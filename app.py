import os
import secrets
import requests
import base64
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from openai import OpenAI
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

# --- مفاتيح API ---
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
IMGBB_API_KEY = os.environ.get("IMGBB_API_KEY")

# --- نماذج قاعدة البيانات ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)

class Product(db.Model):
    __tablename__ = 'products_v2'
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

# --- دالة رفع الصور لـ ImgBB ---
def upload_image_to_imgbb(image_file):
    url = "https://api.imgbb.com/1/upload"
    payload = {"key": IMGBB_API_KEY}
    files = {"image": image_file.read()}
    response = requests.post(url, data=payload, files=files)
    if response.status_code == 200:
        return response.json()['data']['url']
    return None

# --- محرك OpenRouter الذكي للمحاولات المتعددة والنماذج المجانية ---
# --- محرك OpenRouter الذكي للمحاولات المتعددة والنماذج المجانية ---
def generate_with_openrouter(prompt_text, image_bytes=None, mimetype=None):
    if not OPENROUTER_API_KEY:
        raise Exception("مفتاح OPENROUTER_API_KEY مفقود من الإعدادات.")
        
    # تهيئة عميل OpenAI ليعمل مع سيرفرات OpenRouter
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    
    # تحديد النماذج والمحتوى بناءً على وجود صورة أو لا
    if image_bytes:
        # نماذج مجانية تدعم الرؤية (Vision)
        models = [
            "qwen/qwen-2-vl-7b-instruct:free",
            "google/gemini-1.5-flash-exp:free"
        ]
        base64_image = base64.b64encode(image_bytes).decode('utf-8')
        content = [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": f"data:{mimetype};base64,{base64_image}"}}
        ]
    else:
        # نماذج مجانية قوية جداً للنصوص
        models = [
            "meta-llama/llama-3.1-8b-instruct:free",
            "google/gemma-2-9b-it:free"
        ]
        content = prompt_text

    last_error = ""
    for model_name in models:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": content}],
                # تم تصحيح الكلمة هنا من headers إلى extra_headers لتتوافق مع التحديث الأخير
                extra_headers={
                    "HTTP-Referer": "https://oslo-dp.onrender.com",
                    "X-Title": "OSLO DP"
                }
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            last_error = str(e)
            continue # حاول مع النموذج المجاني التالي
            
    raise Exception(f"فشلت المعالجة من OpenRouter. (آخر خطأ: {last_error})")

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

# --- مسار المعالجة النصية الذكية ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
@login_required
def process_text():
    text = request.form.get('text', '')
    mode = request.form.get('mode', 'product')
    
    system_prompt = """
    أنت صانع محتوى احترافي. التزم بهذه القواعد الصارمة حرفياً ولا تخالفها أبداً:
    1. اكتب النص المطلوب مباشرة بدون أي مقدمات أو ترحيب.
    2. لا تذكر أو تخمن أي سعر نهائياً.
    3. يمنع منعاً باتاً استخدام علامة النجمة (*) أو المربعات في التنسيق. استخدم فقط علامة الشرطة (-) لعمل قائمة نقطية.
    4. يجب أن يكون السطر الأول من الإجابة هو اسم المنتج فقط.
    5. في نهاية النص، اكتب 5 هاشتاجات قوية ومناسبة لانستجرام وتيك توك تتعلق بالمنتج.
    """
    
    prompts = {
        "product": "في السطر الأول اكتب اسم المنتج. في الأسطر التالية استخرج مميزاته ووصفه ونسقها بشكل جذاب للمشتري.",
        "seo": "في السطر الأول اكتب اسم المنتج. ثم اكتب أفضل كلمات مفتاحية (SEO) ووصف تسويقي قصير (Meta Description).",
        "marketing": "في السطر الأول اكتب اسم المنتج. ثم اكتب منشوراً تسويقياً جذاباً مع عبارات تحفيزية."
    }
    
    full_prompt = system_prompt + "\n\nالمطلوب:\n" + prompts.get(mode) + f"\n\nالنص المدخل:\n{text}"
    
    try:
        # معالجة النص باستخدام OpenRouter
        result_text = generate_with_openrouter(full_prompt)
        return jsonify({"result": result_text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- مسارات الأرشيف ---
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
            db.session.rollback()
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
                    
            elif search_image and search_image.filename != '':
                image_bytes = search_image.read()
                mime_type = search_image.mimetype
                
                prompt = "استخرج جميع أسماء المنتجات والأشياء والمكونات الواضحة في هذه الصورة. اكتبها ككلمات مفردة فقط مفصولة بمسافة فارغة بدون أي نصوص أو رموز أخرى."
                
                # استخدام OpenRouter مع الصورة (نماذج الرؤية المجانية)
                result_text = generate_with_openrouter(prompt, image_bytes, mime_type)
                extracted_keywords = result_text.split()
                
                if extracted_keywords:
                    conditions = []
                    for kw in extracted_keywords:
                        if len(kw) > 2:
                            conditions.append(Product.name.ilike(f"%{kw}%"))
                            conditions.append(Product.description.ilike(f"%{kw}%"))
                    if conditions:
                        results = list(set(Product.query.filter(or_(*conditions)).all()))
                        
                kw_string = "، ".join(extracted_keywords)
                if results:
                    flash(f'تم تحليل الصورة (المكونات: {kw_string})', 'success')
                else:
                    flash(f'لا يوجد تطابق في الأرشيف (تم التعرف على: {kw_string})', 'error')
                
        except Exception as e:
            flash(f'حدث خطأ: {str(e)}', 'error')
            
    return render_template('search.html', results=results)

@app.route('/edit_archive')
@login_required
def edit_archive():
    products = Product.query.order_by(Product.id.desc()).all()
    return render_template('edit_archive.html', products=products)

@app.route('/delete_product/<int:id>', methods=['POST'])
@login_required
def delete_product(id):
    product = Product.query.get_or_404(id)
    try:
        db.session.delete(product)
        db.session.commit()
        flash('تم حذف المنتج بنجاح.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'خطأ أثناء الحذف: {str(e)}', 'error')
    return redirect(url_for('edit_archive'))

@app.route('/edit_product/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_product(id):
    product = Product.query.get_or_404(id)
    if request.method == 'POST':
        try:
            product.name = request.form.get('name')
            product.description = request.form.get('description')
            product.price = request.form.get('price')
            
            image_file = request.files.get('image')
            if image_file and image_file.filename != '':
                new_image_url = upload_image_to_imgbb(image_file)
                if new_image_url:
                    product.image_url = new_image_url
                    
            db.session.commit()
            flash('تم تحديث بيانات المنتج بنجاح!', 'success')
            return redirect(url_for('edit_archive'))
        except Exception as e:
            db.session.rollback()
            flash(f'خطأ أثناء التحديث: {str(e)}', 'error')
            
    return render_template('edit_product.html', product=product)

if __name__ == '__main__':
    app.run(debug=True)