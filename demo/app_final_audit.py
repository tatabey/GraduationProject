import gradio as gr
from unsloth import FastLanguageModel
import torch
import os
import re
import chromadb
from chromadb.utils import embedding_functions

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "llama", "lora_model") 
DB_PATH = os.path.join(BASE_DIR, "data", "chroma_db")

# --- MODELİ YÜKLE ---
print(f"🚀 Model Yükleniyor: {MODEL_PATH}...")
if not os.path.exists(MODEL_PATH):
    print("⚠️ Yerel model bulunamadı, HuggingFace'den çekiliyor...")
    MODEL_PATH = "unsloth/Llama-3.2-3B-Instruct"

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048, 
    dtype = None,
    load_in_4bit = True,
    gpu_memory_utilization = 0.60,
)
FastLanguageModel.for_inference(model)

# --- DB BAĞLANTISI ---
client = chromadb.PersistentClient(path=DB_PATH)
emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = client.get_collection(name="aastp1_rules", embedding_function=emb_fn)

def extract_groups(text):
    return list(set(re.findall(r"\bGroup\s+([A-S])\b", text, re.IGNORECASE)))

def retrieve_and_filter_context(scenario):
    results = collection.query(query_texts=[scenario], n_results=20)
    raw_chunks = results['documents'][0]
    target_groups = extract_groups(scenario)
    
    filtered_chunks = []
    notes_chunk = ""

    for chunk in raw_chunks:
        if "REFERENCE NOTES" in chunk:
            notes_chunk = chunk
            continue
            
        if len(target_groups) >= 2:
            g1, g2 = target_groups[0], target_groups[1]
            if f"Group {g1}" in chunk and f"Group {g2}" in chunk:
                filtered_chunks.append(chunk)
        else:
            filtered_chunks.append(chunk)
    
    if not filtered_chunks and len(target_groups) >= 2:
        filtered_chunks.append(f"System Alert: No specific rule found for mixing Group {target_groups[0]} and Group {target_groups[1]}. Therefore it is STRICTLY PROHIBITED (Empty Cell).")

    if notes_chunk:
        filtered_chunks.append(notes_chunk)
        
    return filtered_chunks

def parse_model_output(raw_output):
    clean_text = raw_output.replace("###", "").replace("**", "").replace("##", "").strip()
    
    decision_match = re.search(r"(DECISION|STATUS)[:\s\-\.]+(TRUE|FALSE)", clean_text, re.IGNORECASE)
    if decision_match:
        decision = decision_match.group(2).upper()
    else:
        if "STRICTLY PROHIBITED" in clean_text.upper(): decision = "FALSE"
        elif "PERMITTED" in clean_text.upper(): decision = "TRUE"
        else: decision = "UNCERTAIN"

    code_match = re.search(r"(CODE|STATUS CODE)[:\s\-\.]+(X[0-9]*|[0-9]+|EMPTY)", clean_text, re.IGNORECASE)
    code = code_match.group(2).strip() if code_match else "EMPTY"

    reasoning_match = re.split(r"(REASONING|LOGIC|EXPLANATION)[:\s\-\.]+", clean_text, flags=re.IGNORECASE)
    reasoning = reasoning_match[-1].strip() if len(reasoning_match) > 1 else clean_text

    return decision, code, reasoning

def analyze_with_rag(scenario):
    chunks = retrieve_and_filter_context(scenario)
    context_text = "\n".join(chunks)
    
    debug_view = ""
    for idx, c in enumerate(chunks):
        debug_view += f"🔹 {c}\n"

    system_prompt = "You are a Military Validation Engine. Verify compatibility rules strictly."
    
    # --- GÜNCELLENEN KISIM ---
    user_prompt = f"""
OFFICIAL RULES:
{context_text}

INSTRUCTION:
Determine if the storage scenario is permitted based ONLY on the rules above.

FORMAT:
DECISION: [TRUE or FALSE]
CODE: [X, X1, 2, 4, or EMPTY]
REASONING: [If a Code like X1, 2, 4 is found, do NOT just say "Permitted". You MUST summarize the condition described in the Note text (e.g., "Permitted only if fuses are aggregated...").]

LOGIC:
- If Rule says "STRICTLY PROHIBITED" or "No specific rule found" -> DECISION: FALSE
- If Rule says "PERMITTED" -> DECISION: TRUE

SCENARIO:
{scenario}
"""
    # -------------------------

    messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, return_tensors="pt").to("cuda")
    
    outputs = model.generate(input_ids=inputs, max_new_tokens=256, use_cache=True, temperature=0.1)
    response = tokenizer.decode(outputs[0][len(inputs[0]):], skip_special_tokens=True)

    return response, debug_view

