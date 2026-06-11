"""
Report Parser
=============
Denetim raporu PDF'inden numaralı maddeleri çıkarır.

Dışarıya açık:
    parse_report(pdf_path) -> list[dict]

Her madde:
    {
      "item_no" : int,
      "text"    : str,
    }
"""

import re
from pathlib import Path

import pdfplumber


_ITEM_RE = re.compile(r"^(\d{1,3})\.\s+(.+)", re.DOTALL)


def _extract_text(pdf_path: Path) -> str:
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=2, y_tolerance=3)
            if text:
                pages.append(text)
    return "\n".join(pages)


def _split_items(raw_text: str) -> list[dict]:
    # Her satırı al, numaralı madde başlarken yeni item aç
    lines = [l.rstrip() for l in raw_text.splitlines()]
    items: list[dict] = []
    current_no: int | None = None
    current_lines: list[str] = []

    for line in lines:
        m = re.match(r"^(\d{1,3})\.\s+(.*)", line)
        if m:
            # Önceki maddeyi kaydet
            if current_no is not None:
                text = " ".join(current_lines).strip()
                if text:
                    items.append({"item_no": current_no, "text": text})
            current_no = int(m.group(1))
            current_lines = [m.group(2).strip()]
        elif current_no is not None and line.strip():
            # Devam satırı — bir önceki maddeye ekle
            current_lines.append(line.strip())

    # Son madde
    if current_no is not None:
        text = " ".join(current_lines).strip()
        if text:
            items.append({"item_no": current_no, "text": text})

    return items


def parse_report(pdf_path: str | Path) -> list[dict]:
    pdf_path = Path(pdf_path)
    raw = _extract_text(pdf_path)
    items = _split_items(raw)
    return items
