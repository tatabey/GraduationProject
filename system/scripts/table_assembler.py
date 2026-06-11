"""
Table Assembler
===============
MinerU JSON çıktısındaki her tablo için semantik ünite üretir.
Notları sayfa sınırını aşarak toplar, gürültü tablolarını filtreler,
parçalanmış tabloları birleştirir.

Dışarıya açık:
    assemble_semantic_units(json_path) -> (units, rejected)
    save_semantic_units(units, rejected, output_dir)
"""

import json
import re
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

# ---------------------------------------------------------------------------
# Yapısal filtre parametreleri
# ---------------------------------------------------------------------------
MIN_FILL_RATE       = 0.30   # dolu hücre oranı
MIN_HTML_LEN        = 100    # minimum HTML karakter sayısı
BOILERPLATE_MIN_PAGES = 5    # kaç sayfada tekrar ederse boilerplate
STOP_LEVEL          = 2      # bu text_level'dan büyük başlık yeni bölüm başlatır
NOTES_TRIGGERS      = {"notes", "note"}
NOISE_TYPES         = {"header", "footer", "page_number"}
_SECTION_HEADING_RE = re.compile(r"^\d+\.\d+")


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
class _CellCounter(HTMLParser):
    def __init__(self):
        super().__init__()
        self.total = self.non_empty = 0
        self._buf = ""; self._in = False

    def handle_starttag(self, tag, attrs):
        if tag in ("td", "th"):
            self.total += 1; self._in = True; self._buf = ""

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._in:
            if self._buf.strip(): self.non_empty += 1
            self._in = False

    def handle_data(self, data):
        if self._in: self._buf += data


def _is_real_table(html: str) -> tuple[bool, str]:
    if len(html) < MIN_HTML_LEN:
        return False, f"html_len={len(html)} < {MIN_HTML_LEN}"
    c = _CellCounter(); c.feed(html)
    if c.total == 0:
        return False, "hücre yok"
    fr = c.non_empty / c.total
    if fr < MIN_FILL_RATE:
        return False, f"doluluk={fr:.0%} < {MIN_FILL_RATE:.0%} ({c.non_empty}/{c.total} hücre dolu)"
    return True, ""


def detect_boilerplate(data: list, min_pages: int = BOILERPLATE_MIN_PAGES) -> set[str]:
    text_pages: dict[str, set[int]] = defaultdict(set)
    for block in data:
        text = (block.get("text") or "").strip()
        if len(text) < 5:
            continue
        text_pages[text.lower()].add(block.get("page_idx", -1))
    return {t for t, pages in text_pages.items() if len(pages) >= min_pages}


def _is_noise(block: dict, boilerplate: set[str]) -> bool:
    if block.get("type") in NOISE_TYPES:
        return True
    return (block.get("text") or "").strip().lower() in boilerplate


def _is_section_heading(block: dict) -> bool:
    if block.get("type") != "text":
        return False
    text  = (block.get("text") or "").strip()
    level = block.get("text_level")
    if level is not None and level <= STOP_LEVEL:
        return True
    return bool(_SECTION_HEADING_RE.match(text))


def _extract_list_items(block: dict) -> list[str]:
    return [str(i).strip() for i in block.get("list_items", []) if str(i).strip()]


# ---------------------------------------------------------------------------
# Tablo çevresi tarama
# ---------------------------------------------------------------------------
def _scan_backward(data: list, table_idx: int, boilerplate: set[str]) -> dict:
    hierarchy = {}
    found_levels: set = set()
    for i in range(table_idx - 1, -1, -1):
        block = data[i]
        if _is_noise(block, boilerplate): continue
        if block.get("type") == "table": break
        if block.get("type") == "text":
            level = block.get("text_level")
            text  = (block.get("text") or "").strip()
            if text and level is not None and level not in found_levels:
                hierarchy[f"level_{level}"] = text
                found_levels.add(level)
        if len(found_levels) >= 3:
            break
    return hierarchy


def _scan_forward(data: list, table_idx: int, boilerplate: set[str]) -> dict:
    legend = ""; notes = []; footnotes = []; in_notes = False
    for i in range(table_idx + 1, len(data)):
        block = data[i]
        btype = block.get("type", "")
        text  = (block.get("text") or "").strip()

        if _is_noise(block, boilerplate): continue
        if btype == "table": break
        if btype == "page_footnote":
            if text: footnotes.append(text)
            continue
        if btype == "text":
            tl = text.lower().strip().rstrip(":")
            if not in_notes and ("legend" in tl or tl.startswith("x=") or "mixing permitted" in tl):
                legend = text; continue
            if tl in NOTES_TRIGGERS:
                in_notes = True; continue
            if _is_section_heading(block): break
            if in_notes and text: notes.append(text)
            continue
        if btype == "list":
            items = _extract_list_items(block)
            if items:
                in_notes = True
                notes.extend(items)
    return {"legend": legend, "notes": notes, "footnotes": footnotes}


# ---------------------------------------------------------------------------
# Parça birleştirme
# ---------------------------------------------------------------------------
def _get_col_count(html: str) -> int:
    m = re.search(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE)
    if not m: return 0
    row = m.group(1).lower()
    return row.count("<td") + row.count("<th")


