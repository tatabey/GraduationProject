import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "lora_model")
CONTEXT_FILE = os.path.join(BASE_DIR, "data", "context", "Table6_Context.txt")

# --- BAĞLAMI YÜKLE (KOPYA KAĞIDI) ---
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        RULES_CONTEXT = f.read()
else:
    RULES_CONTEXT = "Error: Rules file not found."

# --- MODELİ YÜKLE ---
print(f"🚀 Model Yükleniyor: {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

def ask_auditor(scenario):
    # RAG TEKNİĞİ: Kuralları prompt'un içine gömüyoruz.
    # Model artık ezberden değil, bu metinden okuyarak cevap verecek.
    
    prompt = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

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
    
    inputs = tokenizer([prompt], return_tensors="pt").to("cuda")
    
    outputs = model.generate(
        **inputs, 
        max_new_tokens = 256,
        use_cache = True,
        temperature = 0.1, # Yaratıcılığı kısıtla, kurallara uy.
    )
    
    response = tokenizer.batch_decode(outputs)[0]
    if "### Response:\n" in response:
        clean_response = response.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
    else:
        clean_response = response
        
    return clean_response

# --- ARAYÜZ ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        # 🛡️ AI Military Storage Auditor (AASTP-1)
        **Bitirme Projesi POC** | Model: Phi-3 Fine-Tuned + Context Injection
        """
    )
    
    with gr.Row():
        with gr.Column():
            input_text = gr.Textbox(
                label="Senaryo Giriniz", 
                placeholder="Örn: Group B fuses are stored with Group F articles...",
                lines=3
            )
            submit_btn = gr.Button("Denetle (Audit)", variant="primary")
            
            gr.Examples(
                examples=[
                    ["Scenario: Compatibility Group B fuses are stored in the same magazine with Compatibility Group F articles."],
                    ["Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles."],
                    ["Scenario: Compatibility Group L articles are stored with Group K."],
                    ["Scenario: Group N articles are stored with Group S."],
                ],
                inputs=input_text
            )

        with gr.Column():
            output_text = gr.Textbox(label="Denetim Raporu", lines=6, interactive=False)
            
    submit_btn.click(fn=ask_auditor, inputs=input_text, outputs=output_text)

if __name__ == "__main__":
    demo.launch(share=True)