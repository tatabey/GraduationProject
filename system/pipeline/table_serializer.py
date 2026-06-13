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
    """HTML tablosunu 2D metin listesine çevirir; rowspan/colspan ızgaraya açılır.

    Birleşik hücreler düzleştirilir: colspan=N hücre değeri N kolona kopyalanır,
    rowspan=N değeri sonraki N-1 satırda aynı kolon konumuna taşınır. Böylece
    çok-başlıklı matris tabloları (üst-başlık + alt-başlık) veri satırlarıyla
    hizalı kalır — başlık etiketleri kaymaz, hücreler kesilmez.
    """

    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[tuple[str, int, int]] | None = None  # (text, colspan, rowspan)
        self._buf: str | None = None
        self._cur_attrs: dict | None = None
        # rowspan taşıması: {kolon_indeksi: (kalan_satir, metin)}
        self._pending: dict[int, tuple[int, str]] = {}

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._buf = ""
            self._cur_attrs = dict(attrs)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("td", "th") and self._buf is not None:
            if self._row is not None:
                def _span(name: str) -> int:
                    try:
                        return max(1, int((self._cur_attrs or {}).get(name, 1)))
                    except (TypeError, ValueError):
                        return 1
                self._row.append((self._buf.strip(), _span("colspan"), _span("rowspan")))
            self._buf = None
            self._cur_attrs = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._expand_row(self._row))
            self._row = None

    def handle_data(self, data):
        if self._buf is not None:
            self._buf += data

    def _expand_row(self, cells: list[tuple[str, int, int]]) -> list[str]:
        """(text, colspan, rowspan) hücrelerini + bekleyen rowspan'leri düz kolon
        listesine açar."""
        out: list[str] = []
        queue = list(cells)
        ci = 0
        # Hem kuyrukta hücre varken hem de mevcut/ileri kolonda bekleyen rowspan
        # varken devam et; geçilmiş (ci'den küçük) bekleyenler döngüyü uzatmaz.
        while queue or any(c >= ci for c in self._pending):
            if ci in self._pending:
                rem, text = self._pending[ci]
                out.append(text)
                if rem - 1 > 0:
                    self._pending[ci] = (rem - 1, text)
                else:
                    del self._pending[ci]
                ci += 1
                continue
            if queue:
                text, cspan, rspan = queue.pop(0)
                for _ in range(cspan):
                    out.append(text)
                    if rspan > 1:
                        self._pending[ci] = (rspan - 1, text)
                    ci += 1
            else:
                ci += 1  # kuyruk bitti ama ileride bekleyen var → boşluğu atla
        return out


def _parse_html(html: str) -> list[list[str]]:
    """HTML'yi 2D liste olarak döndürür; tamamen boş satırları atar."""
    p = _TableParser()
    p.feed(html)
    return [r for r in p.rows if any(c.strip() for c in r)]


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

# Sık LaTeX komutu → okunur sembol (sıra önemli: \leq, \le'den önce gelmeli)
_LATEX_SYM = [
    (r'\\leq', '≤'), (r'\\geq', '≥'), (r'\\le(?![a-zA-Z])', '≤'),
    (r'\\ge(?![a-zA-Z])', '≥'), (r'\\neq', '≠'),
    (r'\\rightarrow', '→'), (r'\\to(?![a-zA-Z])', '→'), (r'\\Rightarrow', '⇒'),
    (r'\\times', '×'), (r'\\cdot', '·'), (r'\\pm', '±'), (r'\\approx', '≈'),
    (r'\\div', '÷'), (r'\\sqrt', '√'), (r'\\%', '%'),
]


def _latex_to_text(expr: str) -> str:
    """$...$ içeriğini SİLMEDEN okunur metne çevirir: ≤, →, üst/alt simge, \\text{} vb.
    Mesafe formülleri ve HD satır etiketleri (örn. 1.3^2, 6.4 Q^(1/3)) korunur."""
    s = expr
    s = re.sub(r'\\text\s*\{([^}]*)\}', r'\1', s)   # \text{Compatibility Group} → metin
    for pat, rep in _LATEX_SYM:
        s = re.sub(pat, rep, s)
    s = re.sub(r'\^\{([^}]*)\}', r'^(\1)', s)        # ^{1/3} → ^(1/3)
    s = re.sub(r'_\{([^}]*)\}', r'_(\1)', s)         # _{p} → _(p)
    s = re.sub(r'\\[a-zA-Z]+', ' ', s)               # kalan komutlar → boşluk
    s = s.replace('{', '').replace('}', '').replace('\\', ' ')
    return re.sub(r'\s+', ' ', s).strip()


def _clean(cell: str) -> str:
    """LaTeX footnote işaretini [N]'e çevirir; kalan $...$ matematiğini metne dönüştürür
    (eskiden siliniyordu → formül/satır-etiketi kaybına yol açıyordu)."""
    cell = re.sub(r'\$\^?\{?(\w+)\}?\$', r'[\1]', cell)                          # $^{1}$ → [1]
    cell = re.sub(r'\$([^$]+)\$', lambda m: _latex_to_text(m.group(1)), cell)    # kalan math → metin
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
    # Sözlük bir kez intro'da; her satırda kısaltma+kod (tam ad tekrar EDİLMEZ → token tasarrufu)
    ab = _abbrev(corner)
    short = ab or corner
    name  = f"{corner} ({ab})" if ab else corner
    intro = (f"{name} combination matrix — resulting value for each pair:"
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
            rl = f"{short} {rcode}" if short else rcode
            cl = f"{short} {ccode}" if short else ccode
            lines.append(f"{rl} + {cl} → {val_exp}.")

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
    # Köşe etiketi bir kez intro'da (eskiden her satırda İKİ kez tekrarlanıyordu → büyük israf)
    lines: list[str] = []
    if corner:
        lines.append(f"{corner} — row with column (X = {pos}):")

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
            lines.append(f"{rl} with {cl}: {perm}.")

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
    body_start = 1
    lines: list[str] = []

    # Colspan-band tespiti: ilk satırın sütun başlıkları (col0 hariç) tek bir
    # tekrarlı değerse, bu bir üst-başlık bandıdır (örn. "Quantity-Distances in
    # metres" 4 kez) → gerçek başlıklar (D1-D4) alt satırda. Band'i bir kez yaz,
    # alt satırı başlık yap; hücre başına uzun band tekrarını önler.
    col_part = [h for h in hdrs[1:] if h]
    if len(rows) > 2 and len(col_part) >= 2 and len(set(col_part)) == 1:
        sub = [_clean(c) for c in rows[1]]
        if any(sub[1:]):
            lines.append(f"{col_part[0]}:")
            hdrs = sub
            body_start = 2

    for row in rows[body_start:]:
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
