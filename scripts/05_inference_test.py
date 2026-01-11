from unsloth import FastLanguageModel
import torch
import os

# --- MODEL YOLLARI ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Final kaydedilen model klasörünü hedefliyoruz
MODEL_PATH = os.path.join(BASE_DIR, "models", "llama", "lora_model")

def test_model_interactive():
    print(f"📂 Eğitilmiş Model Yükleniyor: {MODEL_PATH}")
    
    # 1. Modeli ve Tokenizer'ı Yükle (Eğitimdeki ayarlarla aynı olmalı)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = MODEL_PATH, 
        max_seq_length = 2048,
        dtype = None,
        load_in_4bit = True,
    )
    
    # Inference modu (Daha hızlı çalışması için)
    FastLanguageModel.for_inference(model)

    # 2. Prompt Şablonu (Eğitimdekiyle AYNI olmalı)
    alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Evaluate compliance with AASTP-1 standards.

### Input:
{}

### Response:
"""

    print("\n✅ Model Hazır! Çıkmak için 'q' yazın.\n")

    while True:
        # Kullanıcıdan senaryo al
        user_scenario = input("📝 Bir senaryo yazın (Örn: 'Found 50kg of Group B stored with Group D.'): ")
        
        if user_scenario.lower() == 'q':
            break
            
        # Tokenize ve GPU'ya taşı
        inputs = tokenizer(
            [alpaca_prompt.format(user_scenario)], 
            return_tensors = "pt"
        ).to("cuda")

        # Cevap Üret
        outputs = model.generate(
            **inputs, 
            max_new_tokens = 128, # Cevap uzunluğu
            use_cache = True,
            temperature = 0.1 # Test ederken tutarlı olsun diye düşük sıcaklık
        )
        
        # Cevabı temizle
        decoded_output = tokenizer.batch_decode(outputs)[0]
        # Sadece "Response" kısmını al
        response_text = decoded_output.split("### Response:")[-1].strip().replace("<|end_of_text|>", "")
        
        print(f"\n🤖 MODEL KARARI:\n{response_text}\n")
        print("-" * 50)

if __name__ == "__main__":
    test_model_interactive()