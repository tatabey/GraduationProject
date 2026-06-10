#!/usr/bin/env python3
"""
remap_gold_ids.py
=================
Chunker iyileştirmesi (sahte sayfa-başlığı heading'lerinin bastırılması) bazı
chunk'ları önceki bölümle birleştirir. Bu durumda eski gold chunk_id kaybolur
ama GOLD PASAJ aynen yeni (host) chunk'ın içindedir.

Bu araç, test setindeki kayıp gold chunk_id'leri içerik-doğrulamalı olarak
host chunk'a remap eder:
    1. Eski chunk'ın içeriğinden bir kanıt satırı (probe) alınır.
    2. start_idx'i kapsayan yeni host chunk bulunur.
    3. Probe host içeriğinde birebir varsa remap yapılır; yoksa İPTAL.

Test seti anlamı değişmez — aynı pasaj, yeni chunk sınırı. (Tez notu: etiket
remapleri burada loglanır.)

Kullanım:
    python3 system/tools/remap_gold_ids.py --kb aastp_test [--dry-run]
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.text_chunker import chunk_text_blocks  # noqa: E402

SCENARIOS_PATH = ROOT / "data" / "test_scenarios_text.json"
_IDX_RE = re.compile(r"idx(\d+)$")


def _start_idx(chunk_id: str) -> int:
    m = _IDX_RE.search(chunk_id)
    return int(m.group(1)) if m else -1


def _probe_lines(content: str) -> list[str]:
    """İçerikten kanıt satırları: ≥20 karakterlik anlamlı satırlar."""
    return [ln.strip() for ln in content.splitlines() if len(ln.strip()) >= 20]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default="aastp_test")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    kb_dir    = ROOT / "data" / "kbs" / args.kb
    old_path  = kb_dir / "text_chunks" / "text_chunks.json"
    merged    = kb_dir / "merged_content_list.json"

    old_chunks = {c["chunk_id"]: c for c in json.loads(old_path.read_text(encoding="utf-8"))}
    new_chunks = chunk_text_blocks(merged)
    new_ids    = {c["chunk_id"] for c in new_chunks}
    new_sorted = sorted(new_chunks, key=lambda c: _start_idx(c["chunk_id"]))

    scenarios = json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))

    remaps: dict[str, str] = {}
    failures: list[str] = []
    for s in scenarios:
        gid = s.get("chunk_id")
        if not gid or gid in new_ids or gid in remaps:
            continue
        old = old_chunks.get(gid)
        if old is None:
            failures.append(f"{gid}: eski chunk dosyasında da yok")
            continue
        target = _start_idx(gid)
        host = None
        for c in new_sorted:
            if _start_idx(c["chunk_id"]) <= target:
                host = c
            else:
                break
        if host is None:
            failures.append(f"{gid}: host bulunamadı")
            continue
        probes = _probe_lines(old["content"])
        # title satırını atla (probes[0] genelde title); içerikten doğrula
        check = probes[1:] or probes
        if not check or not all(p in host["content"] for p in check[:3]):
            failures.append(f"{gid}: içerik {host['chunk_id']} içinde doğrulanamadı")
            continue
        remaps[gid] = host["chunk_id"]

    if failures:
        print("❌ Remap İPTAL — doğrulanamayan etiketler:")
        for f in failures:
            print("   " + f)
        sys.exit(1)

    if not remaps:
        print("✅ Remap gereken etiket yok.")
        return

    print(f"{len(remaps)} gold etiket remap edilecek:")
    n_aff = 0
    for s in scenarios:
        gid = s.get("chunk_id")
        if gid in remaps:
            n_aff += 1
    for old_id, new_id in sorted(remaps.items()):
        print(f"   {old_id}  →  {new_id}")
    print(f"   (etkilenen senaryo: {n_aff}/{len(scenarios)})")

    if args.dry_run:
        print("(dry-run — dosya değişmedi)")
        return

    backup = SCENARIOS_PATH.with_suffix(".json.bak_pre_remap")
    if not backup.exists():
        shutil.copy2(SCENARIOS_PATH, backup)
        print(f"Yedek: {backup.name}")
    for s in scenarios:
        if s.get("chunk_id") in remaps:
            s["chunk_id"] = remaps[s["chunk_id"]]
    SCENARIOS_PATH.write_text(
        json.dumps(scenarios, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✅ Güncellendi: {SCENARIOS_PATH.name}")


if __name__ == "__main__":
    main()
