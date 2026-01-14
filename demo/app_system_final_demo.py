import gradio as gr
from unsloth import FastLanguageModel
import torch
import os
import re
import chromadb
from chromadb.utils import embedding_functions
# --- MEVCUT IMPORTLARIN ALTINA EKLEYİN ---
from groq import Groq

# Groq API Anahtarı (https://console.groq.com/keys adresinden alıp buraya yapıştırın)
GROQ_API_KEY = "***REMOVED***" 
# Model: Llama-3.3-70B (Çok güçlü ve hızlı)
API_MODEL_NAME = "llama-3.3-70b-versatile" 

try:
    client_groq = Groq(api_key=GROQ_API_KEY)
except Exception as e:
    print(f"⚠️ Groq istemcisi hatası: {e}")
    client_groq = None
# ==============================================================================
# 1. AYARLAR VE YOL YAPILANDIRMASI
# ==============================================================================
CURRENT_FILE_PATH = os.path.abspath(__file__)
DEMO_DIR = os.path.dirname(CURRENT_FILE_PATH)
BASE_DIR = os.path.dirname(DEMO_DIR)

print(f"📂 Proje Ana Dizini: {BASE_DIR}")

MODEL_PATH = os.path.join(BASE_DIR, "models", "llama", "lora_model") 
DB_PATH = os.path.join(BASE_DIR, "data", "chroma_db")

# ==============================================================================
# 2. MODEL VE DB YÜKLEME
# ==============================================================================
print(f"🚀 Loading Trained Model: {MODEL_PATH}")
if not os.path.exists(MODEL_PATH):
    print("⚠️ WARNING: Local model not found, using base model.")
    MODEL_PATH = "unsloth/Llama-3.2-3B-Instruct"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048, 
    dtype = None,
    load_in_4bit = True,
    gpu_memory_utilization = 0.70,
)
FastLanguageModel.for_inference(model)

if not os.path.exists(DB_PATH):
    raise FileNotFoundError(f"❌ Database not found: {DB_PATH}")

client = chromadb.PersistentClient(path=DB_PATH)
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = client.get_collection(name="aastp1_universal", embedding_function=emb_fn)

# ... (Importlar ve Model Yükleme kısımları aynı) ...

# ==============================================================================
# 3. YARDIMCI FONKSİYONLAR (AKILLI METADATA FİLTRELEME)
# ==============================================================================

# Kimyasal madde anahtar kelimeleri
CHEMICAL_KEYWORDS = [
    "napalm", "toxic", "phosphorous", "wp", "pwp", "tear gas", "smoke",
    "thermite", "thermate", "pyrotechnic", "calcium phosphide",
    "triethylaluminum", "tea", "tpa", "signaling", "isobutyl"
]

def extract_groups(text):
    """
    Sorgudan compatibility grup harflerini çıkarır.
    """
    groups = set()

    # Pattern 1: "Group X" formatı
    matches = re.findall(r'\bGroup\s+([A-S])\b', text, re.IGNORECASE)
    groups.update([m.upper() for m in matches])

    # Pattern 2: "Compatibility Group X" formatı
    matches = re.findall(r'\bCompatibility\s+Group\s+([A-S])\b', text, re.IGNORECASE)
    groups.update([m.upper() for m in matches])

    # Pattern 3: "1.6N", "1.4S" gibi formatlar
    matches = re.findall(r'\b1\.[1-6]([A-S])\b', text)
    groups.update([m.upper() for m in matches])

    return list(groups)

def has_chemical_keyword(text):
    """
    Sorgunun kimyasal madde içerip içermediğini kontrol eder.
    """
    text_lower = text.lower()
    return any(kw in text_lower for kw in CHEMICAL_KEYWORDS)

def detect_query_type(scenario):
    """
    Sorgu tipini tespit eder.
    Returns: "compatibility", "chemical", "general"
    """
    groups = extract_groups(scenario)
    has_chemical = has_chemical_keyword(scenario)

    # İki grup varsa ve depolama/karıştırma bağlamındaysa
    storage_keywords = ["stored", "store", "mix", "mixed", "mixing", "together",
                       "same magazine", "same building", "separation"]
    has_storage_context = any(kw in scenario.lower() for kw in storage_keywords)

    if len(groups) >= 2 and has_storage_context:
        return "compatibility"
    elif has_chemical:
        return "chemical"
    else:
        return "general"

