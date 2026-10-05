import os
import secrets
import requests
import io
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import google.generativeai as genai
from dotenv import load_dotenv
from sqlalchemy import or_

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "oslo_super_secret_key_123")

db_url = os.environ.get("DATABASE_URL", "sqlite:///oslo_v2.db")
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
    __tablename__ = 'products_v2' # هذا السطر سيجبر النظام على إنشاء جدول جديد محدث
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    price = db.Column(db.String(50), nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

# --- دالة رفع الصور ---
def upload_image_to_imgbb(image_file):
    url = "https://api.imgbb.com/1/upload"
    payload = {"key": IMGBB_API_KEY}
    files = {"image": image_file.read()}
    response = requests.post(url, data=payload, files=files)
    if response.status_code == 200:
        return response.json()['data']['url']
    return None

# --- مسارات المصادقة والإدارة ---
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
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password_hash, request.form.get('password')):
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
        return "غير مصرح", 403
    if request.method == 'POST':
        user = User.query.get(request.form.get('user_id'))
        action = request.form.get('action')
        if user:
            if action == 'activate': user.is_active = True
            elif action == 'deactivate': user.is_active = False
            elif action == 'make_admin': user.is_admin = True
            db.session.commit()
    return render_template('admin.html', users=User.query.all())

# --- مسار المعالجة الذكية ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
@login_required
def process_text():
    text = request.form.get('text', '')
    mode = request.form.get('mode', 'product')
    image_file = request.files.get('image')
    
    # أوامر هندسة نصوص صارمة لتنفيذ طلبك بالحرف
    system_prompt = """
    أنت صانع محتوى احترافي. التزم بهذه القواعد الصارمة حرفياً ولا تخالفها أبداً:
    1. اكتب النص المطلوب مباشرة بدون أي مقدمات أو ترحيب (لا تكتب "إليك الوصف" أو "بناءً على الصورة").
    2. لا تذكر أو تخمن أي سعر نهائياً.
    3. يمنع منعاً باتاً استخدام علامة النجمة (*) أو المربعات في التنسيق. استخدم فقط علامة الشرطة (-) لعمل قائمة نقطية.
    4. إذا كان هناك صورة مرفقة، استخرج بدقة أسماء الأشياء والمكونات التي تراها في الصورة وادمجها بتناسق كجزء من الوصف والمميزات.
    5. يجب أن يكون السطر الأول من الإجابة هو اسم المنتج فقط.
    6. في نهاية النص تماماً، اترك سطراً فارغاً ثم اكتب 5 هاشتاجات قوية ومناسبة لانستجرام وتيك توك تتعلق بالمنتج ومكوناته.
    """
    
    prompts = {
        "product": "في السطر الأول اكتب اسم المنتج. في الأسطر التالية اكتب مميزاته ووصفه ومكوناته بشكل جذاب للمشتري.",
        "seo": "في السطر الأول اكتب اسم المنتج. ثم اكتب أفضل كلمات مفتاحية (SEO) ووصف تسويقي قصير (Meta Description).",
        "marketing": "في السطر الأول اكتب اسم المنتج. ثم اكتب منشوراً تسويقياً جذاباً مع عبارات تحفيزية."
    }
    
    content_to_send = [system_prompt + "\nالمطلوب: " + prompts.get(mode) + f"\n\nالنص المدخل:\n{text}"]
    
    if image_file and image_file.filename != '':
        image_bytes = image_file.read()
        content_to_send.append({"mime_type": image_file.mimetype, "data": image_bytes})
        
    try:
        model = genai.GenerativeModel('gemini-3.8-flash')
        response = model.generate_content(content_to_send)
        return jsonify({"result": response.text.strip()})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- مسارات الأرشيف والبحث ---
@app.route('/archive', methods=['GET', 'POST'])
@login_required
def archive():
    if request.method == 'POST':
        try:
            name = request.form.get('name')
            description = request.form.get('description')
            price = request.form.get('price')
            image_file = request.files.get('image')
            
            image_url = None
            if image_file and image_file.filename != '':
                image_url = upload_image_to_imgbb(image_file)
                
            unique_code = f"PRD-{secrets.token_hex(3).upper()}"
                
            new_product = Product(code=unique_code, name=name, description=description, price=price, image_url=image_url)
            db.session.add(new_product)
            db.session.commit()
            flash(f'تمت أرشفة المنتج بنجاح! كود المنتج: {unique_code}', 'success')
        except Exception as e:
            db.session.rollback() # التراجع عن العملية لتجنب تعليق قاعدة البيانات
            flash(f'فشلت عملية الأرشفة: {str(e)}', 'error')
            
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
            
            # البحث النصي (اسم، وصف، أو كود)
            if search_text:
                keywords = search_text.split()
                conditions = []
                for kw in keywords:
                    if len(kw) > 1:
                        conditions.append(Product.name.ilike(f"%{kw}%"))
                        conditions.append(Product.description.ilike(f"%{kw}%"))
                        conditions.append(Product.code.ilike(f"%{kw}%"))
                
                if conditions:
                    results = list(set(Product.query.filter(or_(*conditions)).all()))
                    
            # البحث بالصورة (تفكيك المكونات والمطابقة)
            elif search_image and search_image.filename != '':
                image_bytes = search_image.read()
                image_part = {"mime_type": search_image.mimetype, "data": image_bytes}
                
                model = genai.GenerativeModel('gemini-3.8-flash')
                prompt = "استخرج جميع أسماء المنتجات والأشياء والمكونات الواضحة في هذه الصورة. اكتبها ككلمات مفردة فقط مفصولة بمسافة فارغة بدون أي نصوص أو رموز أخرى."
                response = model.generate_content([prompt, image_part])
                
                extracted_keywords = response.text.strip().split()
                
                if extracted_keywords:
                    conditions = []
                    for kw in extracted_keywords:
                        if len(kw) > 2: # تجاهل الحروف والكلمات القصيرة جداً
                            conditions.append(Product.name.ilike(f"%{kw}%"))
                            conditions.append(Product.description.ilike(f"%{kw}%"))
                            
                    if conditions:
                        results = list(set(Product.query.filter(or_(*conditions)).all()))
                        
                kw_string = "، ".join(extracted_keywords)
                if results:
                    flash(f'تم تحليل مكونات الصورة بنجاح: ({kw_string})', 'success')
                else:
                    flash(f'تعرف الذكاء الاصطناعي على: ({kw_string}) ولكن لم يعثر على تطابق في الأرشيف.', 'error')
                
        except Exception as e:
            flash(f'حدث خطأ أثناء المعالجة: {str(e)}', 'error')
            
    return render_template('search.html', results=results)

if __name__ == '__main__':
    app.run(debug=True)