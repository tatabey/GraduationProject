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
print(f"🚀 Eğitilmiş Model Yükleniyor: {MODEL_PATH}")
if not os.path.exists(MODEL_PATH):
    print("⚠️ UYARI: Yerel model bulunamadı, base model kullanılıyor.")
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
    raise FileNotFoundError(f"❌ Veritabanı yok: {DB_PATH}")

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
    print(f"🔍 Matrix Araması Yapılıyor. Tespit edilen gruplar: {groups}")
    
    unique_docs = []
    
    # 1. STRATEJİ: Kesin Metadata Filtreleme (Varsa en az 2 grup)
    if len(groups) >= 2:
        g1 = groups[0]
        g2 = groups[1]
        
        print(f"🎯 Hedef Filtre: Row={g1}, Col={g2}")
        
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
    if verdict == "COMPLIANT":
        color = "#28a745" # Yeşil
        icon = "✅"
        bg = "rgba(40, 167, 69, 0.05)"
    elif verdict == "NON-COMPLIANT":
        color = "#dc3545" # Kırmızı
        icon = "⛔"
        bg = "rgba(220, 53, 69, 0.05)"
    else:
        color = "#ffc107" # Sarı
        icon = "⚠️"
        bg = "rgba(255, 193, 7, 0.05)"

    # Kanıt Vurgulama
    evidence_list_html = ""
    keywords = set(re.findall(r"(Note \d+|Table \w+|Set \d+|Group [A-Z])", reasoning, re.IGNORECASE))
    keywords = set([k.upper() for k in keywords])

    for i, doc in enumerate(evidence):
        is_relevant = False
        style = "margin-bottom: 6px; padding: 4px; border-radius: 4px; color: #a0aec0;"
        prefix = f"<span style='color: #666; font-size: 0.8em;'>[DOC {i+1}]</span> "
        
        for k in keywords:
            if k in doc.upper():
                is_relevant = True
                break
        
        if is_relevant:
            style = "margin-bottom: 6px; padding: 6px; border-radius: 4px; background-color: rgba(255, 255, 255, 0.1); color: #fff; border-left: 3px solid #63b3ed;"
            prefix = f"<span style='color: #63b3ed; font-weight: bold; font-size: 0.8em;'>[MATCHED]</span> "

        evidence_list_html += f"<li style='{style}'>{prefix}{doc}</li>"

    # --- API GÖRÜŞÜ KUTUSU ---
    api_html_block = ""
    if api_opinion:
        api_color = "#3b82f6" # Mavi
        if "NON-COMPLIANT" in api_opinion.upper(): api_color = "#ef4444"
        elif "COMPLIANT" in api_opinion.upper(): api_color = "#22c55e"
        
        api_html_block = f"""
        <div style="margin-top: 15px; padding: 10px; background-color: rgba(30, 41, 59, 0.5); border-left: 4px solid {api_color}; border-radius: 4px;">
            <div style="font-size: 0.85em; font-weight: bold; color: {api_color}; margin-bottom: 4px; text-transform: uppercase;">
                🤖 {API_MODEL_NAME} (Second Opinion)
            </div>
            <div style="font-size: 0.95em; color: #e2e8f0; font-style: italic;">
                "{api_opinion}"
            </div>
        </div>
        """

    return f"""
    <div style="border: 1px solid {color}; border-left: 5px solid {color}; border-radius: 8px; margin-bottom: 20px; background-color: {bg}; font-family: sans-serif;">
        <div style="padding: 15px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <span style="font-weight: bold; font-size: 1.2em; color: {color};">{icon} CASE {index}: {verdict}</span>
            </div>
            <div style="margin-bottom: 15px;">
                <p style="margin: 0; color: #aaa; font-size: 0.9em;">SCENARIO</p>
                <p style="margin: 5px 0; color: #fff; font-style: italic;">"{scenario}"</p>
            </div>
            <div style="margin-bottom: 15px;">
                <p style="margin: 0; color: #aaa; font-size: 0.9em;">AI REASONING (Local Model)</p>
                <p style="margin: 5px 0; color: #fff; font-weight: 500;">{reasoning}</p>
            </div>
            
            {api_html_block}

            <details open style="margin-top: 15px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 10px;">
                <summary style="cursor: pointer; color: #aaa; font-size: 0.9em;">🔍 <b>Evidence Analysis</b> (RAG Context)</summary>
                <ul style="font-size: 0.85em; list-style-type: none; padding-left: 0; margin-top: 10px;">
                    {evidence_list_html}
                </ul>
            </details>
        </div>
    </div>
    """


