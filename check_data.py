import json
import os

file_path = "data/training/training_data_final.jsonl"

if not os.path.exists(file_path):
    print("❌ Dosya bulunamadı!")
    exit()

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"🔍 Toplam Satır: {len(lines)}")
valid_count = 0
for i, line in enumerate(lines):
    try:
        data = json.loads(line)
        if "instruction" in data and "input" in data and "output" in data:
            valid_count += 1
        else:
            print(f"⚠️ Satır {i+1} eksik anahtar içeriyor.")
    except:
        print(f"❌ Satır {i+1} bozuk JSON formatında.")

print(f"✅ Geçerli Veri: {valid_count} / {len(lines)}")