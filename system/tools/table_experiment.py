#!/usr/bin/env python3
"""
table_experiment.py
===================
mineru_chunks/ içindeki 45 ham tablo üzerinde 6 serileştirme metodunu karşılaştırır.
Her metod için SADECE semantik arama (cross-encoder kapalı) ile HR@1/3/5 ve MRR ölçer.
En iyi semantik metod için ayrıca cross-encoder versiyonu da çalıştırır.

Kaldırılabilir yardımcı script — ana pipeline'ı değiştirmez.

Kullanım:
    python3 system/table_experiment.py
    python3 system/table_experiment.py --top-k 5 --methods A B C D E F
"""

import argparse
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MINERU_DIR    = ROOT / "data" / "kbs" / "aastp_test" / "mineru_chunks"
SCENARIOS_PATH = ROOT / "data" / "test_scenarios.json"
RESULTS_DIR   = ROOT / "data" / "benchmark"
EMBED_MODEL   = "BAAI/bge-large-en-v1.5"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

CHUNK_OFFSETS = {
    "pages_001-050_content_list.json": 0,
    "pages_051-100_content_list.json": 50,
    "pages_101-150_content_list.json": 100,
    "pages_151-200_content_list.json": 150,
    "pages_201-207_content_list.json": 200,
}

# abs_page → scenario "table" label eşlemesi
PAGE_TO_LABEL: dict[int, str] = {
    27: "Table 4",
    28: "Table 5",
    29: "Table 6",
    133: "Table 133",
    148: "Table T.2",
}
TARGET_LABELS = set(PAGE_TO_LABEL.values())


# ---------------------------------------------------------------------------
# HTML yardımcıları
# ---------------------------------------------------------------------------

class _StripParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []
    def handle_data(self, data):
        d = data.strip()
        if d:
            self._parts.append(d)
    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(html: str) -> str:
    p = _StripParser()
    p.feed(html)
    return p.get_text()


def parse_rows(html: str) -> list[list[str]]:
    """HTML tablosunu 2D liste (hücreler) olarak döndürür."""
    class RowParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.rows: list[list[str]] = []
            self._row: list[str] | None = None
            self._buf: str | None = None
        def handle_starttag(self, tag, attrs):
            if tag == "tr": self._row = []
            elif tag in ("td","th") and self._row is not None: self._buf = ""
        def handle_endtag(self, tag):
            if tag == "tr" and self._row is not None:
                self.rows.append(self._row); self._row = None
            elif tag in ("td","th") and self._buf is not None:
                if self._row is not None: self._row.append(self._buf.strip())
                self._buf = None
        def handle_data(self, data):
            if self._buf is not None: self._buf += data
    p = RowParser(); p.feed(html)
    return [r for r in p.rows if any(c.strip() for c in r)]


# ---------------------------------------------------------------------------
# Veri yükleme
# ---------------------------------------------------------------------------

def load_mineru_tables() -> list[dict]:
    """45 ham tabloyu abs_page ile yükle."""
    tables = []
    for fname in sorted(os.listdir(MINERU_DIR)):
        if not fname.endswith(".json"):
            continue
        offset = CHUNK_OFFSETS.get(fname, 0)
        data   = json.loads((MINERU_DIR / fname).read_text(encoding="utf-8"))
        for item in data:
            if item.get("type") != "table":
                continue
            t = {
                "abs_page"  : offset + item.get("page_idx", 0),
                "caption"   : " ".join(item.get("table_caption") or []).strip(),
                "body_html" : item.get("table_body", ""),
                "footnotes" : item.get("table_footnote") or [],
                "img_path"  : item.get("img_path", ""),
                "_chunk"    : fname,
            }
            t["label"] = PAGE_TO_LABEL.get(t["abs_page"], "")
            t["display"] = t["caption"] if t["caption"] else f"Table (p.{t['abs_page']})"
            tables.append(t)
    return tables


# ---------------------------------------------------------------------------
# Serileştirme metodları
# ---------------------------------------------------------------------------

def _cap(t: dict) -> str:
    return t["caption"] if t["caption"] else f"Table (p.{t['abs_page']})"


