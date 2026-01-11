import google.generativeai as genai

# API Key'inizi buraya yapıştırın
GEMINI_API_KEY = "***REMOVED***"
genai.configure(api_key=GEMINI_API_KEY)

print("🔍 Kullanılabilir Modeller Listeleniyor...")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"❌ Hata: {e}")