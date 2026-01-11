# app_phi3_multi_compare.py (Çoklu Karşılaştırma - Gelişmiş Demo)
# İşlevi: Kullanıcı birden fazla senaryoyu alt alta yapıştırır. Sistem hepsini tek tek işler, gelişmiş prompt kullanır ve aşağıya uzun bir rapor dökümü yapar.
#
# Prompt: Critical Rules (Boş hücre kuralı) eklenmiş, daha zeki bir prompt kullanır.

import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# HEDEF: Phi-3 Modeli
MODEL_PATH = os.path.join(BASE_DIR, "models", "lora_model") 
CONTEXT_FILE = os.path.join(BASE_DIR, "data", "context", "Table6_Context.txt")

# --- BAĞLAMI YÜKLE ---
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        RULES_CONTEXT = f.read()
else:
    RULES_CONTEXT = "Error: Context file not found."

# --- MODELİ YÜKLE ---
print(f"🚀 Phi-3 (Multi-Compare Mode) Yükleniyor: {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

def analyze_scenario_pair(scenario):
    """
    Tek bir senaryo için hem SAF (No-RAG) hem de HİBRİT (RAG) tahmini üretir.
    """
    
    # --- 1. SAF MODEL PROMPT (EKSİK OLAN KISIM EKLENDİ) ---
    prompt_no_rag = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Verify compliance with AASTP-1 Table 6 standards.

### Input:
{scenario}

### Response:
"""

    # --- 2. HİBRİT MODEL PROMPT (RAG + ALGORİTMİK MANTIK) ---
    prompt_rag = f"""You are an expert Military Ammunition Storage Inspector.
    
RULES FROM AASTP-1 TABLE 6:
{RULES_CONTEXT}
    
INSTRUCTION:
Determine compliance by following this STRICT DECISION LOGIC:
    
STEP 1: Locate the intersection cell of the two Compatibility Groups in Table 6.
    
STEP 2: CHECK IF THE CELL IS EMPTY.
    - IF EMPTY: STOP immediately. 
    Output: COMPLIANCE: FALSE. 
    Reasoning: "The intersection in Table 6 is an empty cell, indicating strictly prohibited mixing."
    (DO NOT cite Note 1, 2, 4, 5, 6, or 7 for empty cells. Only cite Note 3 if Group L is involved).
    
STEP 3: CHECK IF THE CELL CONTAINS A NOTE REFERENCE (e.g., '2)', '4)', 'X^1)').
    - IF YES: Output: COMPLIANCE: TRUE (Conditional).
    Reasoning: Cite the text of that specific Note found in the cell.
          
STEP 4: CHECK IF THE CELL CONTAINS 'X'.
    - IF YES: Output: COMPLIANCE: TRUE.
    Reasoning: "Mixing is permitted (X)."

SCENARIO TO ANALYZE:
{scenario}
    
### Response:
"""

    # --- TAHMİN 1: SAF MODEL ---
    inputs1 = tokenizer([prompt_no_rag], return_tensors="pt").to("cuda")
    outputs1 = model.generate(**inputs1, max_new_tokens=128, use_cache=True, temperature=0.1)
    res_no_rag = tokenizer.batch_decode(outputs1)[0]
    if "### Response:\n" in res_no_rag:
        res_no_rag = res_no_rag.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()

    # --- TAHMİN 2: HİBRİT MODEL ---
    inputs2 = tokenizer([prompt_rag], return_tensors="pt").to("cuda")
    outputs2 = model.generate(**inputs2, max_new_tokens=256, use_cache=True, temperature=0.1)
    res_rag = tokenizer.batch_decode(outputs2)[0]
    if "### Response:\n" in res_rag:
        res_rag = res_rag.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()

    return res_no_rag, res_rag

def batch_process(multi_input):
    """Listeyi satır satır işler ve karşılaştırmalı rapor oluşturur."""
    
    scenarios = [line.strip() for line in multi_input.split('\n') if line.strip()]
    
    if not scenarios:
        return "⚠️ Lütfen senaryo giriniz."

    # Rapor Başlığı
    full_report = f"# ⚔️ TOPLU KARŞILAŞTIRMA RAPORU\n"
    full_report += f"**Analiz Edilen:** {len(scenarios)} adet senaryo\n"
    full_report += f"**Model:** Phi-3 Mini (Fine-Tuned)\n\n"
    
    for i, scenario in enumerate(scenarios):
        print(f"⏳ Analiz ediliyor ({i+1}/{len(scenarios)}): {scenario[:40]}...")
        
        # Analizi yap
        saf_sonuc, rag_sonuc = analyze_scenario_pair(scenario)
        
        # Görsel Ayrım (Emoji ve Formatlama)
        # RAG'ın düzelttiği durumları vurgula
        if saf_sonuc == rag_sonuc:
            durum = "✅ Modeller Hemfikir"
        else:
            durum = "⚠️ FARK TESPİT EDİLDİ (RAG Düzeltmesi)"

        # Markdown Raporuna Ekle
        full_report += f"---\n"
        full_report += f"## 🛡️ Senaryo {i+1}: {durum}\n"
        full_report += f"> **Girdi:** *{scenario}*\n\n"
        
        # Karşılaştırma Tablosu (veya Yan Yana Bloklar)
        full_report += f"| **🧠 Saf Model (Sadece Hafıza)** | **📘 Hibrit Model (RAG Destekli)** |\n"
        full_report += f"| :--- | :--- |\n"
        # Tablo içinde yeni satırları <br> ile değiştirmemiz gerekebilir
        saf_clean = saf_sonuc.replace("\n", "<br>")
        rag_clean = rag_sonuc.replace("\n", "<br>")
        full_report += f"| {saf_clean} | {rag_clean} |\n\n"
    
    return full_report

# --- ARAYÜZ ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        # 🧪 AASTP-1 AI Karşılaştırma Laboratuvarı
        Bu araç, **Fine-Tuning** (Saf Hafıza) ile **RAG** (Doküman Destekli) yöntemlerini aynı anda test eder.
        Birden fazla senaryo girerek modelin nerede hata yaptığını ve RAG'ın bunu nasıl düzelttiğini görebilirsiniz.
        """
    )
    
    with gr.Row():
        with gr.Column(scale=1):
            input_text = gr.Textbox(
                label="Senaryo Listesi (Her satıra bir tane)", 
                placeholder="Scenario 1...\nScenario 2...",
                lines=12
            )
            submit_btn = gr.Button("⚔️ Karşılaştırmalı Analizi Başlat", variant="primary")
            
            # Hazır Test Paketi (En Kritik Senaryolar)
            gr.Examples(
                examples=[
                    [
"""Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles.
Scenario: Mixing of articles of Compatibility Group G with articles of Compatibility Group C.
Scenario: Compatibility Group L articles are stored in the same storage area as Compatibility Group K articles.
Scenario: Group N articles are stored with Group S.
Scenario: Compatibility Group H articles are stored in the same magazine as Compatibility Group J articles."""
                    ]
                ],
                inputs=input_text,
                label="🧪 Kritik Test Paketi (Tıkla)"
            )

        with gr.Column(scale=2):
            output_text = gr.Markdown(label="Detaylı Karşılaştırma Raporu")
            
    submit_btn.click(fn=batch_process, inputs=input_text, outputs=output_text)

if __name__ == "__main__":
    demo.launch(share=True, server_port=7866)