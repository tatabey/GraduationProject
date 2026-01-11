from unsloth import FastLanguageModel
import torch
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset
import os

# --- KLASÖR YOLLARI ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, "data", "training", "training_data_final.jsonl")
OUTPUT_DIR = os.path.join(BASE_DIR, "models", "checkpoints") # Ara kayıtlar
FINAL_MODEL_DIR = os.path.join(BASE_DIR, "models", "lora_model") # Final model

# --- AYARLAR ---
max_seq_length = 2048
dtype = None
load_in_4bit = True

def main():
    print(f"📂 Veri Seti Yolu: {DATA_FILE}")
    if not os.path.exists(DATA_FILE):
        print("❌ HATA: Eğitim verisi bulunamadı!")
        return

    # 1. Modeli Yükle
    print("🚀 Model Yükleniyor (Phi-3-mini)...")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name = "unsloth/Phi-3-mini-4k-instruct",
        max_seq_length = max_seq_length,
        dtype = dtype,
        load_in_4bit = load_in_4bit,
    )

    # 2. LoRA Adaptörlerini Ekle
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
        use_rslora = False,  
        loftq_config = None, 
    )

    # 3. Veri Setini Hazırla
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

    dataset = load_dataset("json", data_files=DATA_FILE, split="train")
    dataset = dataset.map(formatting_prompts_func, batched = True)
    
    print(f"📚 Toplam Eğitim Verisi: {len(dataset)} satır")

    # 4. Eğitimi Başlat
    # HESAPLAMA: 
    # 95 Veri / 8 (Batch Size) = ~12 adım (1 Epoch)
    # 60 Adım = ~5 Epoch (Veriyi 5 kez görecek, ezberlemeden öğrenmesi için ideal)
    
    trainer = SFTTrainer(
        model = model,
        tokenizer = tokenizer,
        train_dataset = dataset,
        dataset_text_field = "text",
        max_seq_length = max_seq_length,
        dataset_num_proc = 2,
        packing = False,
        args = TrainingArguments(
            per_device_train_batch_size = 2,
            gradient_accumulation_steps = 4,
            warmup_steps = 20,          # Artırıldı: Modelin ısınması için daha fazla zaman.
            max_steps = 150,            # Artırıldı: Daha yavaş ve sindirerek öğrenmesi için.
            learning_rate = 1e-4,       # Düşürüldü: 2e-4 yerine 1e-4 (Daha hassas ayar).
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
    print(f"💾 Model Kaydediliyor: {FINAL_MODEL_DIR}")
    model.save_pretrained(FINAL_MODEL_DIR)
    tokenizer.save_pretrained(FINAL_MODEL_DIR)
    print("✅ EĞİTİM TAMAMLANDI!")

if __name__ == "__main__":
    main()