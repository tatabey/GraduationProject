#!/usr/bin/env python3
"""
eval_retrieval.py
=================
200 senaryo üzerinde retrieval-only metrik ölçümü.
Verdict accuracy'den bağımsız: YALNIZCA doğru tablonun top-k'da görünüp görünmediğini ölçer.

Metrikler:
    HR@1, HR@3, HR@5  — Hit Rate (doğru tablo top-k'da var mı?)
    MRR               — Mean Reciprocal Rank

Çıktı:
    Terminale tablo + system/data/benchmark/retrieval_eval.txt

Kullanım:
    python3 system/eval_retrieval.py
    python3 system/eval_retrieval.py --kb aastp_test --top-k 5
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.retriever import retrieve
from config import TOP_K, SPLIT_RESULTS, EMBED_MODEL

SCENARIOS_PATH = ROOT / "data" / "test_scenarios.json"  # varsayılan; --scenarios ile geçersiz kılınır
BENCHMARK_DIR  = ROOT / "data" / "benchmark"

# Senaryo "table" etiketi → KB'de aranacak tablo adı prefixleri / page_idx
# Deterministik eşleştirme: "Table 4" → table_name startswith "Table 4"
# "Table 133" → display_name == "Table 133" VEYA table_name startswith "Table_page133" veya page_idx==133
TABLE_MATCHERS = {
    "Table 4"  : lambda m: m["table_name"].startswith("Table 4"),
    "Table 5"  : lambda m: m["table_name"].startswith("Table 5") and not m["table_name"].startswith("Table 5-"),
    "Table 6"  : lambda m: (m["table_name"].startswith("Table 6") and not any(
                    x in m["table_name"] for x in ["6-1", "6-2", "6-3"])),
    "Table T.2": lambda m: "T.2" in m["table_name"],
    "Table 133": lambda m: (
        m.get("display_name", "") == "Table 133"
        or m["table_name"].startswith("Table_page133")
        or (m.get("page_idx") == 133 and m["type"] == "table")
    ),
}


_CHUNK_PAGE_RE = re.compile(r"chunk_p(\d+)_idx")


def _gold_page(label: str) -> int | None:
    """chunk_p{page}_idx{...} etiketinden gold sayfa indeksini çıkarır."""
    m = _CHUNK_PAGE_RE.match(label)
    return int(m.group(1)) if m else None


def _is_hit(match: dict, label: str, match_mode: str = "chunk") -> bool:
    """Hem tablo hem text_chunk senaryolarını destekler.

    - chunk_p* label → text_chunk eşleşmesi:
        * match_mode="chunk" → katı chunk_id eşleşmesi (birincil metrik)
        * match_mode="page"  → getirilen text_chunk gold ile aynı page_idx'te
          ise "doğru bölge" sayılır (chunk sınır farkını isabetten ayırır)
    - Aksi hâlde → tablo eşleşmesi (TABLE_MATCHERS veya table_name prefix)
    """
    if label.startswith("chunk_"):
        if match.get("type") != "text_chunk":
            return False
        if match_mode == "page":
            gp = _gold_page(label)
            return gp is not None and match.get("page_idx") == gp
        return match.get("chunk_id") == label
    if match.get("type") != "table":
        return False
    matcher = TABLE_MATCHERS.get(label)
    if not matcher:
        return match["table_name"].startswith(label)
    return matcher(match)


def _reciprocal_rank(matches: list[dict], label: str, match_mode: str = "chunk") -> float:
    for rank, m in enumerate(matches, start=1):
        if _is_hit(m, label, match_mode):
            return 1.0 / rank
    return 0.0


def run_eval(kb_name: str, fetch_k: int = 5,
             scenarios_path: Path = SCENARIOS_PATH,
             match_mode: str = "chunk") -> dict:
    meta_path  = ROOT / "data" / "kbs" / kb_name / "kb_meta.json"
    meta       = json.loads(meta_path.read_text(encoding="utf-8"))
    chroma_dir = Path(meta["chroma_dir"])
    col_name   = meta["collection"]
    embed_model = meta.get("embed_model", EMBED_MODEL)

    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    n = len(scenarios)

    hr = {1: 0, 3: 0, 5: 0}
    rr_sum = 0.0
    # Gruplandırma: text senaryolarında "section", tablo senaryolarında "table"
    by_table: dict[str, dict] = defaultdict(lambda: {"hr1": 0, "hr3": 0, "hr5": 0, "rr": 0.0, "n": 0})

    print(f"\nKB: {kb_name}  |  {len(scenarios)} senaryo ({scenarios_path.name})  |  fetch_k={fetch_k}")
    print("─" * 70)

    for idx, s in enumerate(scenarios):
        # chunk_id varsa text senaryosu; yoksa tablo senaryosu
        label   = s.get("chunk_id") or s.get("table", "?")
        grp_key = s.get("section") or s.get("table", "?")
        query   = s["text"]

        matches = retrieve(
            query=query,
            chroma_dir=chroma_dir,
            collection_name=col_name,
            top_k=fetch_k,
            embed_model=embed_model,
        )
        # Modalite-ayrık modda isabet, gold'un KENDİ modalite listesi içinde
        # sayılır (tablo senaryosu tablo top-k'sına, text senaryosu text
        # top-k'sına bakar) — diğer modalite zaten ayrı slotlarda sunuluyor.
        if SPLIT_RESULTS:
            gold_type = "text_chunk" if label.startswith("chunk_") else "table"
            matches = [m for m in matches if m.get("type") == gold_type]

        rr = _reciprocal_rank(matches, label, match_mode)
        rr_sum += rr
        by_table[grp_key]["rr"]  += rr
        by_table[grp_key]["n"]   += 1

        for k in (1, 3, 5):
            hit = any(_is_hit(m, label, match_mode) for m in matches[:k])
            if hit:
                hr[k] += 1
            by_table[grp_key][f"hr{k}"] += int(hit)

        bar_done = int((idx + 1) / n * 40)
        bar = "█" * bar_done + "░" * (40 - bar_done)
        print(f"\r  [{bar}] {idx+1:3d}/{n}  MRR={rr_sum/(idx+1):.3f}", end="", flush=True)

    print()

    result = {
        "hr1" : hr[1] / n,
        "hr3" : hr[3] / n,
        "hr5" : hr[5] / n,
        "mrr" : rr_sum / n,
        "n"   : n,
        "match_mode": match_mode,
        "by_table": {
            lbl: {
                "hr1": d["hr1"] / d["n"],
                "hr3": d["hr3"] / d["n"],
                "hr5": d["hr5"] / d["n"],
                "mrr": d["rr"]  / d["n"],
                "n"  : d["n"],
            }
            for lbl, d in by_table.items()
        },
    }
    return result


def print_report(result: dict, tag: str = "") -> str:
    SEP = "═" * 72
    n = result["n"]
    mode = result.get("match_mode", "chunk")
    mode_str = "" if mode == "chunk" else f" · eşleşme={mode}"
    tag_str = f" [{tag}]" if tag else ""
    lines = [
        "",
        SEP,
        f"  RETRIEVAL DEĞERLENDİRMESİ — AASTP-1 / {n} Senaryo{tag_str}{mode_str}",
        SEP,
        f"  {'Metrik':<12} {'Değer':>8}   {'Hedef':>8}   {'Durum':>8}",
        f"  {'─'*12} {'─'*8}   {'─'*8}   {'─'*8}",
        f"  {'HR@1':<12} {result['hr1']:>7.1%}   {'—':>8}",
        f"  {'HR@3':<12} {result['hr3']:>7.1%}   {'≥ 90%':>8}   {'✅' if result['hr3'] >= 0.90 else '❌'}",
        f"  {'HR@5':<12} {result['hr5']:>7.1%}   {'—':>8}",
        f"  {'MRR':<12} {result['mrr']:>7.3f}   {'—':>8}",
        "",
        f"  Grup/Tablo Bazında (HR@3):",
        f"  {'Tablo':<14} {'HR@1':>6} {'HR@3':>6} {'HR@5':>6} {'MRR':>7} {'n':>4}",
        f"  {'─'*14} {'─'*6} {'─'*6} {'─'*6} {'─'*7} {'─'*4}",
    ]
    for lbl, d in sorted(result["by_table"].items()):
        status = "✅" if d["hr3"] >= 0.90 else "❌"
        lines.append(
            f"  {lbl:<14} {d['hr1']:>5.1%} {d['hr3']:>6.1%} {d['hr5']:>6.1%} "
            f"{d['mrr']:>6.3f} {d['n']:>4}  {status}"
        )
    lines.append(SEP)
    lines.append("")
    report = "\n".join(lines)
    print(report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb",        default="aastp_test")
    parser.add_argument("--top-k",     type=int, default=5)
    parser.add_argument("--scenarios", type=Path, default=None,
                        help="Test senaryoları JSON dosyası (varsayılan: data/test_scenarios.json)")
    parser.add_argument("--tag",       type=str, default=None,
                        help="Çıktı dosyası öneki, ör. set1/set2/set3")
    parser.add_argument("--match",     choices=["chunk", "page"], default="chunk",
                        help="text senaryolarında isabet ölçütü: katı chunk_id "
                             "(birincil) veya sayfa-düzeyi (doğru bölge)")
    args = parser.parse_args()

    scenarios_path = args.scenarios if args.scenarios else SCENARIOS_PATH
    if args.tag:
        run_tag = args.tag
    else:
        stem = Path(scenarios_path).stem
        run_tag = stem.replace("test_scenarios", "").strip("_") or "set1"

    result = run_eval(args.kb, fetch_k=args.top_k, scenarios_path=scenarios_path,
                      match_mode=args.match)
    report = print_report(result, tag=run_tag)

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "" if args.match == "chunk" else f"_{args.match}"
    out = BENCHMARK_DIR / f"{run_tag}_retrieval_eval{suffix}.txt"
    out.write_text(report, encoding="utf-8")
    print(f"  Rapor kaydedildi: {out.relative_to(ROOT.parent)}")


if __name__ == "__main__":
    main()
