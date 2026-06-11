"""
table_serializer.py
===================
Deterministik (LLM yok) tablo serializer.
HTML → okunabilir prose; hem embedding vektörü hem LLM context olarak kullanılır.

Dışarıya açık:
    table_display_name(unit) -> str
    serialize_table(unit)    -> str
"""

import re
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# HTML Parser
# ---------------------------------------------------------------------------

class _TableParser(HTMLParser):
    """HTML tablosunu 2D metin listesine çevirir (rowspan/colspan görmezden gelinir)."""

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._buf: str | None = None

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._buf = ""

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag in ("td", "th") and self._buf is not None:
            if self._row is not None:
                self._row.append(self._buf.strip())
            self._buf = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf += data


def _parse_html(html: str) -> list[list[str]]:
    """HTML'yi 2D liste olarak döndürür; tamamen boş satırları atar."""
    p = _TableParser()
    p.feed(html)
    return [r for r in p.rows if any(c.strip() for c in r)]


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _clean(cell: str) -> str:
    """LaTeX footnote işaretlerini [N] formatına çevirir, diğer $ ifadelerini temizler."""
    cell = re.sub(r'\$\^?\{?(\w+)\}?\$', r'[\1]', cell)  # $^{1}$ → [1]
    cell = re.sub(r'\$[^$]+\$', '', cell)                  # kalan LaTeX
    return cell.strip()


def _build_fmap(raw_footnotes: list[str]) -> dict[str, str]:
    """["$^{1}$ metin...", ...] → {"1": "metin...", ...}"""
    fmap: dict[str, str] = {}
    for fn in raw_footnotes:
        fn = fn.strip()
        m = re.match(r'^\$?\^?\{?(\w+)\}?\$?\s+(.*)', fn)
        if m:
            key, val = m.group(1), m.group(2).strip()
            if key and val:
                fmap[key] = val
    return fmap


def _expand(text: str, fmap: dict[str, str]) -> str:
    """[1] → (footnote metni)"""
    return re.sub(
        r'\[(\w+)\]',
        lambda m: f"({fmap[m.group(1)]})" if m.group(1) in fmap else m.group(0),
        text,
    )


# ---------------------------------------------------------------------------
# Tablo görünen adı (Table_pageN → anlamlı isim)
# ---------------------------------------------------------------------------

def table_display_name(unit: dict) -> str:
    """
    Tablonun temiz görünen adını döndürür (domain'e özel sabit yok).
    - Gerçek caption varsa onu kullanır.
    - Table_pageN ise: bölüm hiyerarşisi → sayfa fallback.
    """
    name = unit.get("table_name", "")
    if not name.startswith("Table_page"):
        return name

    page = unit.get("page_idx", -1)
    hier = unit.get("hierarchy", {}) or {}
    if hier:
        section = list(hier.values())[-1]
        return f"Table (p.{page}): {section}"

    return f"Table (p.{page})"


# ---------------------------------------------------------------------------
# Ana serializer
# ---------------------------------------------------------------------------

def serialize_table(unit: dict) -> str:
    """
    Tablo unit'ini embedding + LLM context için prose'a çevirir.

    Çıktı yapısı:
        [display_name]
        [Section: ...]
        [legend]

        [satır cümleleri]

        Notes:
        - ...

        Footnotes:
        - ...
    """
    html      = unit.get("html", "")
    footnotes = unit.get("footnotes", []) or []
    notes     = unit.get("notes", []) or []
    legend    = (unit.get("legend") or "").strip()
    hierarchy = unit.get("hierarchy", {}) or {}
    dname     = table_display_name(unit)

    rows = _parse_html(html)
    fmap = _build_fmap(footnotes)

    # --- Başlık bloğu ---
    header_lines = [dname]
    if hierarchy:
        header_lines.append("Section: " + " > ".join(hierarchy.values()))
    if legend:
        header_lines.append(legend)
    header = "\n".join(header_lines)

    # --- İçerik ---
    content = _dispatch(rows, fmap, legend) if rows else ""

    # --- Birleştir ---
    parts = [p for p in [header, content] if p.strip()]
    if notes:
        parts.append("Notes:\n" + "\n".join(f"- {n}" for n in notes))
    if footnotes:
        parts.append("Footnotes:\n" + "\n".join(f"- {fn}" for fn in footnotes))

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Tablo tipi tespiti + dispatch — tamamen YAPISAL, domain kelimesi yok
# ---------------------------------------------------------------------------

# Noktalı kod: 1.1, 1.2.1, 2.3 vb. (herhangi bir standardın kod şeması)
_CODE_PAT = re.compile(r'^\d+(\.\d+)+$')


def _abbrev(label: str) -> str:
    """Çok kelimeli etiketten baş-harf kısaltması üretir: 'Hazard Division'→'HD'.
    Tek kelimelik etikette boş döner (kısaltma anlamsız)."""
    words = [w for w in re.findall(r"[A-Za-z]+", label) if w[0].isupper()]
    return "".join(w[0] for w in words) if len(words) >= 2 else ""


def _x_ratio(rows: list[list[str]]) -> float:
    """Gövde hücrelerinin (ilk sütun hariç) X/boş oranı — binary matris sinyali."""
    body = [_clean(c).upper() for r in rows[1:] for c in r[1:]]
    if not body:
        return 0.0
    return sum(1 for c in body if c in ("X", "")) / len(body)