def serialize_A_caption_only(t: dict) -> str:
    return _cap(t)


def serialize_B_caption_plus_headers(t: dict) -> str:
    rows = parse_rows(t["body_html"])
    header_text = " | ".join(rows[0]) if rows else ""
    return _cap(t) + ("\n" + header_text if header_text else "")


def serialize_C_html_stripped(t: dict) -> str:
    return _cap(t) + "\n" + strip_html(t["body_html"])


def serialize_D_caption_first3rows(t: dict) -> str:
    rows = parse_rows(t["body_html"])
    lines = [_cap(t)]
    for row in rows[:4]:  # header + first 3 data rows
        lines.append(" | ".join(row))
    return "\n".join(lines)


def serialize_E_current_serializer(t: dict) -> str:
    """
    Mevcut table_serializer.py mantığı: semantik unit formatına çevir,
    ardından serialize_table() çağır.
    """
    sys.path.insert(0, str(ROOT))
    from pipeline.table_serializer import serialize_table, table_display_name

    # SemanticUnit formatına uy
    unit = {
        "table_name"  : t["caption"] if t["caption"] else f"Table_page{t['abs_page']}",
        "html"        : t["body_html"],
        "footnotes"   : t["footnotes"],
        "notes"       : [],
        "legend"      : "",
        "hierarchy"   : {},
        "page_idx"    : t["abs_page"],
    }
    return serialize_table(unit)


def serialize_F_full_text_stripped(t: dict) -> str:
    """Başlık + tam stripped HTML (uzun olabilir)."""
    return _cap(t) + "\n" + strip_html(t["body_html"])


METHODS = {
    "A": ("caption_only",         serialize_A_caption_only),
    "B": ("caption_plus_headers", serialize_B_caption_plus_headers),
    "C": ("html_stripped",        serialize_C_html_stripped),
    "D": ("caption_first3rows",   serialize_D_caption_first3rows),
    "E": ("current_serializer",   serialize_E_current_serializer),
    "F": ("full_text_stripped",   serialize_F_full_text_stripped),
}


# ---------------------------------------------------------------------------
# ChromaDB yardımcıları
# ---------------------------------------------------------------------------

def build_collection(tables: list[dict], serialize_fn, tmpdir: str):
    import chromadb
    from chromadb.utils import embedding_functions

    chroma = chromadb.PersistentClient(path=tmpdir)
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL
    )
    col = chroma.create_collection(name="exp", embedding_function=emb_fn)

    ids, docs, metas = [], [], []
    for i, t in enumerate(tables):
        doc = serialize_fn(t)
        ids.append(f"tbl_{i}")
        docs.append(doc)
        metas.append({
            "abs_page": t["abs_page"],
            "label"   : t["label"],
            "display" : t["display"],
            "doc_text": doc[:300],
        })

    col.add(ids=ids, documents=docs, metadatas=metas)
    return col


def retrieve_top_k(col, query: str, k: int) -> list[dict]:
    results = col.query(query_texts=[query], n_results=min(k, col.count()))
    out = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        out.append({"abs_page": meta["abs_page"], "label": meta["label"],
                    "display": meta["display"], "distance": dist, "doc_text": meta["doc_text"]})
    return out


# ---------------------------------------------------------------------------
# Değerlendirme
# ---------------------------------------------------------------------------

def evaluate_method(col, scenarios: list[dict], top_k: int) -> dict:
    hr = {1: 0, 3: 0, 5: 0}
    rr_sum = 0.0
    by_label: dict[str, dict] = defaultdict(lambda: {"hr1":0,"hr3":0,"hr5":0,"rr":0.0,"n":0})
    n = len(scenarios)

    for s in scenarios:
        target_label = s["table"]
        query        = s["text"]

        matches = retrieve_top_k(col, query, k=max(5, top_k))

        rr = 0.0
        for rank, m in enumerate(matches, 1):
            if m["label"] == target_label:
                rr = 1.0 / rank
                break
        rr_sum += rr

        by_label[target_label]["n"]  += 1
        by_label[target_label]["rr"] += rr

        for k in (1, 3, 5):
            hit = any(m["label"] == target_label for m in matches[:k])
            if hit:
                hr[k] += 1
            by_label[target_label][f"hr{k}"] += int(hit)

    return {
        "hr1"     : hr[1] / n,
        "hr3"     : hr[3] / n,
        "hr5"     : hr[5] / n,
        "mrr"     : rr_sum / n,
        "n"       : n,
        "by_label": {
            lbl: {k: d[k]/d["n"] if k != "n" else d["n"]
                  for k in ("hr1","hr3","hr5","rr","n")}
            for lbl, d in by_label.items()
        },
    }