def retrieve_knowledge(scenario):
    """
    AKILLI RAG: Sorgu tipine göre optimize edilmiş arama.
    Yeni hücre bazlı vektör DB yapısını kullanır.
    """
    query_type = detect_query_type(scenario)
    groups = extract_groups(scenario)

    print(f"🔍 Sorgu tipi: {query_type}, Gruplar: {groups}")

    # Sorgu tipine göre strateji
    if query_type == "compatibility" and len(groups) >= 2:
        # Compatibility matrix sorgusu - özelleştirilmiş arama
        return retrieve_compatibility(scenario, groups)
    elif query_type == "chemical":
        # Kimyasal madde sorgusu
        return retrieve_chemical(scenario)
    else:
        # Genel arama
        return retrieve_general(scenario)

# app_system_final.py içindeki retrieve_compatibility fonksiyonunu böyle güncelleyin:

def retrieve_compatibility(scenario, groups):
    """
    ÖNCE Metadata Filtreleme (Kesin Sonuç), BULAMAZSA Semantik Arama.
    """
    print(f"🔍 Performing Matrix Search. Detected groups: {groups}")
    
    unique_docs = []
    
    # 1. STRATEJİ: Kesin Metadata Filtreleme (Varsa en az 2 grup)
    if len(groups) >= 2:
        g1 = groups[0]
        g2 = groups[1]
        
        print(f"🎯 Target Filter: Row={g1}, Col={g2}")
        
        try:
            # ChromaDB 'where' filtresi ile nokta atışı
            results = collection.query(
                query_texts=[""], # Metne bakma, sadece filtreye bak
                n_results=1,      # Tek bir hücre arıyoruz
                where={
                    "$and": [
                        {"type": "compatibility_rule"},
                        {"row": g1},
                        {"col": g2}
                    ]
                }
            )
            
            if results['documents'] and len(results['documents'][0]) > 0:
                doc = results['documents'][0][0]
                print(f"✅ Metadata ile Kural Bulundu: {doc}")
                unique_docs.append(doc)
                
                # Ekstra: İlgili notları da getir (Opsiyonel)
                if "Note" in doc:
                    # Not getirme mantığı buraya eklenebilir
                    pass
                    
                return unique_docs # Kesin bulduk, dönelim.
                
        except Exception as e:
            print(f"⚠️ Filtreleme hatası: {e}")

    # 2. STRATEJİ: Metadata sonuç vermediyse Semantic Search (Fallback)
    # Örn: Kullanıcı grup ismi vermedi, genel bir şey sordu.
    print("⚠️ Metadata ile bulunamadı, genel aramaya geçiliyor...")
    results = collection.query(
        query_texts=[scenario],
        n_results=5,
        where={"type": "compatibility_rule"} # Yine de sadece kurallarda ara
    )
    
    unique_docs.extend(results['documents'][0])
    return unique_docs

def retrieve_chemical(scenario):
    """
    Kimyasal madde sorguları için özelleştirilmiş retrieval.
    """
    all_docs = []

    # 1. Chemical requirement tipinde ara
    try:
        results = collection.query(
            query_texts=[scenario],
            n_results=10,
            where={"type": "chemical_requirement"}
        )
        all_docs.extend(results['documents'][0])
    except:
        pass

    # 2. Genel semantic search
    results = collection.query(
        query_texts=[scenario],
        n_results=10
    )
    all_docs.extend(results['documents'][0])

    # Deduplicate
    seen = set()
    unique_docs = []
    for doc in all_docs:
        if doc not in seen:
            unique_docs.append(doc)
            seen.add(doc)

    return unique_docs[:8]

def retrieve_general(scenario):
    """
    Genel sorgular için retrieval.
    """
    results = collection.query(
        query_texts=[scenario],
        n_results=15
    )

    return results['documents'][0][:8]

# ==============================================================================
# 4. POST-PROCESSING: RAG-BASED VERDICT EXTRACTION
# ==============================================================================