def _dispatch(rows: list[list[str]], fmap: dict, legend: str) -> str:
    """Tablo tipini YAPISAL özelliklerden tespit edip uygun serializer'ı çağırır."""
    first_row = [_clean(c) for c in rows[0]]
    corner    = first_row[0] if first_row else ""

    # 1. Binary X-matrisi: gövde ağırlıkla X/boş (uyumluluk matrisleri vb.)
    if len(rows) > 1 and len(first_row) > 2 and _x_ratio(rows) >= 0.7:
        return _serialize_binary_matrix(rows, fmap, legend, corner)

    # 2. Kod×kod değer-matrisi: sütun başlıkları noktalı kodlarsa (1.1, 1.2.1)
    col_hdrs = [c for c in first_row[1:] if c]
    if col_hdrs and all(_CODE_PAT.match(h) for h in col_hdrs):
        return _serialize_value_matrix(rows, fmap, corner)

    # 3. Anahtar-değer / çok-sütunlu lookup
    return _serialize_kv(rows, fmap)


# ---------------------------------------------------------------------------
# Serializer'lar
# ---------------------------------------------------------------------------

def _label_pair(label: str, code: str) -> str:
    """Etiket+kod ikilisini hem kısaltma hem tam adla yazar (vocabulary match):
    ('Hazard Division','1.1') → 'HD 1.1 (Hazard Division 1.1)'. Etiket yoksa kod."""
    label = label.strip()
    if not label:
        return code
    ab = _abbrev(label)
    if ab:
        return f"{ab} {code} ({label} {code})"
    return f"{label} {code}"


def _serialize_value_matrix(rows: list[list[str]], fmap: dict, corner: str) -> str:
    """
    Kod×kod değer matrisi (örn. AASTP Table 4): satır_kodu × sütun_kodu → değer.
    Etiket sözlüğü köşe hücresinden türetilir — domain'e özel sabit yok.
    """
    col_hdrs = [_clean(c) for c in rows[0][1:]]
    intro = (f"{corner} combination matrix — resulting value for each pair:"
             if corner else "Combination matrix — resulting value for each pair:")
    lines: list[str] = [intro]

    for row in rows[1:]:
        if not row:
            continue
        rcode = _clean(row[0])
        if not rcode:
            continue
        for j, raw in enumerate(row[1:]):
            if j >= len(col_hdrs):
                break
            ccode = col_hdrs[j]
            val   = _clean(raw)
            if not val or not ccode:
                continue
            val_exp = _expand(val, fmap)
            lines.append(
                f"{_label_pair(corner, rcode)} combined with "
                f"{_label_pair(corner, ccode)}: resulting value {val_exp}."
            )

    return "\n".join(lines)


def _legend_x_meaning(legend: str) -> tuple[str, str]:
    """Legend'dan X işaretinin anlamını çıkarır: 'X = mixing permitted' →
    ('mixing permitted', 'mixing not permitted'). Bulunamazsa jenerik ikili."""
    m = re.search(r"\bX\s*[=:]\s*([^;.\n]+)", legend, re.IGNORECASE)
    if m:
        meaning = m.group(1).strip().rstrip(",")
        # "Mixing permitted" → olumsuzu "Mixing NOT permitted" (son kelimeden önce)
        words = meaning.split()
        if len(words) >= 2:
            neg = " ".join(words[:-1] + ["NOT", words[-1]])
        else:
            neg = f"NOT {meaning}"
        return meaning, neg
    return "permitted (marked X)", "not permitted (unmarked)"


def _serialize_binary_matrix(rows: list[list[str]], fmap: dict,
                             legend: str, corner: str) -> str:
    """
    Binary X-matrisi (örn. uyumluluk matrisleri): X → izinli, boş → izinsiz.
    Satır/sütun etiketi köşe hücresinden, X'in anlamı legend'dan türetilir.
    """
    col_lbls = [_clean(c) for c in rows[0][1:]]
    pos, neg = _legend_x_meaning(legend)
    lines: list[str] = []

    for row in rows[1:]:
        if not row:
            continue
        rl = _clean(row[0])
        if not rl:
            continue
        for j, raw in enumerate(row[1:]):
            if j >= len(col_lbls):
                break
            cl  = col_lbls[j]
            if not cl:
                continue
            val = _clean(raw).upper()
            if val == "X":
                perm = pos
            elif not val:
                perm = neg
            else:
                perm = _expand(_clean(raw), fmap)
            row_t = f"{corner} {rl}" if corner else rl
            col_t = f"{corner} {cl}" if corner else cl
            lines.append(f"{row_t} with {col_t}: {perm}.")

    return "\n".join(lines)


def _serialize_kv(rows: list[list[str]], fmap: dict) -> str:
    """
    Genel anahtar-değer veya çok-sütunlu lookup (Table 133, T.2 vb.).
    Her satır → "Col1: Val1; Col2: Val2; ..." cümlesi.
    Değer noktalı kodlardan oluşuyorsa başlık etiketi+kısaltmasıyla genişletilir
    (örn. başlık 'Hazard Division', değer '1.1; 1.5' →
    'HD 1.1 (Hazard Division 1.1); HD 1.5 (Hazard Division 1.5)') —
    başlıktan türetilir, domain'e özel sabit yok.
    """
    hdrs = [_clean(c) for c in rows[0]]
    lines: list[str] = []

    for row in rows[1:]:
        cells = [_clean(c) for c in row]
        if not any(cells):
            continue
        pairs = []
        for h, v in zip(hdrs, cells):
            if not v:
                continue
            parts = [x.strip() for x in v.split(";") if x.strip()]
            if h and parts and all(_CODE_PAT.match(x) for x in parts):
                v = "; ".join(_label_pair(h, x) for x in parts)
            pairs.append(f"{h}: {v}" if h else v)
        if pairs:
            lines.append(_expand("; ".join(pairs) + ".", fmap))

    return "\n".join(lines)