def _page_n_prefix(name: str) -> str:
    m = re.match(r"^(.+?)\s*\(PAGE\s*\d+\)", name, re.IGNORECASE)
    return m.group(1).strip().upper() if m else ""


def _merge_group(group: list[dict]) -> dict:
    best_name = group[0]["table_name"]
    for u in group:
        if not u["table_name"].startswith("Table_page"):
            name   = u["table_name"]
            prefix = _page_n_prefix(name)
            best_name = re.sub(r"\s*\(PAGE\s*\d+\)\s*", " ", name, flags=re.IGNORECASE).strip(" -") if prefix else name
            break
    seen_n: set = set(); seen_f: set = set()
    all_notes: list[str] = []; all_fn: list[str] = []
    for u in group:
        for n in u["notes"]:
            if n not in seen_n: all_notes.append(n); seen_n.add(n)
        for f in u["footnotes"]:
            if f not in seen_f: all_fn.append(f); seen_f.add(f)
    return {
        **group[0],
        "table_name": best_name,
        "html"      : "\n".join(u["html"] for u in group),
        "notes"     : all_notes,
        "footnotes" : all_fn,
        "legend"    : next((u["legend"] for u in group if u["legend"]), ""),
        "merged_pages": [u["page_idx"] for u in group],
    }


def merge_fragmented_tables(units: list[dict], max_page_gap: int = 1) -> list[dict]:
    if not units: return units
    n          = len(units)
    used       = [False] * n
    col_counts = [_get_col_count(u["html"]) for u in units]
    result: list[dict] = []

    def is_unnamed(idx: int) -> bool:
        return units[idx]["table_name"].startswith("Table_page")

    for i in range(n):
        if used[i] or is_unnamed(i): continue
        used[i] = True
        anchor_col    = col_counts[i]
        anchor_prefix = _page_n_prefix(units[i]["table_name"])
        group_idx     = [i]
        last_page     = units[i]["page_idx"]

        prepend: list[int] = []
        for j in range(i - 1, -1, -1):
            if used[j]: break
            if (is_unnamed(j) and col_counts[j] == anchor_col
                    and units[i]["page_idx"] - units[j]["page_idx"] <= max_page_gap):
                prepend.insert(0, j); used[j] = True
            else: break

        for j in range(i + 1, n):
            if used[j]: break
            u = units[j]
            if u["page_idx"] - last_page > max_page_gap: break
            j_prefix = _page_n_prefix(u["table_name"])
            if anchor_prefix and j_prefix and anchor_prefix == j_prefix:
                group_idx.append(j); used[j] = True; last_page = u["page_idx"]; continue
            if is_unnamed(j) and col_counts[j] == anchor_col:
                group_idx.append(j); used[j] = True; last_page = u["page_idx"]; continue
            break

        full_group = [units[k] for k in (prepend + group_idx)]
        if len(full_group) == 1:
            result.append(units[i])
        else:
            merged = _merge_group(full_group)
            pages  = merged.get("merged_pages", [units[i]["page_idx"]])
            print(f"  Birleştirildi ({len(full_group)} parça, s{pages[0]}–{pages[-1]}): '{merged['table_name'][:50]}'")
            result.append(merged)

    for i in range(n):
        if not used[i]: result.append(units[i])

    result.sort(key=lambda u: u["page_idx"])
    return result


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
def assemble_semantic_units(json_path: str | Path) -> tuple[list[dict], list[dict]]:
    json_path = Path(json_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    boilerplate = detect_boilerplate(data)
    units: list[dict] = []; rejected: list[dict] = []

    for i, block in enumerate(data):
        if block.get("type") != "table":
            continue
        html         = block.get("table_body", "")
        caption_list = block.get("table_caption", [])
        table_name   = caption_list[0].strip() if caption_list else f"Table_page{block.get('page_idx', '?')}"

        passed, reason = _is_real_table(html)
        if not passed:
            rejected.append({"table_name": table_name, "page_idx": block.get("page_idx", -1),
                              "reject_reason": reason, "html_len": len(html)})
            continue
        if table_name.lower().strip() in boilerplate:
            rejected.append({"table_name": table_name, "page_idx": block.get("page_idx", -1),
                              "reject_reason": "caption boilerplate", "html_len": len(html)})
            continue

        hierarchy = _scan_backward(data, i, boilerplate)
        forward   = _scan_forward(data, i, boilerplate)
        units.append({
            "table_idx" : i,
            "table_name": table_name,
            "page_idx"  : block.get("page_idx", -1),
            "html"      : html,
            "img_path"  : block.get("img_path", ""),
            "legend"    : forward["legend"],
            "notes"     : forward["notes"],
            "footnotes" : forward["footnotes"],
            "hierarchy" : hierarchy,
        })

    units = merge_fragmented_tables(units)
    return units, rejected


def save_semantic_units(
    units: list[dict],
    rejected: list[dict],
    output_dir: str | Path,
) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    units_path    = output_dir / "semantic_units.json"
    rejected_path = output_dir / "rejected_tables.json"
    units_path.write_text(json.dumps(units, ensure_ascii=False, indent=2), encoding="utf-8")
    rejected_path.write_text(json.dumps(rejected, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  {len(units)} tablo kabul, {len(rejected)} reddedildi → {output_dir}")
    return units_path, rejected_path
