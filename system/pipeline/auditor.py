"""
Auditor
=======
Denetim raporu maddelerini KB'ye karşı sorgular,
her madde için LLM verdict üretir.

Dışarıya açık:
    audit_items(items, kb_meta, api_key=None, log_fn=print) -> list[dict]

Her sonuç:
    {
      "item_no"  : int,
      "text"     : str,
      "verdict"  : "UYGUN" | "UYGUN DEĞİL" | "DEĞERLENDİRİLEMEDİ",
      "reasoning": str,
      "sources"  : [{"name": str, "type": str, "page_idx": int}, ...],
      "context"  : str,   # LLM'e gönderilen ham bağlam
    }
"""

import queue
import re
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable

from openai import OpenAI

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (
    TOP_K, VERDICTS, ERROR_VERDICT,
    AUDIT_PROVIDER, AUDIT_MODEL,
    GROQ_API_KEY, GROQ_BASE_URL,
    CEREBRAS_API_KEY, CEREBRAS_BASE_URL,
    OLLAMA_URL, LLM_MAX_TOKENS, CONTEXT_CHAR_CAP,
    AUDIT_PREFETCH, LLM_MAX_CALLS_PER_MIN, TIMING_LOGS,
)
from pipeline.retriever import retrieve, format_context


# ---------------------------------------------------------------------------
# Sağlayıcı istemcisi (OpenAI-uyumlu: cerebras / groq / ollama)
# ---------------------------------------------------------------------------
def make_client(provider: str, api_key: str = "") -> OpenAI:
    if provider == "cerebras":
        return OpenAI(base_url=CEREBRAS_BASE_URL, api_key=api_key or CEREBRAS_API_KEY)
    if provider == "groq":
        return OpenAI(base_url=GROQ_BASE_URL, api_key=api_key or GROQ_API_KEY)
    return OpenAI(base_url=OLLAMA_URL, api_key="ollama")


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """You are a strict compliance auditor. You check whether audit findings comply with the official standard documents provided as context.

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


def _parse_verdict(response_text: str) -> tuple[str, str]:
    """LLM çıktısından (verdict, reasoning) çifti çıkarır."""
    verdict = ERROR_VERDICT   # bozuk/parse edilemeyen çıktı = değerlendirilemedi
    reasoning = response_text.strip()

    m = re.search(r"VERDICT\s*:\s*(UYGUN DEĞİL|UYGUN)", response_text, re.IGNORECASE)
    if m:
        raw = m.group(1).upper().strip()
        if raw in VERDICTS:
            verdict = raw

    r = re.search(r"REASONING\s*:\s*(.+)", response_text, re.DOTALL | re.IGNORECASE)
    if r:
        reasoning = r.group(1).strip()

    return verdict, reasoning


def _call_llm(client: OpenAI, model: str, provider: str,
              item_text: str, context: str,
              log_fn: Callable[[str], None] = print) -> tuple[str, str]:
    # Bağlam kırpma: cloud sağlayıcılara giden input token'ı sınırla
    if provider != "ollama" and len(context) > CONTEXT_CHAR_CAP:
        context = context[:CONTEXT_CHAR_CAP] + "\n…[kısaltıldı]"
    user_msg = f"ITEM: {item_text}\n\nCONTEXT:\n{context}"

    for attempt in range(4):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=LLM_MAX_TOKENS,
            )
            content = resp.choices[0].message.content or ""
            if not content.strip():
                return ERROR_VERDICT, "Model boş içerik döndü (reasoning token aşımı)."
            return _parse_verdict(content)
        except Exception as e:
            err = str(e).lower()
            # Rate-limit (429) → exponential backoff: 5 → 10 → 20 sn bekle, tekrar dene
            if ("rate_limit" in err or "429" in err) and attempt < 3:
                wait = 5 * (2 ** attempt)
                log_fn(f"  ⏳ API limiti — {wait}s bekleniyor (deneme {attempt+1}/3)...")
                time.sleep(wait)
                continue
            if "rate_limit" in err or "429" in err:
                return ERROR_VERDICT, "API limiti aşıldı. Biraz bekleyip tekrar deneyin."
            return ERROR_VERDICT, f"LLM hatası: {e}"
    return ERROR_VERDICT, "API limiti: tekrar denemeler tükendi."


def _source_label(m: dict) -> dict:
    if m["type"] == "table":
        return {
            "name"    : m["table_name"],
            "type"    : "table",
            "page_idx": m.get("page_idx", -1),
            "html"    : m.get("html", ""),
            "notes"   : m.get("notes", ""),
            "legend"  : m.get("legend", ""),
            "img_path": m.get("img_path", ""),
        }
    return {
        "name"    : m.get("title", m.get("chunk_id", "?")),
        "type"    : "text_chunk",
        "page_idx": m.get("page_idx", -1),
        "html"    : "",
        "notes"   : "",
        "legend"  : "",
        "img_path": "",
    }


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
def audit_items(
    items: list[dict],
    kb_meta: dict,
    api_key: str | None = None,
    top_k: int = TOP_K,
    log_fn: Callable[[str], None] = print,
    provider: str = AUDIT_PROVIDER,
    model: str = AUDIT_MODEL,
) -> list[dict]:
    """
    items    : parse_report() çıktısı — [{"item_no": int, "text": str}, ...]
    kb_meta  : build_kb() / list_kbs() çıktısı — {"chroma_dir": str, "collection": str, ...}
    api_key  : sağlayıcı anahtarı override (boşsa config'deki kullanılır)
    provider : "cerebras" (varsayılan) | "groq" | "ollama"
    """
    chroma_dir      = Path(kb_meta["chroma_dir"])
    collection_name = kb_meta["collection"]
    client          = make_client(provider, api_key or "")
    log_fn(f"Model: {model} ({provider})")
    results = []

    n = len(items)

    # ── Pipelining: N+1'in retrieval'ı, N'in LLM çağrısıyla paralel yürür ──
    def _retrieve_one(item: dict):
        t0 = time.perf_counter()
        try:
            m = retrieve(
                query=item["text"],
                chroma_dir=chroma_dir,
                collection_name=collection_name,
                top_k=top_k,
            )
            return m, time.perf_counter() - t0
        except Exception as e:
            return e, time.perf_counter() - t0

    if AUDIT_PREFETCH and n > 1:
        _q: queue.Queue = queue.Queue(maxsize=2)

        def _producer():
            for it in items:
                _q.put((it, _retrieve_one(it)))
            _q.put(None)

        threading.Thread(target=_producer, daemon=True).start()

        def _stream():
            while True:
                got = _q.get()
                if got is None:
                    return
                yield got
        stream = _stream()
    else:
        stream = ((it, _retrieve_one(it)) for it in items)

    # ── Proaktif tempo: kayar 60 sn penceresinde ≤ LLM_MAX_CALLS_PER_MIN çağrı.
    #    Reaktif 429 backoff'un kör beklemelerinin yerini alır; küçük raporlarda
    #    (pencere dolmadan) burst korunur.
    _call_times: deque = deque()

    def _pace():
        if LLM_MAX_CALLS_PER_MIN <= 0 or provider == "ollama":
            return
        now = time.time()
        while _call_times and now - _call_times[0] > 60:
            _call_times.popleft()
        if len(_call_times) >= LLM_MAX_CALLS_PER_MIN:
            wait = 60 - (now - _call_times[0]) + 0.5
            if wait > 0:
                log_fn(f"  ⏳ API temposu — {wait:.0f}s bekleniyor (limit aşımı önleme)")
                time.sleep(wait)
        _call_times.append(time.time())

    for idx, (item, ret) in enumerate(stream):
        no   = item["item_no"]
        text = item["text"]
        pct  = int((idx + 0.5) / n * 100)
        log_fn(f"__PROGRESS__:{pct}:Madde {idx+1}/{n} denetleniyor")
        log_fn(f"▶ Madde #{no:02d} analiz ediliyor...")

        matches, retrieve_s = ret
        if isinstance(matches, Exception):
            log_fn(f"  → {ERROR_VERDICT} (retrieval hatası: {matches})")
            results.append({
                "item_no"  : no,
                "text"     : text,
                "verdict"  : ERROR_VERDICT,
                "reasoning": f"Retrieval hatası: {matches}",
                "sources"  : [],
                "context"  : "",
            })
            continue

        if not matches:
            log_fn(f"  → {ERROR_VERDICT} (ilgili kayıt bulunamadı)")
            results.append({
                "item_no"  : no,
                "text"     : text,
                "verdict"  : ERROR_VERDICT,
                "reasoning": "Bilgi tabanında ilgili kural bulunamadı.",
                "sources"  : [],
                "context"  : "",
            })
            continue

        context = format_context(matches)
        _pace()
        t_llm = time.perf_counter()
        verdict, reasoning = _call_llm(client, model, provider, text, context, log_fn)
        llm_s = time.perf_counter() - t_llm

        if TIMING_LOGS:
            log_fn(f"  ⏱ retrieval {retrieve_s:.1f}s · LLM {llm_s:.1f}s")
        log_fn(f"  → {verdict}")

        results.append({
            "item_no"  : no,
            "text"     : text,
            "verdict"  : verdict,
            "reasoning": reasoning,
            "sources"  : [_source_label(m) for m in matches],
            "context"  : context,
        })

    return results
