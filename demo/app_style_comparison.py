import gradio as gr
from unsloth import FastLanguageModel
import torch
import os

# --- SETTINGS ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Define the path of the model being tested
MODEL_PATH = os.path.join(BASE_DIR, "models", "lora_model") 

# --- LOAD MODEL ---
print(f"🚀 Loading Model for Style Analysis: {MODEL_PATH}...")
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = MODEL_PATH,
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)
FastLanguageModel.for_inference(model)

def style_test(scenario):
    
    # 1. COMMON PROMPT (No Formatting Command)
    # We deliberately do NOT tell the model to use a specific format.
    # We want to see if the Fine-Tuned model applies the format naturally.
    prompt = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
Verify compliance with AASTP-1 Table 6 standards.

### Input:
{scenario}

### Response:
"""
    
    inputs = tokenizer([prompt], return_tensors="pt").to("cuda")

    # --- CASE A: BASE MODEL (Fine-Tuning DISABLED) ---
    # Temporarily disable LoRA adapters to see the "factory settings."
    with model.disable_adapter():
        outputs_base = model.generate(
            **inputs, 
            max_new_tokens=128,
            use_cache=True, 
            temperature=0.7 # Slightly more conversational
        )
        res_base = tokenizer.batch_decode(outputs_base)[0]
        if "### Response:\n" in res_base:
            clean_base = res_base.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
        else:
            clean_base = res_base

    # --- CASE B: FINE-TUNED MODEL (Fine-Tuning ENABLED) ---
    # LoRA adapters active. "Military identity" enabled.
    outputs_ft = model.generate(
        **inputs, 
        max_new_tokens=128,
        use_cache=True, 
        temperature=0.1 # More precise and consistent
    )
    res_ft = tokenizer.batch_decode(outputs_ft)[0]
    if "### Response:\n" in res_ft:
        clean_ft = res_ft.split("### Response:\n")[1].replace("<|endoftext|>", "").strip()
    else:
        clean_ft = res_ft

    return clean_base, clean_ft

# --- UI DESIGN ---
with gr.Blocks(theme=gr.themes.Base()) as demo:
    gr.Markdown(
        """
        # 🎭 Fine-Tuning Impact: Style and Format Test
        **Left Side (Base Model):** Untrained, raw state of the model.
        **Right Side (Fine-Tuned):** The model we trained.
        
        """
    )
    
    with gr.Row():
        input_text = gr.Textbox(
            label="Scenario", 
            placeholder="E.g.: Group F articles are stored with Group C...",
            lines=2
        )
    
    submit_btn = gr.Button("Show Style Difference", variant="primary")
    
    with gr.Row():
        # LEFT COLUMN
        with gr.Column():
            gr.Markdown("### 👶 Base Model (Untrained)")
            output_base = gr.Textbox(label="Output (Chat Style)", lines=6, interactive=False)
            gr.Markdown("*Expectation: Long sentences, conversational tone, vague format.*")
            
        # RIGHT COLUMN
        with gr.Column():
            gr.Markdown("### 👮 Fine-Tuned Model (Trained)")
            output_ft = gr.Textbox(label="Output (Military Format)", lines=6, interactive=False)
            gr.Markdown("*Expectation: 'COMPLIANCE / REASONING' format, concise and strict tone.*")

    # Example
    gr.Examples(
        examples=[
            ["Scenario: Compatibility Group F articles are stored in the same building as Compatibility Group C articles."]
        ],
        inputs=input_text
    )

    submit_btn.click(fn=style_test, inputs=input_text, outputs=[output_base, output_ft])

if __name__ == "__main__":
    demo.launch(share=True, server_port=7867)