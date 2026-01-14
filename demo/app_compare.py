# app_compare.py (Single Comparison - Simple Demo)
# User enters a single scenario. The system analyzes it using both "Pure Model" (No-RAG) and "Hybrid Model" (RAG) and displays them side-by-side.
# This version does NOT include advanced prompt engineering like Critical Rules (Blank cell rule). It performs a raw comparison.
# ADVANCED VERSION: app_phi3_multi_compare.py (Multi-Comparison - Advanced Demo)

import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- SETTINGS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "lora_model")
CONTEXT_FILE = os.path.join(BASE_DIR, "data", "context", "Table6_Context.txt")

# --- LOAD CONTEXT ---
if os.path.exists(CONTEXT_FILE):
    with open(CONTEXT_FILE, "r", encoding="utf-8") as f:
        RULES_CONTEXT = f.read()
else:
    RULES_CONTEXT = "Error: Context file not found."

# --- LOAD MODEL (ONCE) ---
# Loading the model once, we will query it using two different methods.
print(f"🚀 Loading Model: {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

# --- MAIN FUNCTION ---
def compare_models(scenario):
    
    # METHOD 1: PURE MEMORY (NO RAG)
    # Rules are not provided to the model. We only ask what it remembers from training.
    prompt_no_rag = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Verify compliance with AASTP-1 Table 6 standards.

### Input:
{scenario}

### Response:
"""
    
    # METHOD 2: CONTEXT INJECTION (WITH RAG)
    # Rules (Context) are provided to the model.
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

    # --- MODEL EXECUTION (NO RAG) ---
    inputs_1 = tokenizer([prompt_no_rag], return_tensors="pt").to("cuda")
    outputs_1 = model.generate(**inputs_1, max_new_tokens=128, use_cache=True, temperature=0.1)
    response_1 = tokenizer.batch_decode(outputs_1)[0].split("### Response:\n")[1].replace("<|endoftext|>", "").strip()

    # --- MODEL EXECUTION (WITH RAG) ---
    inputs_2 = tokenizer([prompt_rag], return_tensors="pt").to("cuda")
    outputs_2 = model.generate(**inputs_2, max_new_tokens=256, use_cache=True, temperature=0.1)
    response_2 = tokenizer.batch_decode(outputs_2)[0].split("### Response:\n")[1].replace("<|endoftext|>", "").strip()

    return response_1, response_2

# --- UI DESIGN ---
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
        # ⚔️ AI Model Comparison: Fine-Tuning vs. Hybrid (FT + RAG)
        **Left side:** Model uses its memory only. **Right side:** Model reads the document to provide an answer.
        """
    )
    
    with gr.Row():
        input_text = gr.Textbox(
            label="Military Storage Scenario", 
            placeholder="E.g.: Compatibility Group F articles are stored in the same building as Compatibility Group C articles...",
            lines=2
        )
    
    submit_btn = gr.Button("Start Analysis (Compare)", variant="primary")
    
    with gr.Row():
        # LEFT COLUMN
        with gr.Column():
            gr.Markdown("### 🧠 Pure Model (Fine-Tune)")
            output_no_rag = gr.Textbox(label="Result (No Context)", lines=10, interactive=False)
            gr.Markdown("*Risk: May hallucinate or confuse specific rules.*")
            
        # RIGHT COLUMN
        with gr.Column():
            gr.Markdown("### 🛡️ Hybrid Model (RAG + Fine-Tune)")
            output_rag = gr.Textbox(label="Result (Context Aware)", lines=10, interactive=False)
            gr.Markdown("*Advantage: Precise as it reads the rules directly from the text.*")

    # Examples
    gr.Examples(
        examples=[
            ["Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles."], # Note 2 (Hard)
            ["Scenario: Mixing of articles of Compatibility Group G with articles of Compatibility Group C."], # Note 4 (Hard)
            ["Scenario: Compatibility Group L articles are stored in the same storage area as Compatibility Group K articles."], # Forbidden (Easy)
            ["Scenario: Group N articles are stored with Group S."] # Note 7 (Complex)
        ],
        inputs=input_text
    )

    submit_btn.click(fn=compare_models, inputs=input_text, outputs=[output_no_rag, output_rag])

if __name__ == "__main__":
    demo.launch(share=True)