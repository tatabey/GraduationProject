import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# HEDEF: Llama Modeli
MODEL_PATH = os.path.join(BASE_DIR, "models", "llama", "lora_model") 
CONTEXT_FILE = os.path.join(BASE_DIR, "data", "context", "Table6_Context.txt")

# --- BAĞLAMI YÜKLE (KOPYA KAĞIDI) ---
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        RULES_CONTEXT = f.read()
else:
    RULES_CONTEXT = "Error: Context file not found."

# --- MODELİ YÜKLE ---
print(f"🚀 Llama Yükleniyor: {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

def compare_llama(scenario):
    
    # 1. SOL KÖŞE: SAF LLAMA (NO RAG)
    # Modele kuralları vermiyoruz. Sadece "Eğitimde ne öğrendiysen onu söyle" diyoruz.
    prompt_no_rag = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Verify compliance with AASTP-1 Table 6 standards.

### Input:
{scenario}

### Response:
"""
    
    # 2. YÖNTEM: BAĞLAM ENJEKSİYONU (WITH RAG)
    # Modele "Boş hücre kuralını" açıkça öğretiyoruz.
    
    prompt_rag = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
You are an expert Military Ammunition Storage Inspector. 
Use the provided AASTP-1 TABLE 6 RULES below to determine compliance.

--- RULES START ---
{RULES_CONTEXT}
--- RULES END ---

*** CRITICAL RULES FOR REASONING ***
1. If the intersection cell in the table contains specific Notes (e.g., '2)', '4)'), cite that specific Note.
2. If the intersection cell is EMPTY (Blank), the mixing is PROHIBITED.
   - Output must be: COMPLIANCE: FALSE
   - Reasoning must start with: "The intersection in Table 6 is an empty cell, indicating strictly prohibited mixing."
   - DO NOT cite Note 1, 2, or 4 for empty cells. Only Note 3 applies to Group L.

Verify compliance for the following scenario.

### Input:
{scenario}

### Response:
"""

    # --- MODEL ÇALIŞTIRMA (SAF) ---
    inputs_1 = tokenizer([prompt_no_rag], return_tensors="pt").to("cuda")
    outputs_1 = model.generate(**inputs_1, max_new_tokens=128, use_cache=True, temperature=0.1)
    response_1 = tokenizer.batch_decode(outputs_1)[0]
    if "### Response:\n" in response_1:
        clean_1 = response_1.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
    else:
        clean_1 = response_1

    # --- MODEL ÇALIŞTIRMA (RAG) ---
    inputs_2 = tokenizer([prompt_rag], return_tensors="pt").to("cuda")
    outputs_2 = model.generate(**inputs_2, max_new_tokens=256, use_cache=True, temperature=0.1)
    response_2 = tokenizer.batch_decode(outputs_2)[0]
    if "### Response:\n" in response_2:
        clean_2 = response_2.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
    else:
        clean_2 = response_2

    return clean_1, clean_2

# --- ARAYÜZ TASARIMI (Carbon Teması) ---
with gr.Blocks(theme=gr.themes.Monochrome()) as demo:
    gr.Markdown(
        """
        # ⚔️ Llama-3.2 Arena: Fine-Tuning vs. RAG
        **Sol Taraf:** Llama sadece eğitim hafızasını kullanır. (Riskli)
        **Sağ Taraf:** Llama dokümanı okuyarak cevap verir. (Güvenli)
        """
    )
    
    with gr.Row():
        input_text = gr.Textbox(
            label="Senaryo Giriniz", 
            placeholder="Örn: Group F articles are stored with Group C...",
            lines=2
        )
    
    submit_btn = gr.Button("Analiz Et ve Karşılaştır", variant="primary")
    
    with gr.Row():
        # SOL KOLON
        with gr.Column():
            gr.Markdown("### 🧠 Saf Llama (Sadece Hafıza)")
            output_no_rag = gr.Textbox(label="Çıktı (No Context)", lines=8, interactive=False)
            gr.Markdown("⚠️ *Ezber hatası veya aşırı güvenlik (Over-refusal) riski.*")
            
        # SAĞ KOLON
        with gr.Column():
            gr.Markdown("### 🛡️ Hibrit Llama (RAG Destekli)")
            output_rag = gr.Textbox(label="Çıktı (Context Aware)", lines=8, interactive=False)
            gr.Markdown("✅ *Kuralları metinden okuduğu için kesin sonuç.*")

    # Hazır Örnekler
    gr.Examples(
        examples=[
            ["Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles."], # Note 2 (Llama burada takılabilir)
            ["Scenario: Mixing of articles of Compatibility Group G with articles of Compatibility Group C."], # Note 4
            ["Scenario: Compatibility Group L articles are stored with Group K."], # Yasak
            ["Scenario: Group N articles are stored with Group S."] # Note 7
        ],
        inputs=input_text
    )

    submit_btn.click(fn=compare_llama, inputs=input_text, outputs=[output_no_rag, output_rag])

if __name__ == "__main__":
    demo.launch(share=True, server_port=7864)