import os
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=API_KEY)

# قوالب أوامر متعددة لزيادة فائدة الأداة
PROMPTS = {
    "product": "أنت خبير تجارة إلكترونية. استخرج اسم المنتج، مميزاته الأساسية، وسعره إن وجد من النص التالي، ونسقها في نقاط واضحة وجذابة للمشتري.",
    "seo": "أنت خبير تحسين محركات البحث. استخرج أفضل 10 كلمات مفتاحية (SEO Keywords) من النص التالي، واكتب وصفاً قصيراً (Meta Description) للمنتج.",
    "marketing": "أنت صانع محتوى إبداعي. اكتب منشوراً تسويقياً جذاباً لمنصات التواصل الاجتماعي بناءً على هذا النص، مع استخدام عبارات تحفيزية (Call to Action) ورموز تعبيرية مناسبة."
}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_text():
    data = request.json
    user_text = data.get('text', '')
    mode = data.get('mode', 'product')
    
    if not user_text:
        return jsonify({"error": "لم يتم إدخال أي نص للمعالجة."}), 400
        
    selected_prompt = PROMPTS.get(mode, PROMPTS["product"])
    full_prompt = f"{selected_prompt}\n\n--- النص المدخل ---\n{user_text}"
    
    try:
        # تحديد الإصدار المطلوب مباشرة وتخطي البحث التلقائي
        model = genai.GenerativeModel('gemini-3.8-flash')
        response = model.generate_content(full_prompt)
        
        return jsonify({"result": response.text})
        
    except Exception as e:
        return jsonify({"error": f"حدث خطأ أثناء الاتصال بالخادم: {str(e)}"}), 500

if __name__ == '__main__':
    app.run(debug=True)