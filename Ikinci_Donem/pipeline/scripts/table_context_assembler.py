"""
TableContextAssembler
=====================
MinerU JSON çıktısındaki her tablo için tam semantik ünite oluşturur.

Çözdüğü problem:
- Notlar tablo sonrasında birden fazla sayfaya yayılabiliyor.
  Mevcut kod sayfa sınırında durduğu için Note 6-7 gibi devam notları
  kaçırılıyordu. Bu script sayfa sınırını geçer, yeni bölüm başlığı
  veya başka bir tablo görünce durur.

Çıktı (her tablo için):
{
  "table_idx": int,
  "table_name": str,
  "page_idx": int,
  "html": str,           -- ham tablo HTML
  "img_path": str,
  "legend": str,         -- "X= Mixing permitted" gibi
  "notes": [str],        -- tüm notlar, sayfa aşımı dahil
  "footnotes": [str],    -- page_footnote blokları
  "hierarchy": {         -- tablonun bulunduğu bölüm
    "level_1": str,
    "level_2": str,
    "level_3": str
  }
}
"""

import json
import os
import re
from pathlib import Path

PIPELINE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_JSON = PIPELINE_DIR / "input" / "AASTP_1_May2006_20-39" / "AASTP-1-May2006.003973-20-39_content_list.json"
OUTPUT_DIR = PIPELINE_DIR / "data" / "semantic_units"

# MinerU'nun ürettiği gürültü blok tipleri — içerik taşımaz
NOISE_TYPES = {"header", "footer", "page_number"}

# Tip "text" olmasına rağmen içerik taşımayan bilinen boilerplate satırlar.
# MinerU bunları bazen text_level=1 ile işaretler ve yanlış durdurma tetikler.
NOISE_TEXTS = {
    "nato/pfp unclassified",
    "aastp-1",
    "aastp-1 (edition 1)",
    "(edition 1)",
    "change 2",
    "change 1",
}

# Numaralı bölüm başlığı regex: "1.2.3.3. Title" formatı
# Bu pattern eşleşirse yeni bir section başlamış demektir, tarama durur.
import re as _re
_SECTION_HEADING_RE = _re.compile(r"^\d+\.\d+")

# NOTES bölümünün başladığını gösteren tetikleyiciler
NOTES_TRIGGERS = {"notes", "note"}

# İleriye taramayı durduran bölüm başlığı seviyesi
# text_level <= STOP_LEVEL ise yeni bir ana bölüm başlamış demektir
STOP_LEVEL = 2


def _is_noise(block: dict) -> bool:
    if block.get("type") in NOISE_TYPES:
        return True
    # text tipi ama bilinen boilerplate
    text = (block.get("text") or "").strip().lower()
    return text in NOISE_TEXTS


def _is_section_heading(block: dict) -> bool:
    """Yeni bir bölüm başlığı mı?

    İki koşuldan biri yeterliyse True döner:
    1. text_level <= STOP_LEVEL (MinerU'nun başlık etiketleri)
    2. Metin numaralı bölüm formatında ("1.2.3." gibi) — text_level
       bazen eksik olabilir.
    """
    if block.get("type") != "text":
        return False
    text = (block.get("text") or "").strip()
    level = block.get("text_level")
    if level is not None and level <= STOP_LEVEL:
        return True
    if _SECTION_HEADING_RE.match(text):
        return True
    return False


def _extract_list_items(block: dict) -> list[str]:
    """list bloğundan metin öğelerini al."""
    items = block.get("list_items", [])
    return [str(item).strip() for item in items if str(item).strip()]


def _scan_backward(data: list, table_idx: int) -> dict:
    """
    Tablo öncesine doğru tarar, section hiyerarşisini toplar.
    Başka bir tablo görülünce durur.
    """
    hierarchy = {}
    found_levels = set()

    for i in range(table_idx - 1, -1, -1):
        block = data[i]

        if _is_noise(block):
            continue

        if block.get("type") == "table":
            break

        if block.get("type") == "text":
            level = block.get("text_level")
            text = (block.get("text") or "").strip()
            if not text:
                continue
            if level is not None and level not in found_levels:
                hierarchy[f"level_{level}"] = text
                found_levels.add(level)

        # 3 seviye hiyerarşi yeterliyse erken çık
        if len(found_levels) >= 3:
            break

    return hierarchy


