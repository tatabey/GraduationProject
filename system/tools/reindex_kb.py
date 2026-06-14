#!/usr/bin/env python3
"""
reindex_kb.py
=============
Mevcut bir KB'yi (semantic_units + merged MinerU JSON) **deterministik** olarak
yeniden indeksler. MinerU ve LLM ÇAĞIRMAZ — sıfır token, sıfır API.

Ne yapar:
    1. semantic_units.json'dan tabloları yükler (yeniden çıkarma yok).
    2. merged_content_list.json'dan text chunk'ları YENİDEN üretir
       (güncellenmiş text_chunker: boilerplate filtresi + eşik).
    3. Temizlenmiş text_chunks.json'u diske yazar.
    4. reindex_from_units ile ChromaDB'yi sıfırdan kurar
       (kb_builder._index_chunks: section_path bağlamı embed'e dahil).

Kullanım:
    python3 system/tools/reindex_kb.py --kb aastp_test
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.text_chunker import chunk_text_blocks, save_text_chunks
from pipeline.kb_builder import reindex_from_units
from tools.check_gold_ids import check_gold_ids
from config import EMBED_MODEL


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kb", default="aastp_test", help="KB klasör adı (data/kbs altında)")
    parser.add_argument("--embed-model", default=None,
                        help="Embedding modeli (varsayılan: kb_meta'daki ya da config EMBED_MODEL)")
    parser.add_argument("--scenarios", type=Path, default=None,
                        help="Gold chunk_id kontrolü için senaryo dosyası (varsayılan: AASTP text)")
    args = parser.parse_args()

    kb_dir = ROOT / "data" / "kbs" / args.kb
    if not kb_dir.exists():
        sys.exit(f"❌ KB bulunamadı: {kb_dir}")

    units_path  = kb_dir / "semantic_units" / "semantic_units.json"
    merged_path = kb_dir / "merged_content_list.json"
    text_dir    = kb_dir / "text_chunks"
    chroma_dir  = kb_dir / "chroma_db"
    meta_path   = kb_dir / "kb_meta.json"

    for p in (units_path, merged_path):
        if not p.exists():
            sys.exit(f"❌ Gerekli dosya yok: {p}")

    meta     = json.loads(meta_path.read_text(encoding="utf-8"))
    col_name = meta["collection"]
    embed_model = args.embed_model or meta.get("embed_model") or EMBED_MODEL

    print(f"\n🔄 KB yeniden indeksleniyor: {args.kb}  (koleksiyon: {col_name})")
    print(f"   embedding: {embed_model}")
    print("─" * 64)

    # 1) Tablolar (deterministik, değişmez)
    units = json.loads(units_path.read_text(encoding="utf-8"))
    print(f"  ✔ {len(units)} tablo yüklendi (semantic_units.json)")

    # 2) Text chunk'ları yeniden üret (temizlenmiş chunker)
    chunks = chunk_text_blocks(merged_path)
    print(f"  ✔ {len(chunks)} text chunk üretildi (boilerplate filtresi sonrası)")

    # Güvenlik kapısı: gold chunk_id'ler kaybolduysa indeksleme iptal —
    # test seti geçersizleşmeden önce chunker değişikliğini düzelt.
    missing = check_gold_ids(chunks, args.scenarios) if args.scenarios else check_gold_ids(chunks)
    if missing:
        print(f"  ❌ {len(missing)} gold chunk_id yeni chunk'larda yok, reindex iptal:")
        for cid in missing[:10]:
            print(f"     {cid}")
        sys.exit(1)
    print("  ✔ Gold chunk_id kontrolü geçti.")

    save_text_chunks(chunks, text_dir)

    # Sentetik sorular mevcutsa chunk'lara iliştir (CHUNK_SYNTH_QUERIES > 0
    # ise kb_builder ek vektör olarak indeksler; üretim: tools/enrich_chunks.py)
    synth_path = text_dir / "synth_queries.json"
    if synth_path.exists():
        synth = json.loads(synth_path.read_text(encoding="utf-8"))
        n_att = 0
        for c in chunks:
            qs = synth.get(c["chunk_id"]) or []
            if qs:
                c["synth_queries"] = qs
                n_att += 1
        print(f"  ✔ {n_att} chunk'a sentetik soru iliştirildi (synth_queries.json)")

    # 3) ChromaDB'yi sıfırdan kur
    print("  ⏳ ChromaDB indeksleniyor...")
    idx = reindex_from_units(units, chunks, chroma_dir, col_name, embed_model=embed_model)

    # 4) kb_meta güncelle
    meta["tables"] = idx["tables"]
    meta["chunks"] = idx["chunks"]
    meta["total"]  = idx["total"]
    meta["embed_model"] = embed_model
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    print("─" * 64)
    print(f"✅ Tamamlandı: {idx['tables']} tablo + {idx['chunks']} chunk = {idx['total']} döküman")


if __name__ == "__main__":
    main()
