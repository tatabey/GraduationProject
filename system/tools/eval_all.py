#!/usr/bin/env python3
"""
eval_all.py — Birleşik retrieval eval (guardrail)
==================================================
Tek komutta 5 ölçüm:
    set1, set2, set3          (tablo senaryoları, 150'şer)
    text_chunk                (200 text senaryosu, katı chunk_id eşleşmesi)
    text_page                 (aynı 200 senaryo, sayfa-düzeyi eşleşme)

Her retrieval değişikliğinden sonra çalıştırılır; --baseline verilirse
set1/set2/set3 HR@3 baseline altına düştüğünde nonzero exit ile uyarır
(tablo regresyonu = otomatik red).

Kullanım:
    python3 system/tools/eval_all.py --tag baseline
    python3 system/tools/eval_all.py --tag faz1 \
        --baseline system/data/benchmark/eval_all_baseline.json
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from eval_retrieval import run_eval  # noqa: E402

DATA_DIR      = ROOT / "data"
BENCHMARK_DIR = DATA_DIR / "benchmark"

# (ad, senaryo dosyası, match_mode)
RUNS = [
    ("set1",       DATA_DIR / "test_scenarios.json",      "chunk"),
    ("set2",       DATA_DIR / "test_scenarios_set2.json", "chunk"),
    ("set3",       DATA_DIR / "test_scenarios_set3.json", "chunk"),
    ("text_chunk", DATA_DIR / "test_scenarios_text.json", "chunk"),
    ("text_page",  DATA_DIR / "test_scenarios_text.json", "page"),
]

# Tablo guardrail: bu setlerde HR@3 baseline altına düşemez
GUARD_SETS = ["set1", "set2", "set3"]
EPS = 1e-9


def _summary(results: dict[str, dict]) -> str:
    lines = [
        "",
        "═" * 64,
        "  BİRLEŞİK EVAL ÖZETİ",
        "═" * 64,
        f"  {'Set':<12} {'HR@1':>7} {'HR@3':>7} {'HR@5':>7} {'MRR':>7} {'n':>5}",
        f"  {'─'*12} {'─'*7} {'─'*7} {'─'*7} {'─'*7} {'─'*5}",
    ]
    for name, r in results.items():
        lines.append(
            f"  {name:<12} {r['hr1']:>6.1%} {r['hr3']:>6.1%} "
            f"{r['hr5']:>6.1%} {r['mrr']:>7.3f} {r['n']:>5}"
        )
    lines.append("═" * 64)
    return "\n".join(lines)


def _check_baseline(results: dict[str, dict], baseline_path: Path,
                    tolerance: float = 0.0) -> bool:
    base = json.loads(baseline_path.read_text(encoding="utf-8"))["results"]
    ok = True
    tol_str = f" (tolerans: {tolerance:.0%})" if tolerance else ""
    print(f"\n  GUARDRAIL — tablo setleri baseline karşılaştırması{tol_str}:")
    for name in GUARD_SETS:
        b, c = base[name]["hr3"], results[name]["hr3"]
        status = "✅" if c + tolerance + EPS >= b else "❌ REGRESYON"
        print(f"    {name}: HR@3 {b:.1%} → {c:.1%}  {status}")
        if c + tolerance + EPS < b:
            ok = False
    # Text bilgilendirme (gate değil, bilgi amaçlı)
    for name in ("text_chunk", "text_page"):
        if name in base and name in results:
            b, c = base[name]["hr3"], results[name]["hr3"]
            arrow = "⬆️" if c > b + EPS else ("⬇️" if c + EPS < b else "→")
            print(f"    {name}: HR@3 {b:.1%} → {c:.1%}  {arrow}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb",       default="aastp_test")
    ap.add_argument("--top-k",    type=int, default=5)
    ap.add_argument("--tag",      default=time.strftime("%Y%m%d_%H%M"))
    ap.add_argument("--baseline", type=Path, default=None,
                    help="Karşılaştırılacak eval_all_*.json; set1/2/3 HR@3 "
                         "düşerse exit 1")
    ap.add_argument("--tolerance", type=float, default=0.0,
                    help="Tablo setlerinde kabul edilebilir HR@3 düşüşü "
                         "(ör. 0.02 = 2 puan). Asıl hedef text ≥ 0.75.")
    args = ap.parse_args()

    results: dict[str, dict] = {}
    t0 = time.time()
    for name, path, mode in RUNS:
        print(f"\n=== {name}  ({path.name}, match={mode}) ===")
        results[name] = run_eval(
            args.kb, fetch_k=args.top_k, scenarios_path=path, match_mode=mode
        )

    print(_summary(results))
    print(f"  Toplam süre: {time.time() - t0:.0f} sn")

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    out = BENCHMARK_DIR / f"eval_all_{args.tag}.json"
    out.write_text(
        json.dumps(
            {
                "tag"      : args.tag,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "kb"       : args.kb,
                "top_k"    : args.top_k,
                "results"  : results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"  Snapshot: {out.relative_to(ROOT.parent)}")

    if args.baseline:
        if not _check_baseline(results, args.baseline, args.tolerance):
            print("\n  ❌ Tablo guardrail İHLAL — değişiklik revert edilmeli.")
            sys.exit(1)
        print("\n  ✅ Guardrail geçti.")


if __name__ == "__main__":
    main()
