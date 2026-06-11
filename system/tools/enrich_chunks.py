#!/usr/bin/env python3
"""
enrich_chunks.py
================
Her text chunk için YEREL Ollama ile senaryo-stili sentetik sorular üretir
(multi-vector index için). Kök nedeni hedefler: senaryo anlatısı ("Magazine
Alpha stores 800 kg...") ile mevzuat dili ("distances shall be calculated...")
arasındaki embedding boşluğu — sentetik soru, chunk'ı sorgu diline yaklaştırır.

- Sıfır cloud token: localhost Ollama (config.OLLAMA_MODEL).
- Tek seferlik, RESUMABLE: çıktı dosyasındaki chunk_id'ler atlanır; her 10
  chunk'ta diske yazar. Kesilirse kaldığı yerden devam eder.
- Domain'e özel hiçbir şey yok — her PDF'in chunk'larıyla çalışır.

Çıktı: <kb>/text_chunks/synth_queries.json   {chunk_id: [soru, ...]}
Kullanım:
    python3 system/tools/enrich_chunks.py --kb aastp_test [--n 2]
"""

import argparse
import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import OLLAMA_URL, OLLAMA_MODEL  # noqa: E402

PROMPT = """You are indexing a technical regulations document for a search system.
Below is one passage from the document.

Write exactly {n} short, concrete, scenario-style questions that a compliance
officer might ask, and which THIS passage answers. Use realistic quantities,
units and entity names where appropriate. Output ONLY the questions, one per
line, no numbering, no extra text.

SECTION: {section}
PASSAGE:
{content}"""


def _ask_ollama(prompt: str, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            r = requests.post(
                f"{OLLAMA_URL}/chat/completions",
                json={
                    "model": OLLAMA_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.4,
                    "max_tokens": 220,
                },
                timeout=120,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"] or ""
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return ""


def _parse_questions(raw: str, n: int) -> list[str]:
    qs = []
    for ln in raw.splitlines():
        ln = ln.strip().lstrip("-*0123456789.) ").strip()
        if len(ln) >= 15 and "?" in ln:
            qs.append(ln)
    return qs[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kb", default="aastp_test")
    ap.add_argument("--n", type=int, default=2, help="chunk başına soru sayısı")
    args = ap.parse_args()

    kb_dir      = ROOT / "data" / "kbs" / args.kb
    chunks_path = kb_dir / "text_chunks" / "text_chunks.json"
    out_path    = kb_dir / "text_chunks" / "synth_queries.json"

    chunks = json.loads(chunks_path.read_text(encoding="utf-8"))
    done: dict[str, list[str]] = {}
    if out_path.exists():
        done = json.loads(out_path.read_text(encoding="utf-8"))
        print(f"Devam ediliyor: {len(done)} chunk zaten işlenmiş.")

    todo = [c for c in chunks if c["chunk_id"] not in done]
    total = len(todo)
    print(f"{total} chunk işlenecek (model: {OLLAMA_MODEL}, soru/chunk: {args.n})")

    t0 = time.time()
    fails = 0
    for i, c in enumerate(todo):
        section = " > ".join(c.get("section_path", [])) or c.get("title", "")
        prompt  = PROMPT.format(n=args.n, section=section, content=c["content"][:1500])
        try:
            raw = _ask_ollama(prompt)
            qs  = _parse_questions(raw, args.n)
        except Exception as e:
            qs = []
            fails += 1
            print(f"\n  ! {c['chunk_id']}: {e}")
        done[c["chunk_id"]] = qs

        if (i + 1) % 10 == 0 or i + 1 == total:
            out_path.write_text(
                json.dumps(done, ensure_ascii=False, indent=1), encoding="utf-8"
            )
        el  = time.time() - t0
        eta = el / (i + 1) * (total - i - 1)
        print(f"\r  [{i+1}/{total}]  {el/60:.1f} dk geçti, ~{eta/60:.0f} dk kaldı  (hata: {fails})",
              end="", flush=True)

    print(f"\n✅ Bitti: {len(done)} chunk → {out_path}")
    empty = sum(1 for v in done.values() if not v)
    if empty:
        print(f"  Uyarı: {empty} chunk için soru üretilemedi (indekste atlanır).")


if __name__ == "__main__":
    main()
