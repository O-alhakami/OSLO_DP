import os
import requests
from PIL import Image
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "oslo_super_secret_key_123")

db_url = os.environ.get("DATABASE_URL", "sqlite:///users.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY")

# --- نماذج قاعدة البيانات ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.String(50), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

# --- دالة رفع الصور إلى ImgBB ---
def upload_image_to_imgbb(image_file):
    url = "https://api.imgbb.com/1/upload"
    payload = {"key": IMGBB_API_KEY}
    files = {"image": image_file.read()}
    response = requests.post(url, data=payload, files=files)
    if response.status_code == 200:
        return response.json()['data']['url']
    return None

# --- مسارات المصادقة والإدارة (لم تتغير) ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('اسم المستخدم موجود مسبقاً', 'error')
            return redirect(url_for('register'))
        hashed_password = generate_password_hash(password)
        is_first_user = User.query.count() == 0
        new_user = User(username=username, password_hash=hashed_password, is_active=is_first_user, is_admin=is_first_user)
        db.session.add(new_user)
        db.session.commit()
        flash('تم التسجيل. يرجى انتظار التفعيل.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            if not user.is_active:
                flash('حسابك قيد المراجعة.', 'error')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('index'))
        flash('بيانات غير صحيحة', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/admin', methods=['GET', 'POST'])
@login_required
def admin():
    if not current_user.is_admin:
        return "غير مصرح لك", 403
    if request.method == 'POST':
        user = User.query.get(request.form.get('user_id'))
        action = request.form.get('action')
        if user:
            if action == 'activate': user.is_active = True
            elif action == 'deactivate': user.is_active = False
            elif action == 'make_admin': user.is_admin = True
            db.session.commit()
    return render_template('admin.html', users=User.query.all())

# --- مسارات الأداة الأساسية ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
@login_required
def process_text():
    data = request.json
    mode = data.get('mode', 'product')
    prompts = {
        "product": "استخرج اسم المنتج، مميزاته، وسعره من النص ونسقها في نقاط.",
        "seo": "استخرج أفضل كلمات مفتاحية واكتب Meta Description.",
        "marketing": "اكتب منشوراً تسويقياً جذاباً."
    }
    try:
        model = genai.GenerativeModel('gemini-3.8-flash')
        response = model.generate_content(f"{prompts.get(mode)}\n\n{data.get('text', '')}")
        return jsonify({"result": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- مسارات الأرشيف الجديدة ---
@app.route('/archive', methods=['GET', 'POST'])
@login_required
def archive():
    if request.method == 'POST':
        name = request.form.get('name')
        description = request.form.get('description')
        price = request.form.get('price')
        image_file = request.files.get('image')
        
        image_url = None
        if image_file and image_file.filename != '':
            image_url = upload_image_to_imgbb(image_file)
            
        new_product = Product(name=name, description=description, price=price, image_url=image_url)
        db.session.add(new_product)
        db.session.commit()
        flash('تمت أرشفة المنتج بنجاح!', 'success')
        return redirect(url_for('archive'))
        
    return render_template('archive.html')

@app.route('/search', methods=['GET', 'POST'])
@login_required
def search_archive():
    results = []
    if request.method == 'POST':
        try:
            search_text = request.form.get('search_text')
            search_image = request.files.get('search_image')
            
            search_text = search_text.strip() if search_text else ""
            
            # البحث بالنص
            if search_text:
                results = Product.query.filter(Product.name.ilike(f"%{search_text}%")).all()
                
            # البحث بالصورة
            elif search_image and search_image.filename != '':
                # قراءة الصورة كبيانات خام مباشرة بدون Pillow لتوفير الذاكرة
                image_bytes = search_image.read()
                mime_type = search_image.mimetype
                
                image_part = {
                    "mime_type": mime_type,
                    "data": image_bytes
                }
                
                # استخدام الإصدار الرسمي والمستقر
                model = genai.GenerativeModel('gemini-1.5-flash')
                response = model.generate_content([
                    "استخرج اسم هذا المنتج الموجود في الصورة، أو نوعه العام بكلمة أو كلمتين فقط، وبدون أي تفاصيل إضافية ليتم استخدامه ككلمة بحث في قاعدة بيانات.", 
                    image_part
                ])
                
                extracted_keyword = response.text.strip()
                results = Product.query.filter(Product.name.ilike(f"%{extracted_keyword}%")).all()
                flash(f'تم التعرف على الصورة بنجاح كـ: {extracted_keyword}', 'success')
                
        except Exception as e:
            flash(f'حدث خطأ أثناء المعالجة: {str(e)}', 'error')
            
    return render_template('search.html', results=results)