def extract_verdict_from_rag(docs, groups):
    """
    RAG dökümanlarından kesin sonuç çıkarır.
    Model yanılsa bile, RAG'dan gelen bilgiye güvenilir.

    Returns: (verdict, source_doc) veya (None, None)
    """
    if len(groups) < 2:
        return None, None

    g1, g2 = groups[0].upper(), groups[1].upper()

    for doc in docs:
        # Her iki grubu da içeren dökümanı bul
        has_g1 = f"Group {g1}" in doc
        has_g2 = f"Group {g2}" in doc

        if has_g1 and has_g2:
            # Döküman her iki grubu da içeriyor - sonucu çıkar
            doc_upper = doc.upper()

            if "PERMITTED" in doc_upper and "NOT" not in doc_upper:
                return "COMPLIANT", doc
            elif "PROHIBITED" in doc_upper or "CAN NOT" in doc_upper:
                return "NON-COMPLIANT", doc
            elif "CONDITIONAL" in doc_upper:
                return "CONDITIONAL", doc

    return None, None

def extract_chemical_verdict_from_rag(docs, scenario):
    """
    Kimyasal madde sorguları için RAG'dan sonuç çıkarır.
    """
    scenario_lower = scenario.lower()

    for doc in docs:
        doc_lower = doc.lower()

        # Kimyasal madde adını bul
        for chemical in CHEMICAL_KEYWORDS:
            if chemical in scenario_lower and chemical in doc_lower:
                # Bu kimyasal maddeyle ilgili döküman bulundu

                # Ekipman kontrolü
                equipment_issues = []

                if "set 1" in scenario_lower and "set 1" in doc_lower:
                    if "without" in scenario_lower:
                        equipment_issues.append("Set 1 required but missing")

                if "breathing apparatus" in doc_lower:
                    if "without breathing" in scenario_lower or "no breathing" in scenario_lower:
                        equipment_issues.append("Breathing Apparatus required but missing")

                if "apply no water" in doc_lower:
                    if "water" in scenario_lower and ("active" in scenario_lower or "suppression" in scenario_lower):
                        equipment_issues.append("APPLY NO WATER rule violated")

                if equipment_issues:
                    return "NON-COMPLIANT", f"Required equipment missing: {', '.join(equipment_issues)}"

                return "COMPLIANT", doc

    return None, None

# ... (parse_model_response ve generate_html_card) ...

def parse_model_response(text):
    clean_text = text.replace("###", "").replace("**", "").strip()
    
    verdict = "UNKNOWN"
    if "NON-COMPLIANT" in clean_text.upper():
        verdict = "NON-COMPLIANT"
    elif "CONDITIONAL" in clean_text.upper():
        verdict = "CONDITIONAL"
    elif "COMPLIANT" in clean_text.upper():
        verdict = "COMPLIANT"
        
    reasoning_parts = re.split(r"REASONING[:\s\-]+", clean_text, flags=re.IGNORECASE)
    reasoning = reasoning_parts[-1].strip() if len(reasoning_parts) > 1 else clean_text
    
    return verdict, reasoning


def get_api_second_opinion(scenario, context):
    """
    Groq (Llama-3-70B) kullanarak senaryo hakkında kısa bir 'İkinci Görüş' alır.
    """
    if not client_groq:
        return "API Client Not Active"

    try:
        completion = client_groq.chat.completions.create(
            model=API_MODEL_NAME,
            messages=[
                {
                    "role": "system", 
                    "content": "You are a senior NATO auditor. Based STRICTLY on the provided RULES context, provide a single sentence verdict (COMPLIANT/NON-COMPLIANT) and a brief reason. Do not explain process, just judge."
                },
                {
                    "role": "user", 
                    "content": f"RULES:\n{context}\n\nSCENARIO: {scenario}"
                }
            ],
            temperature=0.0,
            max_tokens=100
        )
        return completion.choices[0].message.content
    except Exception as e:
        return f"API Error: {str(e)}"