def format_report_entry(scenario_num, scenario, decision, code, reasoning):
    if decision == "TRUE":
        icon = "✅"
        color = "green"
        text = "PERMITTED"
    elif decision == "FALSE":
        icon = "⛔"
        color = "red"
        text = "PROHIBITED"
    else:
        icon = "⚠️"
        color = "orange"
        text = "UNCERTAIN"

    return f"""
### {icon} Case {scenario_num}: <span style="color:{color}">{text}</span>
> **Scenario:** *{scenario}*

| **Decision** | **Code** | **Reasoning** |
| :--- | :--- | :--- |
| **{decision}** | `{code}` | {reasoning} |

---
"""

def batch_process(multi_input):
    scenarios = [line.strip() for line in multi_input.split('\n') if line.strip()]
    if not scenarios: return "No scenarios.", ""

    full_report = "# 🛡️ AASTP-1 PROFESSIONAL AUDIT REPORT\n---\n"
    full_debug = "## 🔍 DEBUG LOGS (Filtered Context)\n"
    
    for i, scenario in enumerate(scenarios):
        print(f"⏳ Processing ({i+1}/{len(scenarios)})...")
        raw_response, debug_info = analyze_with_rag(scenario)
        decision, code, reasoning = parse_model_output(raw_response)
        
        full_report += format_report_entry(i+1, scenario, decision, code, reasoning)
        full_debug += f"**Scenario {i+1}:** {scenario}\n```text\n{debug_info}\n```\n---\n"
    
    return full_report, full_debug

test_scenarios = """
Scenario: Compatibility Group H articles are stored in the same magazine as Compatibility Group J articles.
Scenario: A depot stores Compatibility Group K articles alongside Compatibility Group B fuses.
Scenario: Mixing of Compatibility Group L articles with Compatibility Group F articles.
Scenario: Compatibility Group G articles are stored with Compatibility Group H articles.
Scenario: Compatibility Group C articles are stored with Compatibility Group S articles.
Scenario: Compatibility Group D articles are stored with Compatibility Group C articles.
Scenario: Compatibility Group E articles are stored with Compatibility Group D articles.
Scenario: Compatibility Group S articles are stored with Compatibility Group F articles.
Scenario: Compatibility Group B fuses are stored with Compatibility Group D articles.
Scenario: Compatibility Group B fuses are stored with Compatibility Group E articles.
Scenario: Compatibility Group N articles are stored with Compatibility Group S articles.
Scenario: Compatibility Group N articles are stored with Compatibility Group C articles.
Scenario: Compatibility Group C articles are stored with Compatibility Group G articles.
Scenario: Compatibility Group F articles are stored with Compatibility Group C articles.
Scenario: Compatibility Group L articles are stored with Compatibility Group B articles.
Scenario: Compatibility Group S articles are stored with Compatibility Group C articles.
Scenario: Compatibility Group D articles are stored with Compatibility Group E articles.
Scenario: Compatibility Group F articles are stored with Compatibility Group S articles.
Scenario: Compatibility Group H articles are stored with Compatibility Group B articles.
Scenario: Compatibility Group J articles are stored with Compatibility Group D articles.
Scenario: Compatibility Group K articles are stored with Compatibility Group F articles.
Scenario: Compatibility Group L articles are stored with Compatibility Group C articles.
Scenario: Compatibility Group B articles are stored with Compatibility Group G articles.
Scenario: Compatibility Group C articles are stored with Compatibility Group H articles.
Scenario: Compatibility Group D articles are stored with Compatibility Group J articles.
Scenario: Compatibility Group E articles are stored with Compatibility Group K articles.
Scenario: Compatibility Group F articles are stored with Compatibility Group L articles.
Scenario: Compatibility Group G articles are stored with Compatibility Group N articles.
Scenario: Compatibility Group D articles are stored with Compatibility Group B articles.
Scenario: Compatibility Group E articles are stored with Compatibility Group B articles.
Scenario: Compatibility Group F articles are stored with Compatibility Group B articles.
Scenario: Compatibility Group C articles are stored with Compatibility Group F articles.
Scenario: Compatibility Group D articles are stored with Compatibility Group F articles.
Scenario: Compatibility Group E articles are stored with Compatibility Group F articles.
Scenario: Compatibility Group D articles are stored with Compatibility Group G articles.
Scenario: Compatibility Group E articles are stored with Compatibility Group G articles.
Scenario: Compatibility Group F articles are stored with Compatibility Group G articles.
Scenario: Compatibility Group C articles are stored with Compatibility Group N articles.
Scenario: Compatibility Group E articles are stored with Compatibility Group N articles.
Scenario: Compatibility Group S articles are stored with Compatibility Group N articles.
""".strip()

with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🛡️ AASTP-1 Audit System (Filtered)")
    with gr.Row():
        inp = gr.Textbox(lines=15, value=test_scenarios, label="Input Scenarios")
        btn = gr.Button("START AUDIT", variant="primary")
    with gr.Row():
        out_report = gr.Markdown(label="Final Report")
        out_debug = gr.Markdown(label="System Logs")
    btn.click(fn=batch_process, inputs=inp, outputs=[out_report, out_debug])

if __name__ == "__main__":
    demo.launch(share=True, server_port=7893)