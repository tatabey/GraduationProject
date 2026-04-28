"""
TextChunker
===========
MinerU JSON'undaki text/list bloklarını section hiyerarşisine göre
anlamlı chunk'lara böler ve JSON olarak kaydeder.

Çıktı: data/text_chunks/text_chunks.json
  Her chunk:
    {
      "chunk_id"    : "chunk_p<page>_<idx>",
      "title"       : "1.2.3.1. General",
      "section_path": ["CHAPTER 2", "Section I", "1.2.1.1. General"],
      "content"     : "paragraf metni + liste maddeleri birleşik",
      "page_idx"    : 5,
      "type"        : "text_chunk"
    }

Atlanan bloklar:
  - footer, page_number, header  (sayfa gürültüsü)
  - table                        (ayrı pipeline'da indekslendi)
  - NOISE_TEXTS listesindeki tekrarlayan ifadeler
"""

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------
PIPELINE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_JSON = PIPELINE_DIR / "input" / "AASTP-1-May2006_003973_content_list.json"
OUTPUT_DIR   = PIPELINE_DIR / "data" / "text_chunks"

SKIP_TYPES  = {"footer", "page_number", "header", "table"}

NOISE_TEXTS = {
    "NATO/PFP UNCLASSIFIED",
    "AASTP-1",
    "(Edition 1)",
    "Edition 1)",
    "Downloaded from http://www.everyspec.com",
}

# text_level değeri olan bloklar heading sayılır
HEADING_LEVELS = {1, 2, 3, 4}

MIN_CONTENT_CHARS = 30  # çok kısa/boş chunk'ları atla

# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def _is_noise(block: dict) -> bool:
    text = block.get("text", "").strip()
    return text in NOISE_TEXTS

def _is_heading(block: dict) -> bool:
    return (
        block.get("type") == "text"
        and block.get("text_level") in HEADING_LEVELS
        and bool(block.get("text", "").strip())
    )

def _block_text(block: dict) -> str:
    """Bir bloktan düz metin çıkarır (text veya list)."""
    btype = block.get("type")
    if btype == "text":
        return block.get("text", "").strip()
    if btype in ("list", "page_footnote"):
        items = block.get("list_items") or []
        base  = block.get("text", "").strip()
        parts = [base] if base else []
        parts += [item.strip() for item in items if item.strip()]
        return "\n".join(parts)
    return ""

def _update_section_path(path: list[str], level: int, title: str) -> list[str]:
    """
    Hiyerarşi yolunu günceller.
    level=1 → yolu sıfırla; level=N → önceki N-1 elemanı koru, N. seviyeyi ekle.
    """
    new_path = path[: level - 1] + [title]
    return new_path

# ---------------------------------------------------------------------------
# Ana chunking fonksiyonu
# ---------------------------------------------------------------------------
def chunk_text_blocks(json_path: str | Path) -> list[dict]:
    json_path = Path(json_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    chunks: list[dict] = []
    section_path: list[str] = []

    current_title   = ""
    current_content: list[str] = []
    current_page    = 0
    current_start_idx = 0

    def _flush(flush_idx: int):
        nonlocal current_title, current_content, current_page
        content = "\n".join(current_content).strip()
        if len(content) >= MIN_CONTENT_CHARS:
            chunks.append({
                "chunk_id"    : f"chunk_p{current_page}_idx{current_start_idx}",
                "title"       : current_title,
                "section_path": list(section_path),
                "content"     : content,
                "page_idx"    : current_page,
                "type"        : "text_chunk",
            })
        current_content = []

    for idx, block in enumerate(data):
        btype = block.get("type")
        page  = block.get("page_idx", 0)

        # Atlanacak bloklar
        if btype in SKIP_TYPES:
            continue
        if _is_noise(block):
            continue

        if _is_heading(block):
            # Mevcut chunk'ı kaydet
            if current_title:
                _flush(idx)

            # Yeni heading başlat
            title = block.get("text", "").strip()
            level = block.get("text_level")
            section_path = _update_section_path(section_path, level, title)

            current_title     = title
            current_page      = page
            current_start_idx = idx
            # Başlık metnini content'e de ekle (arama için)
            current_content   = [title]

        else:
            # Body blok: mevcut chunk'a ekle
            text = _block_text(block)
            if text:
                current_content.append(text)
                if not current_title:
                    # Belge başında başlık gelmeden önce gelen metin
                    current_title     = "Preamble"
                    current_page      = page
                    current_start_idx = idx
                    section_path      = ["Preamble"]

    # Son chunk'ı kaydet
    if current_title:
        _flush(len(data))

    return chunks


# ---------------------------------------------------------------------------
# Kaydetme
# ---------------------------------------------------------------------------
def save_text_chunks(chunks: list[dict], output_dir: Path = OUTPUT_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "text_chunks.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    print(f"\n💾 {len(chunks)} text chunk kaydedildi: {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _preview(chunks: list[dict]):
    print(f"\n{'='*60}")
    print(f"Toplam chunk: {len(chunks)}")
    print(f"{'='*60}")
    for c in chunks:
        path_str = " > ".join(c["section_path"])
        print(f"\n[{c['chunk_id']}]  sayfa={c['page_idx']}")
        print(f"  Başlık : {c['title']}")
        print(f"  Yol    : {path_str}")
        print(f"  İçerik ({len(c['content'])} kr): {c['content'][:120]}...")


if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_JSON)
    print(f"📂 JSON: {json_path}\n")

    chunks = chunk_text_blocks(json_path)
    _preview(chunks)
    save_text_chunks(chunks)