def generate_html_card(index, scenario, verdict, reasoning, evidence, api_opinion=""):
    # Renk Paleti (Açık Tema İçin)
    if verdict == "COMPLIANT":
        color = "#15803d" # Yeşil (Koyu ton)
        icon = "✅"
        bg = "#f0fdf4"    # Çok açık yeşil arka plan
    elif verdict == "NON-COMPLIANT":
        color = "#b91c1c" # Kırmızı (Koyu ton)
        icon = "⛔"
        bg = "#fef2f2"    # Çok açık kırmızı arka plan
    else:
        color = "#b45309" # Turuncu (Koyu ton)
        icon = "⚠️"
        bg = "#fffbeb"    # Çok açık sarı arka plan

    # Kanıt Listesi (Evidence) - Okunaklı Stil
    evidence_list_html = ""
    keywords = set(re.findall(r"(Note \d+|Table \w+|Set \d+|Group [A-Z])", reasoning, re.IGNORECASE))
    keywords = set([k.upper() for k in keywords])

    for i, doc in enumerate(evidence):
        is_relevant = False
        # Normal Kanıt: Beyaz arka plan, Koyu Gri yazı
        style = "margin-bottom: 6px; padding: 6px; border-radius: 4px; color: #374151; border: 1px solid #e5e7eb; background-color: #ffffff;"
        prefix = f"<span style='color: #6b7280; font-size: 0.8em; font-weight: 600;'>[DOC {i+1}]</span> "
        
        for k in keywords:
            if k in doc.upper():
                is_relevant = True
                break
        
        if is_relevant:
            # Eşleşen Kanıt: Mavi arka plan, Lacivert yazı
            style = "margin-bottom: 6px; padding: 6px; border-radius: 4px; background-color: #eff6ff; color: #1e40af; border-left: 4px solid #3b82f6; border: 1px solid #bfdbfe;"
            prefix = f"<span style='color: #2563eb; font-weight: bold; font-size: 0.8em;'>[MATCHED]</span> "

        evidence_list_html += f"<li style='{style}'>{prefix}{doc}</li>"

    # --- API GÖRÜŞÜ KUTUSU ---
    api_html_block = ""
    if api_opinion:
        api_color = "#2563eb"
        api_bg = "#eff6ff"
        api_text = "#1e3a8a" # Lacivert yazı (okunabilirlik için)
        
        if "NON-COMPLIANT" in api_opinion.upper(): 
            api_color = "#dc2626"
            api_bg = "#fef2f2"
            api_text = "#991b1b"
        elif "COMPLIANT" in api_opinion.upper(): 
            api_color = "#16a34a"
            api_bg = "#f0fdf4"
            api_text = "#166534"
        
        api_html_block = f"""
        <div style="margin-top: 15px; padding: 12px; background-color: {api_bg}; border: 3px solid {api_color}; border-radius: 8px;">
            <div style="font-size: 0.85em; font-weight: 800; color: {api_color}; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.5px;">
                🤖 LLAMA-3.3-70B (via API)
            </div>
            <div style="font-size: 0.95em; color: {api_text}; font-style: italic; font-weight: 500;">
                "{api_opinion}"
            </div>
        </div>
        """

    # HTML Kart Şablonu (Koyu yazılarla güncellendi)
    return f"""
    <div style="border: 4px solid {color}40; border-left: 6px solid {color}; border-radius: 8px; margin-bottom: 24px; background-color: {bg}; font-family: 'Segoe UI', sans-serif; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
        <div style="padding: 20px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                <span style="font-weight: 800; font-size: 1.25em; color: {color}; letter-spacing: 0.5px;">{icon} CASE {index}: {verdict}</span>
            </div>
            
            <div style="margin-bottom: 16px;">
                <p style="margin: 0; color: #64748b; font-size: 0.75em; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">SCENARIO</p>
                <p style="margin: 4px 0; color: #0f172a; font-size: 1.05em; font-weight: 600; line-height: 1.5;">"{scenario}"</p>
            </div>
            
            <div style="margin-bottom: 16px;">
                <p style="margin: 0; color: #64748b; font-size: 0.75em; font-weight: 700; text-transform: uppercase; letter-spacing: 1px;">AI REASONING (Local Model)</p>
                <p style="margin: 4px 0; color: #334155; font-weight: 500; font-size: 1em;">{reasoning}</p>
            </div>
            
            {api_html_block}

            <details style="margin-top: 16px; border-top: 1px solid {color}30; padding-top: 12px;">
                <summary style="cursor: pointer; color: #475569; font-size: 0.9em; font-weight: 600; user-select: none;">
                    🔍 <span style="text-decoration: underline;">Evidence Analysis</span> (Click to expand)
                </summary>
                <ul style="font-size: 0.9em; list-style-type: none; padding-left: 0; margin-top: 10px; max-height: 300px; overflow-y: auto;">
                    {evidence_list_html}
                </ul>
            </details>
        </div>
    </div>
    """


# ==============================================================================
# 4. MAIN PROCESSING ENGINE (UPDATED - ENGLISH UI)
# ==============================================================================

