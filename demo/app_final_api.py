import gradio as gr
import os
import re
import chromadb
from chromadb.utils import embedding_functions
from groq import Groq

# ==============================================================================
# 1. AYARLAR VE API KURULUMU
# ==============================================================================
# API Key'inizi buraya girin
GROQ_API_KEY = "***REMOVED***" 

# Model: Llama-3.3-70B (Çok güçlü ve Groq üzerinde şu an ücretsiz/hızlı)
API_MODEL = "llama-3.3-70b-versatile"

# Yol Ayarları
CURRENT_FILE_PATH = os.path.abspath(__file__)
DEMO_DIR = os.path.dirname(CURRENT_FILE_PATH)
BASE_DIR = os.path.dirname(DEMO_DIR)
DB_PATH = os.path.join(BASE_DIR, "data", "chroma_db")

# İstemciyi Başlat
client_groq = Groq(api_key=GROQ_API_KEY)

# ==============================================================================
# 2. VERİTABANI BAĞLANTISI (RAG HAFIZASI)
# ==============================================================================
if not os.path.exists(DB_PATH):
    raise FileNotFoundError(f"❌ Veritabanı yok: {DB_PATH}")

chroma_client = chromadb.PersistentClient(path=DB_PATH)
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = chroma_client.get_collection(name="aastp1_universal", embedding_function=emb_fn)

# ==============================================================================
# 3. YARDIMCI FONKSİYONLAR
# ==============================================================================

def retrieve_knowledge(scenario):
    """RAG: En alakalı 10 kuralı getir (API güçlü olduğu için context window geniş)."""
    results = collection.query(query_texts=[scenario], n_results=10)
    return results['documents'][0]

def parse_api_response(text):
    """API cevabını analiz et."""
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

def generate_html_card(index, scenario, verdict, reasoning, evidence):
    """HTML Rapor Kartı"""
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
    keywords = re.findall(r"(Note \d+|Table \w+|Set \d+|Group [A-Z])", reasoning, re.IGNORECASE)
    keywords = set([k.upper() for k in keywords])

    for i, doc in enumerate(evidence):
        is_relevant = False
        style = "margin-bottom: 6px; padding: 4px; border-radius: 4px; color: #a0aec0;"
        prefix = f"<span style='color: #666; font-size: 0.8em;'>[DOC {i+1}]</span> "
        
        for k in keywords:
            if k in doc.upper(): is_relevant = True; break
        
        if is_relevant:
            style = "margin-bottom: 6px; padding: 6px; border-radius: 4px; background-color: rgba(255, 255, 255, 0.1); color: #fff; border-left: 3px solid #63b3ed;"
            prefix = f"<span style='color: #63b3ed; font-weight: bold; font-size: 0.8em;'>[MATCHED]</span> "

        evidence_list_html += f"<li style='{style}'>{prefix}{doc}</li>"

    return f"""
    <div style="border: 1px solid {color}; border-left: 5px solid {color}; border-radius: 8px; margin-bottom: 20px; background-color: {bg}; font-family: sans-serif;">
        <div style="padding: 15px;">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <span style="font-weight: bold; font-size: 1.2em; color: {color};">{icon} CASE {index}: {verdict}</span>
            </div>
            <div style="margin-bottom: 10px;"><p style="margin:0; color:#aaa; font-size:0.9em;">SCENARIO</p><p style="margin:5px 0; color:#fff; font-style:italic;">"{scenario}"</p></div>
            <div style="margin-bottom: 10px;"><p style="margin:0; color:#aaa; font-size:0.9em;">AI REASONING</p><p style="margin:5px 0; color:#fff; font-weight:500;">{reasoning}</p></div>
            <details style="margin-top:15px; border-top:1px solid rgba(255,255,255,0.1); padding-top:10px;">
                <summary style="cursor:pointer; color:#aaa; font-size:0.9em;">🔍 <b>Evidence Analysis</b> (RAG Context)</summary>
                <ul style="font-size:0.85em; list-style-type:none; padding-left:0; margin-top:10px;">{evidence_list_html}</ul>
            </details>
        </div>
    </div>
    """

# ==============================================================================
# 4. ANA İŞLEM (API ÇAĞRISI)
# ==============================================================================

def run_audit(input_text):
    scenarios = [line.strip() for line in input_text.split('\n') if line.strip()]
    if not scenarios: return "Lütfen analiz edilecek senaryoları girin."
    
    full_html = ""
    
    for i, scenario in enumerate(scenarios):
        # 1. RAG ile Bilgi Getir
        evidence_docs = retrieve_knowledge(scenario)
        context_str = "\n".join([f"- {doc}" for doc in evidence_docs])
        
        # 2. Sistem Promptu (API için optimize edildi)
        system_prompt = """You are an expert Military Safety Auditor. Your task is to verify storage compliance based ONLY on the provided RULES.

CRITICAL INSTRUCTIONS:
1. **Analyze the Table Data:** - If the rule says 'Group A | B: X', it means Mixing Group A and B is COMPLIANT.
   - If the rule says 'Group A | B: X Note 1', it is CONDITIONAL (cite the note).
   - If the cell is empty or not listed, it is NON-COMPLIANT.
2. **Be Decisive:** Do not be vague. If you see an 'X', trust it.
3. **Format:** Start your response with "VERDICT: [COMPLIANT/NON-COMPLIANT/CONDITIONAL]". Then provide "REASONING: ...".
"""
        
        user_message = f"""
RULES CONTEXT:
{context_str}

SCENARIO TO AUDIT:
{scenario}
"""

        try:
            # 3. API İsteği (Groq - Llama 70B)
            completion = client_groq.chat.completions.create(
                model=API_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0, # Sıfır yaratıcılık, tam itaat
                max_tokens=256
            )
            
            response_text = completion.choices[0].message.content
            
            # 4. Sonuç İşleme
            verdict, reasoning = parse_api_response(response_text)
            full_html += generate_html_card(i+1, scenario, verdict, reasoning, evidence_docs)
            
        except Exception as e:
            full_html += f"<div style='color:red;'>API Error on Case {i+1}: {str(e)}</div>"

    return full_html

# ==============================================================================
# 5. ARAYÜZ
# ==============================================================================

TEST_SET_MATRIX = """Found 100kg of Group D stored with Group E without separation.
Found 50kg of Group B stored with 20kg of Group K.
Compatibility Group C articles are stored with Compatibility Group S articles.
Compatibility Group H articles are stored in the same magazine as Compatibility Group J articles."""

with gr.Blocks(theme=gr.themes.Soft(), css="body {background-color: #0f172a;} .gradio-container {background-color: #0f172a; color: white;} textarea {background-color: #1e293b !important; color: white !important;}") as demo:
    gr.Markdown("# 🛡️ AASTP-1 AI Auditor (Powered by Llama-3-70B API)")
    
    with gr.Row():
        with gr.Column(scale=1):
            input_box = gr.Textbox(label="Scenarios", lines=8, value=TEST_SET_MATRIX)
            btn = gr.Button("🚀 RUN AUDIT (API)", variant="primary")
        with gr.Column(scale=2):
            output_html = gr.HTML(label="Audit Report")

    btn.click(fn=run_audit, inputs=input_box, outputs=output_html)

if __name__ == "__main__":
    demo.launch(share=True)