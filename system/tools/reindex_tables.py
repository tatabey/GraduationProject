#!/usr/bin/env python3
"""
reindex_tables.py
=================
Mevcut semantic_units.json + text_chunks.json'dan ChromaDB'yi sıfırdan kurar.
MinerU veya Ollama gerektirmez — deterministik, hızlı (saniyeler).

Kullanım:
    python3 system/reindex_tables.py                    # varsayılan KB: aastp_test
    python3 system/reindex_tables.py --kb aastp_test
    python3 system/reindex_tables.py --kb benim_kb
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.kb_builder import reindex_from_units


def main():
    parser = argparse.ArgumentParser(description="Deterministik ChromaDB yeniden indeksleme")
    parser.add_argument("--kb", default="aastp_test", help="KB adı (data/kbs/ altındaki klasör)")
    args = parser.parse_args()

    kb_dir     = ROOT / "data" / "kbs" / args.kb
    meta_path  = kb_dir / "kb_meta.json"
    units_path = kb_dir / "semantic_units" / "semantic_units.json"
    chunks_path= kb_dir / "text_chunks"    / "text_chunks.json"

    if not meta_path.exists():
        print(f"[HATA] KB meta dosyası bulunamadı: {meta_path}")
        sys.exit(1)

    meta       = json.loads(meta_path.read_text(encoding="utf-8"))
    col_name   = meta["collection"]
    chroma_dir = Path(meta["chroma_dir"])

    print(f"\nKB        : {args.kb}")
    print(f"Collection: {col_name}")
    print(f"ChromaDB  : {chroma_dir}")

    if not units_path.exists():
        print(f"[HATA] semantic_units.json bulunamadı: {units_path}")
        sys.exit(1)
    if not chunks_path.exists():
        print(f"[HATA] text_chunks.json bulunamadı: {chunks_path}")
        sys.exit(1)

    units  = json.loads(units_path.read_text(encoding="utf-8"))
    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    print(f"\nYüklendi  : {len(units)} tablo + {len(chunks)} chunk")

    result = reindex_from_units(units, chunks, chroma_dir, col_name)

    # kb_meta.json güncelle
    meta["tables"] = result["tables"]
    meta["chunks"] = result["chunks"]
    meta["total"]  = result["total"]
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"kb_meta.json güncellendi.")
    print(f"\n✅ {result['tables']} tablo + {result['chunks']} chunk = {result['total']} döküman")


if __name__ == "__main__":
    main()