def run_audit(input_text, progress=gr.Progress()):
    # 1. Prepare Scenarios
    scenarios = [line.strip() for line in input_text.split('\n') if line.strip()]
    if not scenarios: 
        yield "Please enter scenarios to analyze."
        return

    full_html = ""
    total_scenarios = len(scenarios)

    # 2. Loop (Streaming with Yield)
    for i, scenario in enumerate(scenarios):
        current_step = i + 1
        
        # --- A. SHOW TEMPORARY LOADING CARD (ENGLISH) ---
        loading_card = f"""
        <div style="padding: 20px; margin-bottom: 24px; border: 2px dashed #3b82f6; border-radius: 8px; background-color: #eff6ff; color: #1e3a8a; text-align: center; font-family: 'Segoe UI', sans-serif;">
            <div style="font-weight: 800; font-size: 1.1em; margin-bottom: 8px;">⚙️ ANALYZING: SCENARIO {current_step} / {total_scenarios}</div>
            <div style="font-size: 0.95em; font-style: italic; color: #3b82f6;">"{scenario}"</div>
            <div style="margin-top: 10px; font-size: 0.8em; color: #60a5fa;">(Scanning knowledge base and awaiting LLM verdict...)</div>
        </div>
        """
        
        # Yield current results + loading card
        yield full_html + loading_card

        # --- B. BACKGROUND PROCESSING ---
        evidence_docs = retrieve_knowledge(scenario)
        groups = extract_groups(scenario)
        query_type = detect_query_type(scenario)
        context_str = "\n".join([f"- {doc}" for doc in evidence_docs])

        # RAG Verdict Extraction
        rag_verdict, rag_source = None, None
        if query_type == "compatibility" and len(groups) >= 2:
            rag_verdict, rag_source = extract_verdict_from_rag(evidence_docs, groups)
        elif query_type == "chemical":
            rag_verdict, rag_source = extract_chemical_verdict_from_rag(evidence_docs, scenario)

        # Prompt Preparation
        alpaca_prompt = f"""Below is an instruction that describes a task.

### Instruction:
You are an AASTP-1 Storage Auditor. Analyze the SCENARIO using ONLY the RULES below.

HOW TO READ THE RULES:
- "Group X can be mixed with Group Y: PERMITTED" = Mixing is ALLOWED (COMPLIANT)
- "Group X can NOT be mixed with Group Y: PROHIBITED" = Mixing is FORBIDDEN (NON-COMPLIANT)
- "CONDITIONAL (Note N)" = Check the Note for special requirements

CRITICAL:
- DO NOT add your own rules or safety requirements
- ONLY use what is written in the RULES context
- If RULES say "PERMITTED", the answer is COMPLIANT

### RULES:
{context_str}

### SCENARIO:
{scenario}

### Your Analysis:
VERDICT: [COMPLIANT/NON-COMPLIANT/CONDITIONAL]
REASONING: [Quote the exact rule that applies]
"""

        # Model Inference
        inputs = tokenizer([alpaca_prompt], return_tensors="pt").to("cuda")
        outputs = model.generate(
            **inputs,
            max_new_tokens=256,
            use_cache=True,
            temperature=0.1
        )
        response_text = tokenizer.batch_decode(outputs)[0].split("### Your Analysis:")[-1].strip().replace("<|end_of_text|>", "")

        # Parse & Override
        model_verdict, model_reasoning = parse_model_response(response_text)
        final_verdict = model_verdict
        final_reasoning = model_reasoning

        if rag_verdict is not None:
            if rag_verdict != model_verdict:
                final_verdict = rag_verdict
                final_reasoning = f"[RAG-VERIFIED] {rag_source[:200]}..." if rag_source else model_reasoning
            else:
                final_reasoning = f"[CONFIRMED] {model_reasoning}"

        # API Second Opinion
        api_opinion_text = get_api_second_opinion(scenario, context_str)

        # --- C. GENERATE PERMANENT CARD ---
        new_card = generate_html_card(current_step, scenario, final_verdict, final_reasoning, evidence_docs, api_opinion=api_opinion_text)
        full_html += new_card

        # --- D. UPDATE VIEW ---
        yield full_html



# ==============================================================================
# 5. TEST SENARYOLARI
# ==============================================================================