# ---------------------------------------------------------------------------
# Rapor
# ---------------------------------------------------------------------------

def print_report(all_results: list[tuple[str,str,dict]]):
    SEP = "═" * 100
    labels = sorted(TARGET_LABELS)
    col_w  = 10

    # Sütun başlıkları (tam isim)
    short = {"Table 133":"T133", "Table 4":"T4", "Table 5":"T5", "Table 6":"T6", "Table T.2":"T.2"}
    header_lbl = "".join(f"{short[l]:>{col_w}}" for l in labels)

    lines = [
        "", SEP,
        "  TABLO SERİLEŞTİRME METODU KARŞILAŞTIRMASI — 200 senaryo",
        "  (pure semantic, 45 tablo, cross-encoder kapalı)",
        SEP,
        f"  {'Metod':<30} {'HR@1':>6} {'HR@3':>6} {'HR@5':>6} {'MRR':>7}   {'T133':>{col_w}} {'T4':>{col_w}} {'T5':>{col_w}} {'T6':>{col_w}} {'T.2':>{col_w}}",
        f"  {'─'*30} {'─'*6} {'─'*6} {'─'*6} {'─'*7}   {'─'*(col_w)} {'─'*(col_w)} {'─'*(col_w)} {'─'*(col_w)} {'─'*(col_w)}",
    ]
    for key, name, res in all_results:
        per_tbl = ""
        for lbl in labels:
            d   = res["by_label"].get(lbl, {})
            hr3 = d.get("hr3", 0) * 100
            per_tbl += f"{hr3:>{col_w}.1f}%"
        lines.append(
            f"  {key}: {name:<26} {res['hr1']:>5.1%} {res['hr3']:>6.1%} "
            f"{res['hr5']:>6.1%} {res['mrr']:>6.3f}   {per_tbl}"
        )

    # En iyi HR@3 satırını işaretle
    best_hr3 = max(res["hr3"] for _, _, res in all_results)
    lines.append(f"  {'─'*30}{'─'*30}")
    lines.append(f"  En iyi genel HR@3: {best_hr3:.1%}")
    lines.append(SEP)
    report = "\n".join(lines)
    print(report)
    return report


# ---------------------------------------------------------------------------
# Ana
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k",  type=int, default=5)
    parser.add_argument("--methods", nargs="+", default=list(METHODS.keys()),
                        choices=list(METHODS.keys()))
    args = parser.parse_args()

    tables    = load_mineru_tables()
    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))
    print(f"\n✔ {len(tables)} tablo yüklendi (mineru_chunks)")
    print(f"✔ {len(scenarios)} test senaryosu")
    print(f"✔ Hedef tablolar: {', '.join(sorted(TARGET_LABELS))}\n")

    all_results: list[tuple[str,str,dict]] = []

    for key in args.methods:
        name, fn = METHODS[key]
        print(f"── Metod {key}: {name} {'─'*40}")
        with tempfile.TemporaryDirectory() as tmpdir:
            print(f"   Vektörleştiriliyor...", end=" ", flush=True)
            col = build_collection(tables, fn, tmpdir)
            print(f"✔ {col.count()} döküman")
            print(f"   Değerlendiriliyor ({len(scenarios)} sorgu)...", end=" ", flush=True)
            res = evaluate_method(col, scenarios, args.top_k)
            print(f"✔  HR@3={res['hr3']:.1%}  MRR={res['mrr']:.3f}")
        all_results.append((key, name, res))

    report = print_report(all_results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RESULTS_DIR / "table_experiment_results.txt"
    out_path.write_text(report, encoding="utf-8")
    print(f"\n  Rapor kaydedildi: {out_path.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
