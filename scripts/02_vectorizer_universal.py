"""
AASTP-1 Hücre Bazlı Vektörizasyon Script'i
==========================================
Her tablo hücresini ayrı döküman olarak kaydeder.
Semantic search için optimize edilmiş format.
"""

import os
import re
import pandas as pd
from io import StringIO
import chromadb
from chromadb.utils import embedding_functions
from bs4 import BeautifulSoup

# --- AYARLAR ---
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "data", "cleaned", "Cleaned_Merged.md")
if not os.path.exists(INPUT_FILE):
    INPUT_FILE = os.path.join(BASE_DIR, "data", "intermediate", "Merged.md")
# Fallback: aynı dizindeki dosya
if not os.path.exists(INPUT_FILE):
    INPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Cleaned_Merged.md")

DB_PATH = os.path.join(BASE_DIR, "data", "chroma_db")

# Compatibility grupları
COMPATIBILITY_GROUPS = ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'N', 'S']

# Notes sözlüğü (dosyadan çıkarılacak)
NOTES = {}


def clean_cell_value(value):
    """
    Hücre değerini temizler: LaTeX notasyonunu kaldırır
    \( X^{1)} \) -> X Note 1
    """
    if pd.isna(value) or str(value).strip() == '' or str(value).strip().lower() == 'nan':
        return ''

    val = str(value).strip()
    # LaTeX temizleme
    val = val.replace('\\(', '').replace('\\)', '').replace('$', '')
    val = re.sub(r'\^{?(\d+)\)?}?', r' Note \1', val)
    val = re.sub(r'\s+', ' ', val).strip()
    return val


def extract_notes_from_content(content):
    """
    Dosyadan notları çıkarır ve NOTES sözlüğüne kaydeder
    """
    notes = {}

    # Note 1-7 pattern'leri
    note_patterns = [
        (r'(\d+)\)\s*([^0-9\n][^\n]+?)(?=\d+\)|#|$)', re.MULTILINE),
    ]

    # # NOTES bölümünü bul
    notes_section = re.search(r'# NOTES\s*\n(.+?)(?=#|$)', content, re.DOTALL)
    if notes_section:
        notes_text = notes_section.group(1)

        # Her notu çıkar
        matches = re.findall(r'(\d+)\)\s*(.+?)(?=\d+\)|$)', notes_text, re.DOTALL)
        for num, text in matches:
            clean_text = ' '.join(text.strip().split())
            if len(clean_text) > 10:  # Çok kısa notları atla
                notes[num] = clean_text

    # Table T.1 notları (# Notes: bölümü)
    t1_notes = re.search(r'# Notes:\s*\n(.+?)(?=\n\n|Articles may)', content, re.DOTALL)
    if t1_notes:
        t1_text = t1_notes.group(1)
        matches = re.findall(r'(\d+)\s+(.+?)(?=\d+\s+|$)', t1_text, re.DOTALL)
        for num, text in matches:
            key = f"T1_{num}"
            notes[key] = ' '.join(text.strip().split())

    return notes