# ==============================================================================
# 4. ANA İŞLEM MOTORU (GÜNCELLENMİŞ PROMPT)
# ==============================================================================

def run_audit(input_text):
    scenarios = [line.strip() for line in input_text.split('\n') if line.strip()]
    if not scenarios: return "Lütfen analiz edilecek senaryoları girin."

    full_html = ""

    for i, scenario in enumerate(scenarios):
        # A. RAG - Akıllı retrieval
        evidence_docs = retrieve_knowledge(scenario)
        groups = extract_groups(scenario)
        query_type = detect_query_type(scenario)
        context_str = "\n".join([f"- {doc}" for doc in evidence_docs])

        # B. RAG'DAN DİREKT SONUÇ ÇIKARMAYI DENE (POST-PROCESSING)
        rag_verdict = None
        rag_source = None

        if query_type == "compatibility" and len(groups) >= 2:
            rag_verdict, rag_source = extract_verdict_from_rag(evidence_docs, groups)
        elif query_type == "chemical":
            rag_verdict, rag_source = extract_chemical_verdict_from_rag(evidence_docs, scenario)

        # C. YENİ PROMPT - Döküman formatına uygun
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

        # D. MODEL INFERENCE
        inputs = tokenizer([alpaca_prompt], return_tensors="pt").to("cuda")
        outputs = model.generate(
            **inputs,
            max_new_tokens=256,
            use_cache=True,
            temperature=0.1
        )

        response_text = tokenizer.batch_decode(outputs)[0].split("### Your Analysis:")[-1].strip().replace("<|end_of_text|>", "")

        # E. PARSE MODEL RESPONSE
        model_verdict, model_reasoning = parse_model_response(response_text)

        # F. OVERRIDE MANTIĞI - RAG sonucu varsa ve model yanıldıysa düzelt
        final_verdict = model_verdict
        final_reasoning = model_reasoning

        if rag_verdict is not None:
            if rag_verdict != model_verdict:
                # Model yanıldı, RAG sonucunu kullan
                final_verdict = rag_verdict
                final_reasoning = f"[RAG-VERIFIED] {rag_source[:200]}..." if rag_source else model_reasoning
                print(f"⚠️ Override: Model={model_verdict} → RAG={rag_verdict}")
            else:
                # Model ve RAG aynı fikirde
                final_reasoning = f"[CONFIRMED] {model_reasoning}"

        # F. API SECOND OPINION (GROQ) -- BURAYI EKLEYİN
        print(f"🌍 Groq API'ye soruluyor: Case {i+1}...")
        api_opinion_text = get_api_second_opinion(scenario, context_str)

        # G. HTML ÇIKTI (api_opinion parametresini ekleyerek) -- BURAYI GÜNCELLEYİN
        full_html += generate_html_card(i+1, scenario, final_verdict, final_reasoning, evidence_docs, api_opinion=api_opinion_text)

    return full_html

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
body {background-color: #0f172a;}
.gradio-container {background-color: #0f172a; color: white;}
textarea {background-color: #1e293b !important; color: white !important; border: 1px solid #334155 !important;}
.prose {color: white !important;}
"""

with gr.Blocks(theme=gr.themes.Soft(), css=css, title="AASTP-1 AI Auditor") as demo:
    gr.Markdown(
        """
        # 🛡️ AASTP-1 Akıllı Mühimmat Denetim Sistemi
        **Teknoloji:** RAG (Evrensel Hafıza) + Fine-Tuned Llama-3 (Uzman Karar Mekanizması)
        """
    )
    
    with gr.Row():
        with gr.Column(scale=1):
            input_box = gr.Textbox(
                label="Denetim Senaryoları (Her satıra bir durum girin)", 
                lines=8, 
                placeholder="Örn: Found Group B stored with Group D...",
                value=TEST_SET_MATRIX 
            )
            
            gr.Markdown("### 🔽 Hazır Test Paketleri (Tıklayın)")
            gr.Examples(
                examples=[
                    [TEST_SET_MATRIX],
                    [TEST_SET_CHEMICAL],
                    [TEST_SET_COMPLEX]
                ],
                inputs=input_box,
                label="Test Senaryolarını Yükle"
            )
            
            audit_btn = gr.Button("🚀 DENETİMİ BAŞLAT (START AUDIT)", variant="primary", size="lg")
        
        with gr.Column(scale=2):
            output_html = gr.HTML(label="Denetim Raporu")

    audit_btn.click(fn=run_audit, inputs=input_box, outputs=output_html)

if __name__ == "__main__":
    print("🚀 Sistem Başlatılıyor: http://127.0.0.1:7860")
    demo.launch(share=True)