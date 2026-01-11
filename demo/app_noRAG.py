import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "lora_model")

# DİKKAT: Context (Kurallar) dosyası BİLEREK yüklenmiyor.
# Amaç: Modelin sadece eğitim hafızasını (Fine-Tuning) test etmek.

# --- MODELİ YÜKLE ---
print(f"🚀 Model Yükleniyor (Saf Hafıza Modu): {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

def ask_auditor_raw(scenario):
    # --- NO RAG (Sadece Fine-Tuning) ---
    # Prompt içine kuralları eklemiyoruz. 
    # Sadece eğitimi başlattığımız standart Alpaca formatını kullanıyoruz.
    
    prompt = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Verify compliance with AASTP-1 Table 6 standards.

### Input:
{scenario}

### Response:
"""
    
    inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
    
    outputs = model.generate(
        **inputs, 
        max_new_tokens = 128,
        use_cache = True,
        temperature = 0.1, 
    )
    
    response = tokenizer.batch_decode(outputs)[0]
    if "### Response:\n" in response:
        clean_response = response.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
    else:
        clean_response = response
        
    return clean_response

# --- ARAYÜZ (Kırmızı Tema - Farklı Olduğu Belli Olsun) ---
with gr.Blocks(theme=gr.themes.Base()) as demo:
    gr.Markdown(
        """
        # 🧠 AI Auditor (NO RAG - Sadece Hafıza)
        **DİKKAT:** Bu modda modele kurallar verilmez. Sadece eğitim hafızasını kullanır.
        """
    )
    
    with gr.Row():
        with gr.Column():
            input_text = gr.Textbox(
                label="Senaryo Giriniz", 
                placeholder="Örn: Group B fuses are stored with Group F articles...",
                lines=3
            )
            submit_btn = gr.Button("Hafızadan Denetle", variant="secondary") # Kırmızı/Gri buton
            
            gr.Examples(
                examples=[
                    ["Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles."],
                    ["Scenario: Mixing of articles of Compatibility Group G with articles of Compatibility Group C."],
                    ["Scenario: Compatibility Group L articles are stored with Group K."],
                ],
                inputs=input_text
            )

        with gr.Column():
            output_text = gr.Textbox(label="Denetim Raporu (Saf Model Çıktısı)", lines=6, interactive=False)
            
    submit_btn.click(fn=ask_auditor_raw, inputs=input_text, outputs=output_text)

if __name__ == "__main__":
    demo.launch(share=True, server_port=7861) # Portu değiştirdim (7861), diğer app ile çakışmasın.