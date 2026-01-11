from unsloth import FastLanguageModel
import torch
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset
import os

# --- KLASÖR YOLLARI ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Sizin ürettiğiniz scenario bazlı veri setini hedefliyoruz
DATA_FILE = os.path.join(BASE_DIR, "data", "training", "training_data_scenarios.jsonl")

# Çıktı Klasörleri
OUTPUT_DIR = os.path.join(BASE_DIR, "models", "llama", "checkpoints")
FINAL_MODEL_DIR = os.path.join(BASE_DIR, "models", "llama", "lora_model")

# --- MODEL AYARLARI ---
# Llama 3.2 3B: Hızlı, 4GB VRAM ile bile çalışır ve çok zekidir
MODEL_NAME = "unsloth/Llama-3.2-3B-Instruct"
MAX_SEQ_LENGTH = 2048
DTYPE = None 
LOAD_IN_4BIT = True 

def main():
    print(f"📂 Veri Yolu: {DATA_FILE}")
    
    if not os.path.exists(DATA_FILE):
        print("❌ HATA: Eğitim verisi bulunamadı!")
        return

    print(f"🚀 Model Yükleniyor: {MODEL_NAME}...")
    
    # 1. Modeli Yükle
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = MODEL_NAME,
        max_seq_length = MAX_SEQ_LENGTH,
        dtype = DTYPE,
        load_in_4bit = LOAD_IN_4BIT,
    )

    # 2. LoRA Adaptörleri
    model = FastLanguageModel.get_peft_model(
        model,
        r = 16,
        target_modules = ["q_proj", "k_proj", "v_proj", "o_proj",
                          "gate_proj", "up_proj", "down_proj",],
        lora_alpha = 16,
        lora_dropout = 0, 
        bias = "none",    
        use_gradient_checkpointing = "unsloth", 
        random_state = 3407,
    )

    # 3. Prompt Formatı (Alpaca)
    # Modele "Denetçi" rolünü hatırlatan prompt
    alpaca_prompt = """Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{}

### Input:
{}

### Response:
{}"""

    def formatting_prompts_func(examples):
        instructions = examples["instruction"]
        inputs       = examples["input"]
        outputs      = examples["output"]
        texts = []
        for instruction, input, output in zip(instructions, inputs, outputs):
            text = alpaca_prompt.format(instruction, input, output) + tokenizer.eos_token
            texts.append(text)
        return { "text" : texts, }

    # Veriyi Yükle
    dataset = load_dataset("json", data_files=DATA_FILE, split="train")
    dataset = dataset.map(formatting_prompts_func, batched = True)
    
    print(f"📚 Eğitim Verisi: {len(dataset)} satır.")

    # 4. Eğitim Parametreleri
    trainer = SFTTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = dataset,
        dataset_text_field = "text",
        max_seq_length = MAX_SEQ_LENGTH,
        dataset_num_proc = 2,
        packing = False,
        args = TrainingArguments(
            per_device_train_batch_size = 2,
            gradient_accumulation_steps = 4,
            warmup_steps = 10,
            # 210 veri için 1 epoch ~26 adım. 
            # 3-4 Epoch (yaklaşık 80-100 adım) idealdir.
            max_steps = 100, 
            learning_rate = 2e-4, 
            fp16 = not torch.cuda.is_bf16_supported(),
            bf16 = torch.cuda.is_bf16_supported(),
            logging_steps = 1,
            optim = "adamw_8bit",
            weight_decay = 0.01,
            lr_scheduler_type = "linear",
            seed = 3407,
            output_dir = OUTPUT_DIR,
        ),
    )

    print("🔥 Eğitim Başlıyor...")
    trainer_stats = trainer.train()

    # 5. Kaydet
    os.makedirs(FINAL_MODEL_DIR, exist_ok=True)
    print(f"💾 Model Kaydediliyor: {FINAL_MODEL_DIR}")
    model.save_pretrained(FINAL_MODEL_DIR)
    tokenizer.save_pretrained(FINAL_MODEL_DIR)
    
    # GGUF (Opsiyonel - Yerel kullanım için)
    # model.save_pretrained_gguf(FINAL_MODEL_DIR, tokenizer, quantization_method = "q4_k_m")
    
    print("✅ EĞİTİM BAŞARIYLA TAMAMLANDI!")

if __name__ == "__main__":
    main()