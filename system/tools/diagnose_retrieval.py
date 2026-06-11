#!/usr/bin/env python3
"""
diagnose_retrieval.py
=====================
İlk N senaryo için retrieval + LLM giriş/çıkışını tam olarak yazdırır.
Retrieval başarısızlığı mı yoksa model zayıflığı mı olduğunu teşhis eder.

Kullanım:
    python3 system/diagnose_retrieval.py              # ilk 5 madde
    python3 system/diagnose_retrieval.py --limit 10
    python3 system/diagnose_retrieval.py --model qwen2.5:3b --limit 5
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import OpenAI
from pipeline.retriever import retrieve, format_context
from config import TOP_K

SCENARIOS_PATH = ROOT / "data" / "test_scenarios.json"
KB_META_PATH   = ROOT / "data" / "kbs" / "aastp_test" / "kb_meta.json"
OLLAMA_URL     = "http://localhost:11434/v1"

SYSTEM_PROMPT = """You are a strict compliance auditor. You check whether audit findings comply with the official standard documents provided as context.

For each audit item, you will be given:
  - ITEM: the finding from the audit report
  - CONTEXT: relevant sections from the official standard

Your task: Determine whether the item is compliant with the standard.

Respond with EXACTLY this format:
VERDICT: <one of: UYGUN | UYGUN DEĞİL>
REASONING: <1-3 sentences citing specific rules, table names, or section numbers from the context>

Verdict meanings:
- UYGUN       : The item complies with the standard rules found in context.
- UYGUN DEĞİL : The item violates one or more rules in the standard.

Rules:
- Base your verdict ONLY on the provided context. Do not use external knowledge.
- You MUST choose exactly one of the two verdicts. Make your best binary judgment.
- Always cite the specific table name or section from the context in your reasoning.
- Keep reasoning concise and direct."""

SEP = "─" * 80

def _parse_verdict(text: str) -> tuple[str, str]:
    verdict = "DEĞERLENDİRİLEMEDİ"
    m = re.search(r"VERDICT\s*:\s*(UYGUN DEĞİL|UYGUN)", text, re.IGNORECASE)
    if m:
        raw = m.group(1).upper().strip()
        if raw in ["UYGUN", "UYGUN DEĞİL"]:
            verdict = raw
    r = re.search(r"REASONING\s*:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    reasoning = r.group(1).strip() if r else text.strip()
    return verdict, reasoning


def diagnose(model: str, limit: int):
    scenarios = json.loads(SCENARIOS_PATH.read_text())[:limit]
    kb_meta   = json.loads(KB_META_PATH.read_text())
    chroma_dir      = Path(kb_meta["chroma_dir"])
    collection_name = kb_meta["collection"]

    client = OpenAI(base_url=OLLAMA_URL, api_key="ollama")

    for s in scenarios:
        no   = s["item_no"]
        text = s["text"]
        expected = s["expected"]
        exp_table = s.get("table", "?")

        print(f"\n{SEP}")
        print(f"MADDE #{no:03d}  |  Beklenen: {expected}  |  Kaynak tablo: {exp_table}")
        print(SEP)
        print(f"SORU: {text}\n")

        # ── Retrieval ─────────────────────────────────────────────────────────
        matches = retrieve(
            query=text,
            chroma_dir=chroma_dir,
            collection_name=collection_name,
            top_k=TOP_K,
        )

        print(f"── Retrieval sonuçları (TOP_K={TOP_K}) ──────────────────────────────")
        if not matches:
            print("  [!] Hiçbir sonuç bulunamadı!")
        for i, m in enumerate(matches):
            kind = m["type"]
            name = m["table_name"] if kind == "table" else m.get("chunk_id", m.get("title", "?"))
            score = m.get("rerank_score", m.get("distance", "?"))
            score_str = f"{score:.4f}" if isinstance(score, float) else str(score)
            # Hedef tablo var mı?
            hit = "✓ HEDEFİN KENDİSİ" if (kind == "table" and name == exp_table) else ""
            print(f"  {i+1}. [{kind}] {name}  score={score_str}  {hit}")

        target_retrieved = any(
            m["type"] == "table" and m["table_name"] == exp_table
            for m in matches
        )
        if not target_retrieved:
            print(f"\n  ⚠️  '{exp_table}' TOP {TOP_K} içinde YOK → Retrieval başarısız!")

        # ── Context ───────────────────────────────────────────────────────────
        context = format_context(matches) if matches else "(boş)"
        print(f"\n── LLM'e gönderilen CONTEXT (ilk 1200 karakter) ────────────────────")
        print(context[:1200])
        if len(context) > 1200:
            print(f"  ... [{len(context)-1200} karakter daha]")

        # ── Model çağrısı ────────────────────────────────────────────────────
        if matches:
            user_msg = f"ITEM: {text}\n\nCONTEXT:\n{context}"
            t0 = time.time()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": user_msg},
                    ],
                    temperature=0.0,
                    max_tokens=300,
                )
                raw_out = resp.choices[0].message.content
                elapsed = time.time() - t0
                verdict, reasoning = _parse_verdict(raw_out)
            except Exception as e:
                elapsed = time.time() - t0
                verdict, reasoning, raw_out = "HATA", str(e), str(e)

            correct = "✓ DOĞRU" if verdict == expected else "✗ YANLIŞ"
            print(f"\n── Model çıktısı ({model}, {elapsed:.1f}s) ──────────────────────────")
            print(f"  Ham çıktı: {raw_out[:500]}")
            print(f"\n  VERDICT  : {verdict}  {correct}")
            print(f"  REASONING: {reasoning[:300]}")
        else:
            print("\n  [Model çağrısı atlandı — context yok]")

    print(f"\n{SEP}")
    print("Tanı tamamlandı.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()
    diagnose(args.model, args.limit)


if __name__ == "__main__":
    main()
