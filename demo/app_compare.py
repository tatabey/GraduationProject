# app_compare.py (Tekli Karşılaştırma - Basit Demo)
# Kullanıcı tek bir senaryo girer. Sistem bunu hem "Saf Model" (No-RAG) hem de "Hibrit Model" (RAG) ile analiz eder ve yan yana gösterir.
# Bu versiyonda Critical Rules (Boş hücre kuralı) gibi gelişmiş prompt mühendisliği YOKTUR. Daha ham bir karşılaştırma yapar.
# ÜST VERSİYONU: app_phi3_multi_compare.py (Çoklu Karşılaştırma - Gelişmiş Demo)

import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "lora_model")
CONTEXT_FILE = os.path.join(BASE_DIR, "data", "context", "Table6_Context.txt")

# --- BAĞLAMI YÜKLE ---
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        RULES_CONTEXT = f.read()
else:
    RULES_CONTEXT = "Error: Context file not found."

# --- MODELİ YÜKLE (TEK SEFER) ---
# Modeli bir kere yüklüyoruz, iki farklı yöntemle sorgulayacağız.
print(f"🚀 Model Yükleniyor: {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

# --- ANA FONKSİYON ---
def compare_models(scenario):
    
    # 1. YÖNTEM: SAF HAFIZA (NO RAG)
    # Modele kuralları vermiyoruz. Sadece eğitimden hatırladığını soruyoruz.
    prompt_no_rag = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Verify compliance with AASTP-1 Table 6 standards.

### Input:
{scenario}

### Response:
"""
    
    # 2. YÖNTEM: BAĞLAM ENJEKSİYONU (WITH RAG)
    # Modele kuralları (Context) veriyoruz.
    prompt_rag = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
You are an expert Military Ammunition Storage Inspector. 
Use the provided AASTP-1 TABLE 6 RULES below to determine compliance.
Strictly follow the Notes (1-7) and the Matrix.

--- RULES START ---
{RULES_CONTEXT}
--- RULES END ---

Verify compliance for the following scenario.

### Input:
{scenario}

### Response:
"""

    # --- MODEL ÇALIŞTIRMA (NO RAG) ---
    inputs_1 = tokenizer([prompt_no_rag], return_tensors="pt").to("cuda")
    outputs_1 = model.generate(**inputs_1, max_new_tokens=128, use_cache=True, temperature=0.1)
    response_1 = tokenizer.batch_decode(outputs_1)[0].split("### Response:\n")[1].replace("<|endoftext|>", "").strip()

    # --- MODEL ÇALIŞTIRMA (WITH RAG) ---
    inputs_2 = tokenizer([prompt_rag], return_tensors="pt").to("cuda")
    outputs_2 = model.generate(**inputs_2, max_new_tokens=256, use_cache=True, temperature=0.1)
    response_2 = tokenizer.batch_decode(outputs_2)[0].split("### Response:\n")[1].replace("<|endoftext|>", "").strip()

    return response_1, response_2

# --- ARAYÜZ TASARIMI ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        # ⚔️ AI Model Karşılaştırması: Fine-Tuning vs. Hibrit (RAG)
        **Sol taraf:** Model sadece hafızasını kullanır. **Sağ taraf:** Model dokümanı okuyarak cevap verir.
        """
    )
    
    with gr.Row():
        input_text = gr.Textbox(
            label="Askeri Depolama Senaryosu", 
            placeholder="Örn: Compatibility Group F articles are stored in the same building as Compatibility Group C articles...",
            lines=2
        )
    
    submit_btn = gr.Button("Analizi Başlat (Compare)", variant="primary")
    
    with gr.Row():
        # SOL KOLON
        with gr.Column():
            gr.Markdown("### 🧠 Saf Model (Sadece Hafıza)")
            output_no_rag = gr.Textbox(label="Sonuç (No Context)", lines=10, interactive=False)
            gr.Markdown("*Risk: Halüsinasyon görebilir veya kuralları karıştırabilir.*")
            
        # SAĞ KOLON
        with gr.Column():
            gr.Markdown("### 🛡️ Hibrit Model (RAG + Fine-Tune)")
            output_rag = gr.Textbox(label="Sonuç (Context Aware)", lines=10, interactive=False)
            gr.Markdown("*Avantaj: Kuralları metinden okuduğu için kesindir.*")

    # Örnekler
    gr.Examples(
        examples=[
            ["Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles."], # Note 2 (Zor)
            ["Scenario: Mixing of articles of Compatibility Group G with articles of Compatibility Group C."], # Note 4 (Zor)
            ["Scenario: Compatibility Group L articles are stored in the same storage area as Compatibility Group K articles."], # Yasak (Kolay)
            ["Scenario: Group N articles are stored with Group S."] # Note 7 (Karmaşık)
        ],
        inputs=input_text
    )

    submit_btn.click(fn=compare_models, inputs=input_text, outputs=[output_no_rag, output_rag])

if __name__ == "__main__":
    demo.launch(share=True)