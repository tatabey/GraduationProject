import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Hangi modeli test ediyorsak onun yolunu verelim (Phi-3 veya Llama)
# Şu an Phi-3 ile devam edelim, Llama için yolu değiştirebilirsiniz.
MODEL_PATH = os.path.join(BASE_DIR, "models", "lora_model") 

# --- MODELİ YÜKLE ---
print(f"🚀 Stil Analizi İçin Model Yükleniyor: {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

def style_test(scenario):
    
    # 1. ORTAK PROMPT (Format Emri YOK)
    # Modele bilerek "Şu formatı kullan" DEMİYORUZ.
    # Bakalım Fine-Tuned model kendiliğinden formatı yapacak mı?
    prompt = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Verify compliance with AASTP-1 Table 6 standards.

### Input:
{scenario}

### Response:
"""
    
    inputs = tokenizer([prompt], return_tensors="pt").to("cuda")

    # --- DURUM A: BASE MODEL (Fine-Tuning KAPALI) ---
    # LoRA adaptörlerini geçici olarak devre dışı bırakıyoruz.
    # Model fabrika ayarlarına (saf haline) dönüyor.
    with model.disable_adapter():
        outputs_base = model.generate(
            **inputs, 
            max_new_tokens=128,
            use_cache=True, 
            temperature=0.7 # Biraz daha konuşkan olsun
        )
        res_base = tokenizer.batch_decode(outputs_base)[0]
        if "### Response:\n" in res_base:
            clean_base = res_base.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
        else:
            clean_base = res_base

    # --- DURUM B: FINE-TUNED MODEL (Fine-Tuning AÇIK) ---
    # LoRA adaptörleri devrede. Askeri kimlik aktif.
    outputs_ft = model.generate(
        **inputs, 
        max_new_tokens=128,
        use_cache=True, 
        temperature=0.1 # Daha ciddi ve tutarlı
    )
    res_ft = tokenizer.batch_decode(outputs_ft)[0]
    if "### Response:\n" in res_ft:
        clean_ft = res_ft.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
    else:
        clean_ft = res_ft

    return clean_base, clean_ft

# --- ARAYÜZ TASARIMI ---
with gr.Blocks(theme=gr.themes.Base()) as demo:
    gr.Markdown(
        """
        # 🎭 Fine-Tuning Etkisi: Üslup ve Format Testi
        **Sol Taraf (Base Model):** Modelin eğitilmemiş, ham hali. (Genel amaçlı asistan)
        **Sağ Taraf (Fine-Tuned):** Eğittiğimiz model. (Askeri Denetçi formatı)
        
        *Not: Bu testte RAG (Doküman okuma) KAPALIDIR. Sadece davranış farkına odaklanıyoruz.*
        """
    )
    
    with gr.Row():
        input_text = gr.Textbox(
            label="Senaryo", 
            placeholder="Örn: Group F articles are stored with Group C...",
            lines=2
        )
    
    submit_btn = gr.Button("Stil Farkını Göster", variant="primary")
    
    with gr.Row():
        # SOL KOLON
        with gr.Column():
            gr.Markdown("### 👶 Base Model (Eğitimsiz)")
            output_base = gr.Textbox(label="Çıktı (Sohbet Tarzı)", lines=6, interactive=False)
            gr.Markdown("*Beklenti: Uzun cümleler, sohbet havası, belirsiz format.*")
            
        # SAĞ KOLON
        with gr.Column():
            gr.Markdown("### 👮 Fine-Tuned Model (Eğitilmiş)")
            output_ft = gr.Textbox(label="Çıktı (Askeri Format)", lines=6, interactive=False)
            gr.Markdown("*Beklenti: 'COMPLIANCE / REASONING' formatı, net ve sert üslup.*")

    # Örnek
    gr.Examples(
        examples=[
            ["Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles."]
        ],
        inputs=input_text
    )

    submit_btn.click(fn=style_test, inputs=input_text, outputs=[output_base, output_ft])

if __name__ == "__main__":
    demo.launch(share=True, server_port=7867)