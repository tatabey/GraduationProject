#!/usr/bin/env python3
"""
compare_verdict_runs.py
=======================
İki verdict koşusunu ortak item_no'lar üzerinden birebir karşılaştırır
(ör. eski 138'lik gpt-oss-120b koşusu vs yeni 6-doküman split koşusu).

Kullanım:
    python3 system/tools/compare_verdict_runs.py \
        --old data/benchmark/gpt-oss-120b_results.json \
        --new data/benchmark/split6doc_gpt-oss-120b_results.json
"""

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _acc(results: list[dict], keys: set[int] | None = None) -> tuple[int, int]:
    ok = n = 0
    for r in results:
        if keys is not None and r["item_no"] not in keys:
            continue
        if r.get("verdict") not in ("UYGUN", "UYGUN DEĞİL"):
            continue  # DEĞERLENDİRİLEMEDİ metriğe girmez
        n += 1
        if r["verdict"] == r.get("expected"):
            ok += 1
    return ok, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", type=Path, required=True)
    ap.add_argument("--new", type=Path, required=True)
    args = ap.parse_args()

    old = json.loads((ROOT / args.old).read_text() if not args.old.is_absolute()
                     else args.old.read_text())
    new = json.loads((ROOT / args.new).read_text() if not args.new.is_absolute()
                     else args.new.read_text())

    old_ids = {r["item_no"] for r in old}
    new_ids = {r["item_no"] for r in new}
    common  = old_ids & new_ids

    o_ok, o_n = _acc(old, common)
    n_ok, n_n = _acc(new, common)
    a_ok, a_n = _acc(new)

    print(f"Ortak madde: {len(common)}")
    print(f"  ESKİ  (ortak {o_n}): {o_ok}/{o_n} = {o_ok/o_n:.1%}")
    print(f"  YENİ  (ortak {n_n}): {n_ok}/{n_n} = {n_ok/n_n:.1%}")
    print(f"  YENİ  (tümü  {a_n}): {a_ok}/{a_n} = {a_ok/a_n:.1%}")

    # Madde bazında değişimler
    om = {r["item_no"]: r for r in old}
    nm = {r["item_no"]: r for r in new}
    fixed, broke = [], []
    for no in sorted(common):
        o, nw = om[no], nm[no]
        o_hit = o.get("verdict") == o.get("expected")
        n_hit = nw.get("verdict") == nw.get("expected")
        if not o_hit and n_hit:
            fixed.append(no)
        elif o_hit and not n_hit:
            broke.append(no)
    print(f"\n  Düzelen maddeler ({len(fixed)}): {fixed[:15]}")
    print(f"  Bozulan maddeler ({len(broke)}): {broke[:15]}")


if __name__ == "__main__":
    main()
