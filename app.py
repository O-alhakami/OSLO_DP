import os
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

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

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
        flash('تم طلب إنشاء الحساب بنجاح. يرجى انتظار التفعيل من الإدارة.', 'success')
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
                flash('حسابك قيد المراجعة ولم يتم تفعيله بعد.', 'error')
                return redirect(url_for('login'))
            login_user(user)
            return redirect(url_for('index'))
        flash('اسم المستخدم أو كلمة المرور غير صحيحة', 'error')
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
        return "غير مصرح لك بالدخول", 403
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        action = request.form.get('action')
        user = User.query.get(user_id)
        if user:
            if action == 'activate': user.is_active = True
            elif action == 'deactivate': user.is_active = False
            elif action == 'make_admin': user.is_admin = True
            db.session.commit()
    users = User.query.all()
    return render_template('admin.html', users=users)

PROMPTS = {
    "product": "أنت خبير تجارة إلكترونية. استخرج اسم المنتج، مميزاته، وسعره من النص، ونسقها في نقاط.",
    "seo": "أنت خبير سيو. استخرج أفضل 10 كلمات مفتاحية واكتب Meta Description.",
    "marketing": "اكتب منشوراً تسويقياً جذاباً مع عبارات تحفيزية."
}

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
@login_required
def process_text():
    data = request.json
    user_text = data.get('text', '')
    mode = data.get('mode', 'product')
    if not user_text:
        return jsonify({"error": "لم يتم إدخال أي نص"}), 400
        
    full_prompt = f"{PROMPTS.get(mode, PROMPTS['product'])}\n\n--- النص ---\n{user_text}"
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(full_prompt)
        return jsonify({"result": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)