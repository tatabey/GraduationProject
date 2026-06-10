#!/usr/bin/env python3
"""
check_gold_ids.py
=================
Chunker değişikliklerinden sonra, text test setindeki gold chunk_id'lerin
yeni üretilen text_chunks.json'da hâlâ var olduğunu doğrular.

chunk_id'ler merged JSON'daki blok indeksine bağlıdır; bir chunker değişikliği
blokları kaydırırsa veya gold chunk tamamen boilerplate sayılıp düşerse
200 senaryoluk test seti geçersizleşir. Bu araç reindex ÖNCESİ kapıdır.

Kullanım:
    python3 system/tools/check_gold_ids.py --kb aastp_test
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_SCENARIOS = ROOT / "data" / "test_scenarios_text.json"


def check_gold_ids(
    chunks: list[dict],
    scenarios_path: Path = DEFAULT_SCENARIOS,
) -> list[str]:
    """Eksik gold chunk_id listesini döndürür (boş liste = sorun yok)."""
    if not scenarios_path.exists():
        return []
    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    gold = {s["chunk_id"] for s in scenarios if s.get("chunk_id")}
    have = {c["chunk_id"] for c in chunks}
    return sorted(gold - have)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default="aastp_test")
    ap.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    args = ap.parse_args()

    chunks_path = ROOT / "data" / "kbs" / args.kb / "text_chunks" / "text_chunks.json"
    if not chunks_path.exists():
        sys.exit(f"❌ Bulunamadı: {chunks_path}")

    chunks  = json.loads(chunks_path.read_text(encoding="utf-8"))
    missing = check_gold_ids(chunks, args.scenarios)

    if missing:
        print(f"❌ {len(missing)} gold chunk_id kayıp:")
        for cid in missing[:20]:
            print(f"   {cid}")
        if len(missing) > 20:
            print(f"   ... ve {len(missing) - 20} tane daha")
        sys.exit(1)
    print(f"✅ Tüm gold chunk_id'ler mevcut ({chunks_path.name}, {len(chunks)} chunk).")


if __name__ == "__main__":
    main()