TEST_SET_MATRIX = """Found 100kg of Group D stored with Group E without separation.
Found 50kg of Group B stored with 20kg of Group K.
Found 50kg of Group B stored with 20kg of Group D.
Compatibility Group C articles are stored with Compatibility Group S articles.
Compatibility Group H articles are stored in the same magazine as Compatibility Group J articles.
Mixing of Compatibility Group L articles with Compatibility Group F articles."""

TEST_SET_CHEMICAL = """Found Toxic Agents (Group K) stored without full protective clothing Set 1.
Found Napalm stored while water suppression system was active.
What are the safety rules for White Phosphorous (WP)?
Found Smoke HC stored without breathing apparatus.
Can I use water on Calcium Phosphide?"""

TEST_SET_COMPLEX = """Found suspect ammunition stored with Group D items.
Articles of Compatibility Group N are stored with Group S.
Found Group B fuses stored with Group D without NEQ aggregation.
Toxic Agents without explosives components stored as Group K."""

# ==============================================================================
# 6. ARAYÜZ (UI)
# ==============================================================================

css = """
/* Ana Sayfa Genel Ayarları */
body, .gradio-container {
    background-color: #f8fafc !important; 
    color: #1e293b !important;
}

/* --- SOL TARAFTAKİ PANEL (Giriş Kısmı) --- */

/* 1. ETİKET (BAŞLIK) KISMI: Tam Genişlik Lacivert Blok */
.gradio-container label {
    background-color: #1e293b !important; /* Tüm çerçeve Lacivert */
    color: #ffffff !important;           /* Yazı Beyaz */
    border: 2px solid #1e293b !important;
    padding: 10px 15px !important;       /* İç boşluk (Rahat görünüm) */
    border-radius: 8px 8px 0 0 !important; /* Sadece üst köşeleri yuvarla */
    display: block !important;           /* Kutu gibi davranmasını sağlar */
    width: auto !important;              /* Genişliği otomatik ayarla */
    margin-bottom: 0 !important;         /* Altındaki kutuyla birleşsin */
    font-weight: bold !important;
}

/* (Varsa) İçindeki span etiketinin arka planını temizle */
.gradio-container label span {
    background-color: transparent !important;
    color: #ffffff !important;
    padding: 0 !important;
}

/* 2. GİRİŞ KUTUSU (TEXTAREA): Beyaz Kutu, Siyah Yazı */
textarea {
    background-color: #ffffff !important; 
    color: #000000 !important;           /* Yazı Rengi Siyah */
    border: 2px solid #1e293b !important; /* Çerçeve Lacivert */
    border-top: none !important;         /* Üst çizgi yok (Başlıkla bütünleşsin) */
    border-radius: 0 0 8px 8px !important; /* Sadece alt köşeleri yuvarla */
    font-family: 'Consolas', 'Monaco', monospace !important;
    min-height: 200px !important;        /* Biraz daha yüksek olsun */
}

/* --- DİĞER GENEL AYARLAR --- */
.prose { color: #1e293b !important; }
h1, h2, h3 { color: #0f172a !important; }

/* Buton Stili */
button.primary {
    background-color: #2563eb !important;
    color: white !important;
    border-radius: 8px !important;
}
"""

with gr.Blocks(theme=gr.themes.Base(), css=css, title="AASTP-1 AI Auditor") as demo:
    gr.Markdown(
        """
        # 🛡️ AASTP-1 Smart Ammunition Audit System
        """
    )
    
    with gr.Row():
        with gr.Column(scale=1):
            input_box = gr.Textbox(
                label="Audit Scenarios (Enter one case per line)",
                lines=8, 
                placeholder="E.g.: Found Group B stored with Group D...",
                value=TEST_SET_MATRIX 
            )
            
            gr.Markdown("### 🔽 Ready-to-Use Test Batches (Click to Load)")
            gr.Examples(
                examples=[
                    [TEST_SET_MATRIX],
                    [TEST_SET_CHEMICAL],
                    [TEST_SET_COMPLEX]
                ],
                inputs=input_box,
                label="Load Test Scenarios"
            )
            
            audit_btn = gr.Button("🚀 START AUDIT", variant="primary", size="lg")
        
        with gr.Column(scale=2):
            output_html = gr.HTML(label="🔍 Audit Report & Evidence")

    audit_btn.click(fn=run_audit, inputs=input_box, outputs=output_html)

if __name__ == "__main__":
    print("🚀 Sistem Başlatılıyor: http://127.0.0.1:7860")
    demo.queue().launch(share=True)