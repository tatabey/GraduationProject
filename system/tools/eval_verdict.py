"""
200-Scenario Evaluation Script
================================
Denetim sonuçlarını beklenen verdictlerle karşılaştırır.

Kullanım:
    python3 system/eval_200.py --results system/data/results_200.json

results_200.json formatı (audit_items() çıktısı gibi):
    [{"item_no": 1, "verdict": "UYGUN", ...}, ...]
"""

import json
import argparse
from pathlib import Path
from collections import defaultdict

SCENARIOS = json.loads(
    (Path(__file__).parent.parent / "data" / "test_scenarios.json").read_text()
)
EXPECTED = {s["item_no"]: s for s in SCENARIOS}
VERDICTS = ["UYGUN", "UYGUN DEĞİL"]


def evaluate(results: list[dict]) -> dict:
    correct = wrong = skipped = 0
    by_table = defaultdict(lambda: {"correct": 0, "wrong": 0, "total": 0})
    by_verdict = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    errors = []

    for r in results:
        no = r["item_no"]
        exp = EXPECTED.get(no)
        if not exp:
            skipped += 1
            continue
        predicted = r.get("verdict", "")
        expected  = exp["expected"]
        table     = exp["table"]

        by_table[table]["total"] += 1

        if predicted == expected:
            correct += 1
            by_table[table]["correct"] += 1
            by_verdict[expected]["tp"] += 1
        else:
            wrong += 1
            by_table[table]["wrong"] += 1
            by_verdict[expected]["fn"] += 1
            by_verdict[predicted]["fp"] += 1
            errors.append({
                "item_no": no,
                "table": table,
                "expected": expected,
                "predicted": predicted,
                "text": exp["text"][:80] + "...",
            })

    total = correct + wrong
    accuracy = correct / total * 100 if total else 0

    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "skipped": skipped,
        "accuracy": accuracy,
        "by_table": dict(by_table),
        "errors": errors,
    }


def print_report(ev: dict):
    print("\n" + "═" * 60)
    print("  AASTP-1 Test — 200 Senaryo Değerlendirmesi")
    print("═" * 60)
    print(f"  Toplam  : {ev['total']}")
    print(f"  Doğru   : {ev['correct']}  ({ev['accuracy']:.1f}%)")
    print(f"  Yanlış  : {ev['wrong']}")
    if ev['skipped']:
        print(f"  Atlandı : {ev['skipped']}")
    print()

    print("  Tablo bazında doğruluk:")
    for tbl, d in sorted(ev["by_table"].items()):
        pct = d["correct"] / d["total"] * 100 if d["total"] else 0
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"    {tbl:<12} [{bar}] {pct:5.1f}%  ({d['correct']}/{d['total']})")

    if ev["errors"]:
        print(f"\n  İlk 10 hata:")
        for e in ev["errors"][:10]:
            print(f"    #{e['item_no']:03d} [{e['table']}]")
            print(f"         Beklenen  : {e['expected']}")
            print(f"         Tahmin    : {e['predicted']}")
            print(f"         Metin     : {e['text']}")
    print("═" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True, help="Denetim sonuçları JSON dosyası")
    args = parser.parse_args()

    results = json.loads(Path(args.results).read_text())
    ev = evaluate(results)
    print_report(ev)

    # Özet JSON kaydet
    out = Path(args.results).with_suffix(".eval.json")
    out.write_text(json.dumps(ev, ensure_ascii=False, indent=2))
    print(f"\n  Ayrıntılı rapor: {out}")