def process_compatibility_matrix(content):
    """
    Table 6 (Compatibility Matrix) işleme - DÜZELTİLMİŞ (Note Referans Hatası Giderildi)
    """
    documents = []
    ids = []
    metadatas = []

    # Table 6'yı bul
    table6_match = re.search(r'Table 6.*?(<table>.*?</table>)', content, re.DOTALL | re.IGNORECASE)
    if not table6_match:
        print("⚠️ Table 6 bulunamadı!")
        return documents, ids, metadatas

    html_table = table6_match.group(1)
    processed_pairs = set()

    try:
        dfs = pd.read_html(StringIO(html_table), header=0)
        df = dfs[0]
        col_groups = list(df.columns)[1:] 

        for _, row in df.iterrows():
            row_group = str(row.iloc[0]).strip()
            if row_group not in COMPATIBILITY_GROUPS: continue

            for col_idx, col_group in enumerate(col_groups):
                col_group_clean = str(col_group).strip()
                if col_group_clean not in COMPATIBILITY_GROUPS: continue

                pair_key = tuple(sorted([row_group, col_group_clean]))
                if pair_key in processed_pairs: continue
                processed_pairs.add(pair_key)

                raw_value = row.iloc[col_idx + 1]
                cell_value = clean_cell_value(raw_value)
                
                # --- METİN OLUŞTURMA ---
                doc_text = ""
                status = "UNKNOWN"
                note_content = "" # Not içeriğini tutacak değişken

                # 1. Hücrede "Note X" yazıyor mu? (Örn: X Note 1)
                if "Note" in cell_value:
                    note_match = re.search(r'Note\s*(\d+)', cell_value)
                    if note_match:
                        note_num = note_match.group(1)
                        note_text = NOTES.get(note_num, "See AASTP-1 notes.")
                        note_content = f" Subject to Condition (Note {note_num}): {note_text}"

                # 2. Hücre sadece sayı mı? (Örn: 2) veya 4))
                # Regex: Sadece rakam veya rakam+parantez
                elif re.match(r'^(\d+)\)?$', cell_value):
                    num_match = re.match(r'^(\d+)\)?$', cell_value)
                    note_num = num_match.group(1)
                    note_text = NOTES.get(note_num, "See AASTP-1 notes.")
                    note_content = f" Subject to Condition (Note {note_num}): {note_text}"

                # --- DURUM ANALİZİ ---
                if cell_value == '' or str(raw_value).lower() == 'nan':
                    status = "PROHIBITED"
                    doc_text = (
                        f"Compatibility Rule: Group {row_group} and Group {col_group_clean} CANNOT be mixed. "
                        f"Mixing is PROHIBITED (Empty Cell)."
                    )
                elif 'X' in cell_value:
                    if note_content: # X Note 1 durumu
                        status = "CONDITIONAL"
                        doc_text = (
                            f"Compatibility Rule: Group {row_group} and Group {col_group_clean} mixing is CONDITIONAL. "
                            f"Allowed with restrictions.{note_content}"
                        )
                    else: # Sadece X
                        status = "PERMITTED"
                        doc_text = (
                            f"Compatibility Rule: Group {row_group} and Group {col_group_clean} are COMPATIBLE. "
                            f"Mixing is PERMITTED (X)."
                        )
                elif note_content: # Sadece sayı (2, 4) durumu
                    status = "CONDITIONAL"
                    doc_text = (
                        f"Compatibility Rule: Group {row_group} and Group {col_group_clean} mixing is CONDITIONAL. "
                        f"Refer to Note.{note_content}" # ARTIK BURASI DOLU GELECEK!
                    )
                else:
                    doc_text = f"Compatibility Rule for {row_group} and {col_group_clean}: {cell_value}"

                # --- KAYIT ---
                base_meta = {"type": "compatibility_rule", "verdict": status, "source": "Table 6"}
                
                # YÖN A
                ids.append(f"rule_{row_group}_{col_group_clean}")
                documents.append(doc_text)
                metadatas.append({**base_meta, "row": row_group, "col": col_group_clean})

                # YÖN B (Farklıysa)
                if row_group != col_group_clean:
                    ids.append(f"rule_{col_group_clean}_{row_group}")
                    documents.append(doc_text)
                    metadatas.append({**base_meta, "row": col_group_clean, "col": row_group})

    except Exception as e: print(f"❌ Table 6 Hatası: {e}")
    return documents, ids, metadatas




