import os

# --- YOLLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "data", "intermediate", "Merged.md")
OUTPUT_FILE = os.path.join(BASE_DIR, "data", "cleaned", "Cleaned_Merged.md")

def clean_text_manually():
    print(f"📂 Okunuyor: {INPUT_FILE}")
    
    if not os.path.exists(INPUT_FILE):
        print(f"❌ HATA: Dosya bulunamadı! ({INPUT_FILE})")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    print(f"📊 Orijinal Satır Sayısı: {len(content.splitlines())}")

    # --- TEMİZLİK KURALLARI ---
    # Bu kelimeleri içeren satırlar tamamen silinecek
    NOISE_KEYWORDS = [
        "NATO/PFP UNCLASSIFIED",
        "Downloaded from http",
        "Page ",             # Sayfa numaraları genelde 'Page 1', '--- PAGE 2 ---' gibi geçer
        "CHANGE 2",          # Belge versiyon notları
        "AASTP-1",           # Her sayfada tekrar eden başlık
        "(Edition 1)"
    ]

    lines = content.split('\n')
    cleaned_lines = []
    removed_count = 0

    for line in lines:
        # Satırda gürültü kelimelerinden biri var mı?
        is_noise = False
        for keyword in NOISE_KEYWORDS:
            if keyword in line:
                is_noise = True
                break
        
        # Gürültü değilse ve satır tamamen boş değilse ekle
        # (Tablo satırlarını korumak için çok dikkatli filtreleme yapıyoruz)
        if not is_noise:
            cleaned_lines.append(line)
        else:
            removed_count += 1

    final_content = "\n".join(cleaned_lines)
    
    # Klasör yoksa oluştur
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(final_content)

    print(f"✅ İŞLEM TAMAMLANDI!")
    print(f"🗑️ Silinen Gürültü Satır Sayısı: {removed_count}")
    print(f"💾 Temiz Dosya Kaydedildi: {OUTPUT_FILE}")

if __name__ == "__main__":
    clean_text_manually()