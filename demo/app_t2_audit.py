import gradio as gr
from unsloth import FastLanguageModel
import torch
import os
import re
import chromadb
from chromadb.utils import embedding_functions

# --- AYARLAR (DÜZELTİLDİ) ---
# 1. Bu dosyanın nerede olduğunu bul (.../GraduationProject/demo/app_t2_audit.py)
CURRENT_FILE_PATH = os.path.abspath(__file__)
# 2. Bulunduğu klasörü al (.../GraduationProject/demo)
CURRENT_DIR = os.path.dirname(CURRENT_FILE_PATH)
# 3. PROJE ANA DİZİNİNE ÇIK (.../GraduationProject)
# "demo" veya "scripts" klasöründe olmanız fark etmez, bir üst dizine çıkar.
BASE_DIR = os.path.dirname(CURRENT_DIR)

print(f"📂 Çalışma Dizini (Base Dir): {BASE_DIR}")

MODEL_PATH = os.path.join(BASE_DIR, "models", "llama", "lora_model") 
DB_PATH = os.path.join(BASE_DIR, "data", "chroma_db")

# --- MODELİ YÜKLE ---
print(f"🚀 Model Yükleniyor: {MODEL_PATH}")
if not os.path.exists(MODEL_PATH):
    # Yedek plan: Eğer lokalde yoksa indir (Ama doğru path ayarıyla lokalde bulması lazım)
    print(f"⚠️ DİKKAT: '{MODEL_PATH}' yolunda model bulunamadı. HuggingFace'den indiriliyor...")
    MODEL_PATH = "unsloth/Llama-3.2-3B-Instruct"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048, 
    dtype = None,
    load_in_4bit = True,
    gpu_memory_utilization = 0.60,
)
FastLanguageModel.for_inference(model)

# --- VERİTABANI BAĞLANTISI ---
if not os.path.exists(DB_PATH):
    raise FileNotFoundError(f"❌ Veritabanı bulunamadı: {DB_PATH}\n Lütfen 'data' klasörünün proje ana dizininde olduğundan emin olun.")

client = chromadb.PersistentClient(path=DB_PATH)
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = client.get_collection(name="aastp1_table_t1", embedding_function=emb_fn)

def retrieve_context(query):
    results = collection.query(query_texts=[query], n_results=3)
    return results['documents'][0]

def parse_model_response(raw_output):
    """Model çıktısından sadece ANSWER kısmını çeker."""
    clean = raw_output.replace("**", "").replace("###", "").strip()
    answer_match = re.search(r"ANSWER:\s*(.+)", clean, re.DOTALL | re.IGNORECASE)
    if answer_match:
        return answer_match.group(1).strip()
    else:
        return clean

def analyze_chemical(scenario):
    chunks = retrieve_context(scenario)
    context_text = "\n".join(chunks)
    top_evidence = chunks[0] if chunks else "No relevant data found in DB."

    sys_prompt = "You are a specialized Chemical Safety Assistant. Answer the user's question accurately using the provided context."
    user_prompt = f"""
### CONTEXT (OFFICIAL SAFETY RULES) ###
{context_text}

### INSTRUCTION ###
Act as a strict Safety Officer. Your task is to answer the user's question using ONLY the provided CONTEXT.

RULES FOR ANSWERING:
1. **Be Exact:** If the context says "Group G", you MUST say "Group G". Do NOT hallucinate.
2. **Be Complete:** Do not answer with single letters like "N" or "Y". Write full sentences.
3. **Handle Missing Info:** If the context really doesn't have the answer, say "Information not available in records". Do not say "N/A" if the text is right there!
4. **Verify:** Double-check the Context before writing the Answer.

FORMAT:
ANSWER: [Write a complete, clear sentence answering the question based on the context.]

### USER QUESTION ###
{scenario}
"""
    messages = [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}]
    inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to("cuda")
    
    outputs = model.generate(input_ids=inputs, max_new_tokens=256, use_cache=True, temperature=0.1)
    response = tokenizer.decode(outputs[0][len(inputs[0]):], skip_special_tokens=True)
    
    return response, top_evidence

def format_qa_entry(scenario_num, question, answer, evidence):
    icon = "🤖"
    border_color = "#4a5568"
    
    if "NO WATER" in answer.upper() or "PROHIBITED" in answer.upper():
        icon = "⛔"
        border_color = "#e53e3e"
    elif "PERMITTED" in answer.upper() or "SAFE" in answer.upper():
        icon = "✅"
        border_color = "#48bb78"

    return f"""
<div style="margin-bottom: 20px; padding: 10px 15px; border-left: 5px solid {border_color};">
    <div style="font-size: 1.1em; font-weight: bold; margin-bottom: 8px; color: #a0aec0;">
        Case {scenario_num}: {question}
    </div>
    <div style="font-size: 1.2em; color: #e2e8f0; margin-bottom: 15px; line-height: 1.5;">
        {icon} <b>Answer:</b> {answer}
    </div>
    <div style="font-size: 0.85em; color: #718096; border-top: 1px solid #4a5568; padding-top: 8px;">
        🔍 <b>Retrieved Evidence:</b> <i>"{evidence}"</i>
    </div>
</div>
"""

def batch_process(text):
    queries = [line.strip() for line in text.split('\n') if line.strip()]
    full_report = "<h3>🛡️ Chemical Safety Q&A Audit</h3>"
    
    for i, q in enumerate(queries):
        print(f"Processing ({i+1}/{len(queries)}): {q[:30]}...")
        raw_res, top_evidence = analyze_chemical(q)
        answer = parse_model_response(raw_res)
        full_report += format_qa_entry(i+1, q, answer, top_evidence)
        
    return full_report

test_queries = """
What are the safety rules for Napalm (NP)?
Check requirements for White Phosphorous (WP).
Is it safe to use water on Calcium Phosphide?
What protective clothing is needed for Tear Gas?
Provide storage group for Thermite or Thermate (TH).
Requirements for Smoke, Aluminum-zinc oxide-hexachloroethane (HC).
Safety details for Isobutyl methacrylate with oil (IM).
Can I use water on Pyrotechnic Material (PT)?
What is the compatibility group for Toxic Agents?
Safety gear for Triethylaluminim (TEA).
""".strip()

with gr.Blocks(theme=gr.themes.Base()) as demo:
    with gr.Row():
        inp = gr.Textbox(lines=10, value=test_queries, label="Enter Your Questions")
        btn = gr.Button("ASK EXPERT", variant="primary")
    with gr.Row():
        out_html = gr.HTML(label="Results")
    
    btn.click(fn=batch_process, inputs=inp, outputs=[out_html])

if __name__ == "__main__":
    demo.launch(share=True, server_port=7897)