def process_chemical_table(content):
    """
    Table T.1 (Chemical Equipment) işleme
    Her kimyasal madde için ayrı döküman oluşturur
    """
    documents = []
    ids = []
    metadatas = []

    # Table T.1'i bul
    table_t1_match = re.search(r'Table T\.1.*?(<table>.*?</table>)', content, re.DOTALL | re.IGNORECASE)
    if not table_t1_match:
        print("⚠️ Table T.1 bulunamadı!")
        return documents, ids, metadatas

    html_table = table_t1_match.group(1)

    try:
        # BeautifulSoup ile parse et (daha iyi kontrol için)
        soup = BeautifulSoup(html_table, 'html.parser')
        rows = soup.find_all('tr')

        # Header bilgisi (sabit - dokümantasyondan biliyoruz)
        # Sütunlar: Chemical Name, Group, Set 1, Set 2, Set 3, Breathing Apparatus, Apply No Water

        for row_idx, row in enumerate(rows):
            cells = row.find_all('td')
            if len(cells) < 7:
                continue

            chemical_name = cells[0].get_text().strip()
            group = cells[1].get_text().strip()

            # Sayısal satırları atla (1, 2, 3, 4, 5, 6, 7 header satırı)
            if chemical_name.isdigit() or not chemical_name:
                continue

            # LaTeX temizle
            chemical_name = chemical_name.replace('\\(', '').replace('\\)', '').replace('^1', ' (Note 1)')

            # Ekipman gereksinimlerini topla
            equipment = []
            warnings = []

            set1 = cells[2].get_text().strip()
            set2 = cells[3].get_text().strip()
            set3 = cells[4].get_text().strip()
            breathing = cells[5].get_text().strip()
            no_water = cells[6].get_text().strip()

            if 'X' in set1:
                equipment.append("Full Protective Clothing Set 1")
            if 'X' in set2:
                equipment.append("Full Protective Clothing Set 2")
            if 'X' in set3:
                equipment.append("Full Protective Clothing Set 3")
            if 'X' in breathing:
                equipment.append("Breathing Apparatus")
            if 'X' in no_water:
                warnings.append("APPLY NO WATER")

            # Döküman oluştur
            doc_id = f"chemical_{row_idx}_{chemical_name[:20].replace(' ', '_')}"

            doc_text = f"{chemical_name} storage requirements: Compatibility Group {group}."

            if equipment:
                doc_text += f" Required safety equipment: {', '.join(equipment)}."

            if warnings:
                doc_text += f" Special warning: {', '.join(warnings)}."

            doc_text += " (AASTP-1 Table T.1)"

            documents.append(doc_text)
            ids.append(doc_id)
            metadatas.append({
                "type": "chemical_requirement",
                "source": "Table T.1",
                "chemical": chemical_name,
                "group": group,
                "has_set1": 'X' in set1,
                "has_set2": 'X' in set2,
                "has_set3": 'X' in set3,
                "has_breathing_apparatus": 'X' in breathing,
                "apply_no_water": 'X' in no_water
            })

        print(f"✅ Table T.1'den {len(documents)} kimyasal dökümanı oluşturuldu")

    except Exception as e:
        print(f"❌ Table T.1 işleme hatası: {e}")

    return documents, ids, metadatas


def process_notes(content):
    """
    Notları ayrı dökümanlar olarak işle
    """
    documents = []
    ids = []
    metadatas = []

    for note_num, note_text in NOTES.items():
        if len(note_text) < 20:
            continue

        doc_id = f"note_{note_num}"

        # İlgili grupları bul
        related_groups = re.findall(r'Group\s+([A-S])', note_text)
        related_groups = list(set(related_groups))

        doc_text = f"AASTP-1 Note {note_num}: {note_text}"

        documents.append(doc_text)
        ids.append(doc_id)
        metadatas.append({
            "type": "note",
            "note_number": note_num,
            "related_groups": ','.join(related_groups) if related_groups else ""
        })

    print(f"✅ {len(documents)} not dökümanı oluşturuldu")

    return documents, ids, metadatas


def process_text_blocks(content):
    """
    Genel metin bloklarını işle (section kuralları vb.)
    """
    documents = []
    ids = []
    metadatas = []

    # Tabloları ve notları çıkar
    text_only = re.sub(r'<table>.*?</table>', '', content, flags=re.DOTALL)
    text_only = re.sub(r'# NOTES.*?(?=# \d|$)', '', text_only, flags=re.DOTALL)
    text_only = re.sub(r'# Notes:.*?(?=\n\n|Articles may)', '', text_only, flags=re.DOTALL)

    # Section başlıklarını bul ve paragrafları çıkar
    sections = re.split(r'(# \d+\.\d+\.\d+\.\d*\.?\s*[^\n]+)', text_only)

    current_section = ""
    for i, part in enumerate(sections):
        part = part.strip()
        if not part:
            continue

        # Section başlığı mı?
        if part.startswith('# '):
            current_section = part.replace('# ', '')
            continue

        # İçerik kısmı
        paragraphs = part.split('\n\n')
        for p_idx, para in enumerate(paragraphs):
            para = para.strip()
            if len(para) < 50:  # Çok kısa paragrafları atla
                continue

            # Anahtar kelimeleri çıkar
            keywords = []
            if 'suspect' in para.lower():
                keywords.append('suspect')
            if 'ammunition' in para.lower():
                keywords.append('ammunition')
            if 'explosive' in para.lower():
                keywords.append('explosive')
            if 'hazard division' in para.lower():
                keywords.append('hazard_division')
            if 'mixing' in para.lower():
                keywords.append('mixing')
            if 'storage' in para.lower():
                keywords.append('storage')

            # Grupları bul
            groups = re.findall(r'Group\s+([A-S])', para)
            groups = list(set(groups))

            doc_id = f"text_{hash(para[:50]) % 100000}_{p_idx}"

            documents.append(para)
            ids.append(doc_id)
            metadatas.append({
                "type": "general_rule",
                "source": current_section[:50] if current_section else "general",
                "keywords": ','.join(keywords) if keywords else "",
                "related_groups": ','.join(groups) if groups else ""
            })

    print(f"✅ {len(documents)} metin bloğu dökümanı oluşturuldu")

    return documents, ids, metadatas