def _scan_forward(data: list, table_idx: int) -> dict:
    """
    Tablo sonrasına doğru tarar. Şunları toplar:
      - LEGEND satırı
      - NOTES bölümündeki tüm list_items ve text blokları
      - page_footnote blokları

    Durdurma koşulları:
      - Başka bir tablo
      - Yeni bir bölüm başlığı (text_level <= STOP_LEVEL)
        AMA NOTES tetikleyicisi henüz geçilmediyse bu koşul daha katı:
        herhangi bir text_level=1 veya text_level=2 görülünce dur.
    """
    legend = ""
    notes = []
    footnotes = []
    in_notes_section = False

    for i in range(table_idx + 1, len(data)):
        block = data[i]
        btype = block.get("type", "")
        text = (block.get("text") or "").strip()

        # Gürültü — atla ama devam et (sayfa aşımı burada olur)
        if _is_noise(block):
            continue

        # Başka tablo — kesin dur
        if btype == "table":
            break

        # page_footnote her zaman topla
        if btype == "page_footnote":
            if text:
                footnotes.append(text)
            continue

        if btype == "text":
            text_lower = text.lower().strip().rstrip(":")

            # LEGEND satırı (tablo hemen altında, "X=" veya "LEGEND" içerir)
            if not in_notes_section and (
                "legend" in text_lower
                or text_lower.startswith("x=")
                or "mixing permitted" in text_lower
            ):
                legend = text
                continue

            # NOTES başlığı tetikleyicisi — section heading kontrolünden ÖNCE yapılmalı.
            # MinerU "Notes:" satırını text_level=2 olarak işaretleyebilir; bu yüzden
            # önce içerik kontrolü yapıyoruz, ardından heading kontrolü.
            if text_lower in NOTES_TRIGGERS or text_lower == "notes":
                in_notes_section = True
                continue

            # Yeni bölüm başlığı — notes'a girmedikten sonra dur.
            # Notes içindeyken de yeni bir ana başlık görülürse dur.
            if _is_section_heading(block):
                break

            # NOTES içindeki metin blokları (sayfa aşımında gelen not devamları)
            if in_notes_section and text:
                notes.append(text)
            # NOTES öncesindeki açıklama metinleri atlanır

            continue

        # List blokları — genelde notları taşır
        if btype == "list":
            items = _extract_list_items(block)
            if items:
                in_notes_section = True
                notes.extend(items)
            continue

    return {"legend": legend, "notes": notes, "footnotes": footnotes}


def assemble_semantic_units(json_path: str | Path) -> list[dict]:
    """
    Verilen MinerU JSON dosyasındaki tüm tablolar için semantik ünite listesi döner.
    """
    json_path = Path(json_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    units = []

    for i, block in enumerate(data):
        if block.get("type") != "table":
            continue

        caption_list = block.get("table_caption", [])
        table_name = caption_list[0].strip() if caption_list else f"Table_page{block.get('page_idx', '?')}"

        # Geriye tara → hiyerarşi
        hierarchy = _scan_backward(data, i)

        # İleriye tara → legend, notes, footnotes
        forward = _scan_forward(data, i)

        unit = {
            "table_idx": i,
            "table_name": table_name,
            "page_idx": block.get("page_idx", -1),
            "html": block.get("table_body", ""),
            "img_path": block.get("img_path", ""),
            "legend": forward["legend"],
            "notes": forward["notes"],
            "footnotes": forward["footnotes"],
            "hierarchy": hierarchy,
        }

        units.append(unit)
        print(f"✅ Toplandı: '{table_name[:60]}' — {len(forward['notes'])} not, {len(forward['footnotes'])} dipnot")

    return units


def save_semantic_units(units: list[dict], output_dir: str | Path = OUTPUT_DIR) -> Path:
    """Semantik üniteleri JSON dosyasına kaydeder."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "semantic_units.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=2)
    print(f"\n💾 {len(units)} semantik ünite kaydedildi: {out_path}")
    return out_path


def print_unit_summary(unit: dict) -> None:
    """Tek bir semantik ünitenin özetini ekrana basar (debug için)."""
    print(f"\n{'='*60}")
    print(f"TABLO   : {unit['table_name']}")
    print(f"Sayfa   : {unit['page_idx']}")
    print(f"HTML    : {len(unit['html'])} karakter")
    print(f"Hiyerarşi: {unit['hierarchy']}")
    print(f"Legend  : {unit['legend'] or '—'}")
    print(f"Notlar  ({len(unit['notes'])}):")
    for n in unit["notes"]:
        print(f"  • {n[:120]}")
    if unit["footnotes"]:
        print(f"Dipnotlar ({len(unit['footnotes'])}):")
        for fn in unit["footnotes"]:
            print(f"  † {fn[:120]}")


if __name__ == "__main__":
    import sys

    json_path = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_JSON)

    print(f"📂 JSON: {json_path}\n")
    units = assemble_semantic_units(json_path)

    print(f"\n📊 Toplam {len(units)} tablo bulundu.\n")
    for unit in units:
        print_unit_summary(unit)

    save_semantic_units(units)
