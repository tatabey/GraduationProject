"""
Text Chunker
============
MinerU JSON'undaki text/list bloklarını section hiyerarşisine göre
anlamlı chunk'lara böler.

Dışarıya açık:
    chunk_text_blocks(json_path) -> list[dict]
    save_text_chunks(chunks, output_dir)

Her chunk:
    {
      "chunk_id"    : "chunk_p<page>_<idx>",
      "title"       : str,
      "section_path": [str, ...],
      "content"     : str,
      "page_idx"    : int,
      "type"        : "text_chunk"
    }
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import TEXT_BOILERPLATE_MIN_PAGES

SKIP_TYPES     = {"footer", "page_number", "header", "table"}
HEADING_LEVELS = {1, 2, 3, 4}
MIN_CONTENT_CHARS = 30


def _is_heading(block: dict) -> bool:
    return (
        block.get("type") == "text"
        and block.get("text_level") in HEADING_LEVELS
        and bool(block.get("text", "").strip())
    )


def _block_text(block: dict) -> str:
    btype = block.get("type")
    if btype == "text":
        return block.get("text", "").strip()
    if btype in ("list", "page_footnote"):
        items = block.get("list_items") or []
        base  = block.get("text", "").strip()
        parts = [base] if base else []
        parts += [str(i).strip() for i in items if str(i).strip()]
        return "\n".join(parts)
    return ""


def _update_path(path: list[str], level: int, title: str) -> list[str]:
    return path[: level - 1] + [title]


def _norm_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip().lower()


def detect_boilerplate_lines(
    data: list[dict],
    min_pages: int = TEXT_BOILERPLATE_MIN_PAGES,
) -> set[str]:
    """
    ≥ min_pages FARKLI sayfada birebir tekrarlayan (normalize) satırları bulur.
    MinerU'nun body text sandığı sayfa başlığı/altlığı kalıntılarını yakalar
    ("NATO/PFP UNCLASSIFIED", "AASTP-1 (Edition 1)" vb.) — domain'e özel değil,
    her PDF'in kendi tekrarlarını sayar.
    """
    if min_pages <= 0:
        return set()
    pages_of: dict[str, set[int]] = defaultdict(set)
    for block in data:
        if block.get("type") in SKIP_TYPES:
            continue
        text = _block_text(block)
        if not text:
            continue
        page = block.get("page_idx", 0)
        for raw in text.splitlines():
            norm = _norm_line(raw)
            if norm:
                pages_of[norm].add(page)
    return {ln for ln, pages in pages_of.items() if len(pages) >= min_pages}


def _strip_boilerplate(text: str, boilerplate: set[str]) -> str:
    if not boilerplate:
        return text
    kept = [ln for ln in text.splitlines() if _norm_line(ln) not in boilerplate]
    return "\n".join(kept).strip()


def chunk_text_blocks(json_path: str | Path) -> list[dict]:
    json_path = Path(json_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    # Boilerplate yalnızca İÇERİK SATIRI düzeyinde filtrelenir; blok atlama /
    # yeniden numaralandırma YAPILMAZ → chunk_id'ler (blok indeksine bağlı)
    # her koşulda sabit kalır.
    boilerplate = detect_boilerplate_lines(data)

    chunks: list[dict] = []
    section_path: list[str] = []
    current_title = ""
    current_content: list[str] = []
    current_page = 0
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
        if block.get("type") in SKIP_TYPES:
            continue
        if _is_heading(block):
            # Sahte başlık: sayfa başlığı kalıntısı ("NATO/PFP UNCLASSIFIED" vb.)
            # MinerU tarafından heading sanılmış. Bölüm BÖLME ve içeriğe ALMA —
            # böylece bir bölüm sayfa sınırında parçalanmaz. Blok atlanmadığı
            # için indeksler (chunk_id) değişmez.
            if _norm_line(block.get("text", "")) in boilerplate:
                continue
            if current_title:
                _flush(idx)
            title         = block.get("text", "").strip()
            level         = block.get("text_level")
            section_path  = _update_path(section_path, level, title)
            current_title     = title
            current_page      = block.get("page_idx", 0)
            current_start_idx = idx
            current_content   = [title]
        else:
            text = _strip_boilerplate(_block_text(block), boilerplate)
            if text:
                current_content.append(text)
                if not current_title:
                    current_title     = "Preamble"
                    current_page      = block.get("page_idx", 0)
                    current_start_idx = idx
                    section_path      = ["Preamble"]

    if current_title:
        _flush(len(data))

    return chunks


def save_text_chunks(chunks: list[dict], output_dir: str | Path) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "text_chunks.json"
    out_path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {len(chunks)} text chunk kaydedildi → {out_path}")
    return out_path