def create_universal_db():
    """
    Ana fonksiyon: Tüm dökümanları oluştur ve ChromaDB'ye kaydet
    """
    global NOTES

    print(f"📂 Okunuyor: {INPUT_FILE}")
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Dosya bulunamadı: {INPUT_FILE}")
        return

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    # Önce notları çıkar (diğer fonksiyonlar kullanacak)
    NOTES = extract_notes_from_content(content)
    print(f"📝 {len(NOTES)} not bulundu: {list(NOTES.keys())}")

    # ChromaDB başlat (ESKİ VERİYİ SİL)
    client = chromadb.PersistentClient(path=DB_PATH)
    try:
        client.delete_collection(name="aastp1_universal")
        print("🗑️ Eski koleksiyon silindi")
    except:
        pass

    print("⚙️ Embedding Modeli: all-MiniLM-L6-v2")
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
    collection = client.create_collection(name="aastp1_universal", embedding_function=emb_fn)

    # Tüm dökümanları topla
    all_documents = []
    all_ids = []
    all_metadatas = []

    # 1. Compatibility Matrix (Table 6)
    print("\n📊 Table 6 (Compatibility Matrix) işleniyor...")
    docs, ids, metas = process_compatibility_matrix(content)
    all_documents.extend(docs)
    all_ids.extend(ids)
    all_metadatas.extend(metas)

    # 2. Chemical Equipment (Table T.1)
    print("\n🧪 Table T.1 (Chemical Equipment) işleniyor...")
    docs, ids, metas = process_chemical_table(content)
    all_documents.extend(docs)
    all_ids.extend(ids)
    all_metadatas.extend(metas)

    # 3. Notes
    print("\n📝 Notlar işleniyor...")
    docs, ids, metas = process_notes(content)
    all_documents.extend(docs)
    all_ids.extend(ids)
    all_metadatas.extend(metas)

    # 4. Text Blocks
    print("\n📄 Metin blokları işleniyor...")
    docs, ids, metas = process_text_blocks(content)
    all_documents.extend(docs)
    all_ids.extend(ids)
    all_metadatas.extend(metas)

    # ChromaDB'ye kaydet
    if all_documents:
        print(f"\n💾 Toplam {len(all_documents)} döküman kaydediliyor...")

        # Batch upload
        batch_size = 100
        for i in range(0, len(all_documents), batch_size):
            batch_docs = all_documents[i:i+batch_size]
            batch_ids = all_ids[i:i+batch_size]
            batch_metas = all_metadatas[i:i+batch_size]

            collection.add(
                documents=batch_docs,
                ids=batch_ids,
                metadatas=batch_metas
            )
            print(f"  ✓ Batch {i//batch_size + 1}: {len(batch_docs)} döküman kaydedildi")

        print(f"\n✅ HÜCRE BAZLI VEKTÖRİZASYON TAMAMLANDI!")
        print(f"📂 Veritabanı: {DB_PATH}")
        print(f"📊 Toplam döküman: {len(all_documents)}")

        # İstatistik
        type_counts = {}
        for meta in all_metadatas:
            t = meta.get('type', 'unknown')
            type_counts[t] = type_counts.get(t, 0) + 1

        print(f"\n📈 Döküman Dağılımı:")
        for t, count in type_counts.items():
            print(f"   - {t}: {count}")
    else:
        print("❌ Kaydedilecek döküman bulunamadı!")


if __name__ == "__main__":
    create_universal_db()
