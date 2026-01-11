import os
import time
import json
import re
from groq import Groq

# --- AYARLAR ---
GROQ_API_KEY = "***REMOVED***"
# Llama 3.3: Hem senaryo kurgulama hem de mantık yürütmede çok iyidir
MODEL_ID = "llama-3.3-70b-versatile"

client = Groq(api_key=GROQ_API_KEY)

# --- YOLLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "data", "cleaned", "Cleaned_Merged.md")
if not os.path.exists(INPUT_FILE):
    INPUT_FILE = os.path.join(BASE_DIR, "data", "intermediate", "Merged.md")
    
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "training", "training_data_scenarios.jsonl")

# --- HEDEF HACİM ---
# Her bir parça (tablo/metin) için kaç tur veri üretilsin?
# 8 parça x 5 tur x 3 senaryo = ~120 veri (Siz bu sayıyı artırabilirsiniz)
GENERATION_ROUNDS_PER_CHUNK = 10 

def generate_scenarios_from_chunk(chunk_text, chunk_type):
    """
    Metin parçasına göre 'Test Sonucu/Senaryo' ve 'Denetim Raporu' üretir.
    """
    
    # Prompt stratejisini chunk tipine göre özelleştirelim
    if chunk_type == "table":
        focus_msg = "Create realistic storage scenarios where different items are mixed or specific safety gears are used/missing."
    else:
        focus_msg = "Create scenarios involving specific rules, prohibitions (e.g. suspect ammo), or exceptions mentioned in the text."

    system_prompt = f"""You are an expert Military Ammunition Safety Auditor creating a training dataset.
    Your goal is to generate realistic "Field Scenarios" (Input) and their corresponding "Compliance Evaluation" (Output) based on the provided AASTP-1 rules.
    
    {focus_msg}
    
    FORMAT RULES:
    1. Output MUST be a valid JSON List.
    2. 'input': Describe a realistic situation, inspection finding, or storage setup (e.g., "Found 100kg of Group B stored with Group K...").
    3. 'output': Must start with "VERDICT: [COMPLIANT / NON-COMPLIANT / CONDITIONAL]". Then provide "REASONING:" referencing the specific Table, Note, or Rule.
    4. Generate 3 distinct pairs.
    
    JSON STRUCTURE:
    [
      {{
        "instruction": "Evaluate compliance with AASTP-1 standards.",
        "input": "Scenario description...",
        "output": "VERDICT: ... REASONING: ..."
      }}
    ]
    """

    try:
        completion = client.chat.completions.create(
            model=MODEL_ID,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"RULES CONTEXT:\n{chunk_text}\n\nGenerate 3 scenarios now:"}
            ],
            temperature=0.6, # Yaratıcılık için biraz artırdık (Farklı senaryolar türetsin)
            max_tokens=2048,
            top_p=1,
            stream=False,
            response_format={"type": "json_object"}
        )

        content = completion.choices[0].message.content
        data = json.loads(content)
        
        # Groq dönüş formatını normalize et
        if isinstance(data, dict):
            # Liste içeren bir key varsa onu al, yoksa kendisini listeye sar
            values = list(data.values())
            if values and isinstance(values[0], list):
                return values[0]
            return [data]
        elif isinstance(data, list):
            return data
        return []

    except Exception as e:
        print(f"   ⚠️ Hata: {e}")
        time.sleep(1)
        return []

def split_content_smartly(text):
    chunks = []
    # Tabloları bütün al
    tables = re.findall(r"(<table>.*?</table>)", text, re.DOTALL)
    for t in tables:
        chunks.append({"type": "table", "content": t})
        
    # Metinleri paragraflara böl
    text_only = re.sub(r"<table>.*?</table>", "", text, flags=re.DOTALL)
    paragraphs = re.split(r'\n\s*\n', text_only)
    for p in paragraphs:
        if len(p.strip()) > 150 and "NATO" not in p: # Sadece dolu paragraflar
            chunks.append({"type": "text", "content": p.strip()})
    return chunks

def main():
    if not os.path.exists(INPUT_FILE):
        print("❌ Dosya yok.")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        full_text = f.read()

    chunks = split_content_smartly(full_text)
    print(f"🚀 Senaryo Üretimi Başlıyor ({len(chunks)} Kaynak Parça)...")
    print(f"🎯 Hedef: Her parça için {GENERATION_ROUNDS_PER_CHUNK} tur üretim.")
    
    total_count = 0
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    # Dosyayı sıfırdan aç
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f_out:
        
        # Her bir parça için döngü
        for i, chunk in enumerate(chunks):
            print(f"\n📦 Kaynak [{i+1}/{len(chunks)}] ({chunk['type']}) İşleniyor...")
            
            # Hacim artırma döngüsü
            for round_num in range(GENERATION_ROUNDS_PER_CHUNK):
                print(f"   ↳ Tur {round_num+1}/{GENERATION_ROUNDS_PER_CHUNK} üretiliyor...", end="\r")
                
                scenarios = generate_scenarios_from_chunk(chunk['content'], chunk['type'])
                
                if scenarios:
                    for item in scenarios:
                        # Kalite kontrol: Input/Output dolu mu?
                        if "input" in item and "output" in item:
                            json.dump(item, f_out)
                            f_out.write("\n")
                            total_count += 1
                    f_out.flush()
                
                # API nezaketi
                time.sleep(1.5)

    print(f"\n\n✅ TAMAMLANDI!")
    print(f"📊 Toplam Üretilen Senaryo: {total_count}")
    print(f"💾 Kayıt Yeri: {OUTPUT_FILE}")

if __name__ == "__main__":
    main()