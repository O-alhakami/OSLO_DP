import os
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from dotenv import load_dotenv

# تحميل المتغيرات البيئية (للتشغيل المحلي)
load_dotenv()

app = Flask(__name__)

# إعداد Gemini API
API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# البرومبت الثابت (يمكنك تعديله كما تشاء)
FIXED_PROMPT = """
أنت مساعد ذكي متخصص في تحليل المنتجات.
المطلوب: استخرج اسم المنتج، مميزاته الأساسية، وسعره إن وجد من النص التالي، ونسقها في نقاط واضحة ومختصرة.

النص المدخل من المستخدم:
"""

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_text():
    data = request.json
    user_text = data.get('text', '')
    
    if not user_text:
        return jsonify({"error": "الرجاء إدخال نص"}), 400
        
    full_prompt = f"{FIXED_PROMPT}\n{user_text}"
    
    try:
        response = model.generate_content(full_prompt)
        return jsonify({"result": response.text})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)