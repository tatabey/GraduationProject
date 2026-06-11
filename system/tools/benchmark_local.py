#!/usr/bin/env python3
"""
benchmark_local.py
==================
Farklı yerel Ollama modellerini 200 senaryo üzerinde karşılaştırır.
Mevcut hiçbir pipeline dosyasını değiştirmez.

Çıktı (kaldırılabilir):
    system/data/benchmark/<model>_results.json
    system/data/benchmark/comparison.txt

Kullanım:
    python3 system/benchmark_local.py
    python3 system/benchmark_local.py --models phi4-mini qwen2.5:3b llama3.2:3b
    python3 system/benchmark_local.py --models phi4-mini --skip-pull
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from openai import OpenAI
from pipeline.retriever import retrieve, format_context
from config import (
    TOP_K, VERDICTS, ERROR_VERDICT,
    OLLAMA_URL, GROQ_API_KEY, GROQ_BASE_URL,
    CEREBRAS_API_KEY, CEREBRAS_BASE_URL,
    MODEL_LADDER, GROQ_RPM_DELAY, LLM_MAX_TOKENS, CONTEXT_CHAR_CAP,
)

# ── Sabitler ──────────────────────────────────────────────────────────────────
SCENARIOS_PATH  = ROOT / "data" / "test_scenarios.json"  # varsayılan; --scenarios ile geçersiz kılınır
BENCHMARK_DIR   = ROOT / "data" / "benchmark"
KB_META_PATH    = ROOT / "data" / "kbs" / "aastp_test" / "kb_meta.json"
# Paralel koşularda iki süreç aynı cache'i ezmesin diye env ile ayrılabilir:
#   VERDICT_CACHE_NAME=.cache_scout.json python3 benchmark_local.py ...
CACHE_PATH      = BENCHMARK_DIR / os.getenv("VERDICT_CACHE_NAME", ".verdict_cache.json")
DEFAULT_MODELS  = ["phi4-mini", "qwen2.5:3b", "llama3.2:3b"]

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


# ── Yardımcılar ───────────────────────────────────────────────────────────────
def _parse_verdict(text: str) -> tuple[str, str]:
    verdict = "UYGUN DEĞİL"   # parse başarısız → muhafazakâr default (modele yazılır)
    reasoning = text.strip()
    m = re.search(r"VERDICT\s*:\s*(UYGUN DEĞİL|UYGUN)", text, re.IGNORECASE)
    if m:
        raw = m.group(1).upper().strip()
        if raw in VERDICTS:
            verdict = raw
    r = re.search(r"REASONING\s*:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
    if r:
        reasoning = r.group(1).strip()
    return verdict, reasoning


def ensure_model(model: str) -> bool:
    """Model yoksa indir. True döner başarılıysa."""
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
    installed = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.strip()]
    # Hem "phi4-mini" hem "phi4-mini:latest" eşleşsin
    base = model.split(":")[0]
    if any(i.split(":")[0] == base for i in installed):
        print(f"  ✓ {model} zaten kurulu.")
        return True
    print(f"  ⬇ {model} indiriliyor... (birkaç dakika sürebilir)")
    r = subprocess.run(["ollama", "pull", model], capture_output=False, text=True)
    return r.returncode == 0


# ── Sağlayıcı istemcisi (OpenAI-uyumlu: ollama + groq) ────────────────────────
def make_client(provider: str) -> OpenAI:
    if provider == "groq":
        return OpenAI(base_url=GROQ_BASE_URL, api_key=GROQ_API_KEY)
    if provider == "cerebras":
        return OpenAI(base_url=CEREBRAS_BASE_URL, api_key=CEREBRAS_API_KEY)
    return OpenAI(base_url=OLLAMA_URL, api_key="ollama")


# ── Verdict cache (tekrar çalıştırma = 0 token, limit-güvenli devam) ──────────
def _load_cache() -> dict:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_cache(cache: dict) -> None:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


# Prompt'un kısa hash'i — prompt değişince eski cache otomatik geçersiz olur
_PROMPT_HASH = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12]


def _cache_key(label: str, item_text: str, context: str) -> str:
    raw = f"{label}\x00{_PROMPT_HASH}\x00{item_text}\x00{context}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def call_llm(client: OpenAI, model: str, item_text: str, context: str,
             provider: str = "ollama") -> tuple[str, str]:
    # Bağlam kırpma: API'ye giden input token'ı sınırla (tüm cloud sağlayıcılar)
    if provider != "ollama" and len(context) > CONTEXT_CHAR_CAP:
        context = context[:CONTEXT_CHAR_CAP] + "\n…[kısaltıldı]"
    user_msg = f"ITEM: {item_text}\n\nCONTEXT:\n{context}"

    for attempt in range(4):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": user_msg},
                ],
                temperature=0.0,
                max_tokens=LLM_MAX_TOKENS,
            )
            content = resp.choices[0].message.content or ""
            if not content.strip():
                # Reasoning modeli token'ı düşünmeye harcayıp cevap üretemedi
                return ERROR_VERDICT, "hata: model boş içerik döndü (reasoning token aşımı)"
            return _parse_verdict(content)
        except Exception as e:
            err = str(e).lower()
            if ("rate_limit" in err or "429" in err) and attempt < 3:
                wait = 5 * (2 ** attempt)  # 5, 10, 20 sn backoff
                print(f"\n  ⏳ rate-limit, {wait}s bekleniyor (deneme {attempt+1}/3)...",
                      flush=True)
                time.sleep(wait)
                continue
            return ERROR_VERDICT, f"hata: {e}"
    return ERROR_VERDICT, "hata: rate-limit aşıldı"


# ── Tek model benchmark ───────────────────────────────────────────────────────
def run_benchmark(entry: dict, kb_meta: dict, scenarios: list[dict],
                  cache: dict) -> dict:
    label    = entry["label"]
    provider = entry.get("provider", "ollama")
    params_b = entry.get("params_b", 0.0)
    chroma_dir      = Path(kb_meta["chroma_dir"])
    collection_name = kb_meta["collection"]
    client          = make_client(provider)

    results   = []
    durations = []
    n = len(scenarios)

    print(f"\n{'─'*60}")
    print(f"  Model : {label}  ({params_b:g}B, {provider})")
    print(f"  Madde : {n}")
    print(f"{'─'*60}")

    for idx, s in enumerate(scenarios):
        no   = s["item_no"]
        text = s["text"]

        matches = retrieve(
            query=text,
            chroma_dir=chroma_dir,
            collection_name=collection_name,
            top_k=TOP_K,
        )

        t0 = time.time()
        if matches:
            context = format_context(matches)
            ckey = _cache_key(label, text, context)
            if ckey in cache:
                verdict, reasoning = cache[ckey]["verdict"], cache[ckey]["reasoning"]
                cached = True
            else:
                verdict, reasoning = call_llm(client, label, text, context, provider)
                # Hatalı/limit sonuçlarını cache'leme → resume'da tekrar denensin
                if not reasoning.startswith("hata:"):
                    cache[ckey] = {"verdict": verdict, "reasoning": reasoning}
                cached = False
                if provider == "groq":
                    time.sleep(GROQ_RPM_DELAY)  # throttle
        else:
            verdict, reasoning = ERROR_VERDICT, "Bağlamda ilgili kural bulunamadı."
            cached = False
        elapsed = time.time() - t0
        durations.append(elapsed)

        results.append({
            "item_no"  : no,
            "text"     : text,
            "verdict"  : verdict,
            "reasoning": reasoning,
            "expected" : s["expected"],
            "table"    : s.get("table") or s.get("section", "?"),
            "elapsed_s": round(elapsed, 2),
        })

        mark = "✓" if verdict == s["expected"] else "✗"
        tag  = "⚡" if cached else " "
        bar_done = int((idx + 1) / n * 30)
        bar = "█" * bar_done + "░" * (30 - bar_done)
        print(f"\r  [{bar}] {idx+1:3d}/{n} {tag}#{no:03d} {mark} {verdict:<12} ({elapsed:.1f}s)",
              end="", flush=True)

        if (idx + 1) % 20 == 0:   # ara cache kaydı (kesintide kayıp olmasın)
            _save_cache(cache)

    print()  # newline after progress
    _save_cache(cache)
    avg_s = sum(durations) / len(durations) if durations else 0
    total_s = sum(durations)
    return {"model": label, "params_b": params_b, "provider": provider,
            "results": results, "avg_s": avg_s, "total_s": total_s}


# ── Metrikler ─────────────────────────────────────────────────────────────────
def evaluate(results: list[dict]) -> dict:
    correct = wrong = 0
    by_table   = defaultdict(lambda: {"correct": 0, "total": 0})
    by_verdict = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0})
    errors = []

    for r in results:
        predicted = r["verdict"]
        expected  = r["expected"]
        table     = r["table"]
        by_table[table]["total"] += 1

        if predicted == expected:
            correct += 1
            by_table[table]["correct"] += 1
            by_verdict[expected]["tp"] += 1
        else:
            wrong += 1
            by_verdict[expected]["fn"] += 1
            by_verdict[predicted]["fp"] += 1
            errors.append(r)

    total    = correct + wrong
    accuracy = correct / total * 100 if total else 0
    return {
        "total"     : total,
        "correct"   : correct,
        "wrong"     : wrong,
        "accuracy"  : accuracy,
        "by_table"  : {k: dict(v) for k, v in by_table.items()},
        "by_verdict": {k: dict(v) for k, v in by_verdict.items()},
        "errors"    : errors[:10],
    }


def _class_accuracy(results: list[dict]) -> dict[str, float]:
    """Her gerçek sınıf için recall (doğru/o sınıfın toplamı), %."""
    per = {}
    for v in VERDICTS:
        items = [r for r in results if r["expected"] == v]
        if items:
            hit = sum(1 for r in items if r["verdict"] == v)
            per[v] = hit / len(items) * 100
        else:
            per[v] = 0.0
    return per


# ── Karşılaştırma raporu ──────────────────────────────────────────────────────
def print_comparison(all_benchmarks: list[dict]):
    sep = "═" * 100
    # Parametreye göre artan sırala (tez: boyut vs doğruluk)
    all_benchmarks = sorted(all_benchmarks, key=lambda b: b.get("params_b", 0.0))

    n_total = sum(b.get("params_b", 0) or len(b["results"]) for b in all_benchmarks[:1]) or "?"
    n_total = len(all_benchmarks[0]["results"]) if all_benchmarks else "?"
    print(f"\n{sep}")
    print(f"  MODEL-BOYUTU MERDİVENİ — AASTP-1 / {n_total} Senaryo (2 sınıf: UYGUN / UYGUN DEĞİL)")
    print(sep)

    header = (f"  {'Model':<26} {'Params':>7} {'Sağlay.':>8} {'Doğruluk':>9} "
              f"{'UYGUN':>7} {'DEĞİL':>7} {'Ort.Süre':>9}")
    print(header)
    print(f"  {'─'*26} {'─'*7} {'─'*8} {'─'*9} {'─'*7} {'─'*7} {'─'*9}")

    for b in all_benchmarks:
        ev = evaluate(b["results"])
        pc = _class_accuracy(b["results"])
        print(f"  {b['model']:<26} {b.get('params_b',0):>6g}B {b.get('provider','?'):>8} "
              f"{ev['accuracy']:>8.1f}% {pc['UYGUN']:>6.0f}% {pc['UYGUN DEĞİL']:>6.0f}% "
              f"{b['avg_s']:>8.1f}s")

    # Tablo bazında karşılaştırma
    print(f"\n  Tablo Bazında Doğruluk (%):")
    tables = sorted({t for b in all_benchmarks for t in evaluate(b["results"])["by_table"]})
    model_names = [b["model"] for b in all_benchmarks]
    col_w = 14
    header2 = f"  {'Tablo':<14}" + "".join(f"{m[:col_w]:>{col_w}}" for m in model_names)
    print(header2)
    print(f"  {'─'*14}" + "─" * (col_w * len(model_names)))
    for tbl in tables:
        row = f"  {tbl:<14}"
        for b in all_benchmarks:
            ev = evaluate(b["results"])
            d  = ev["by_table"].get(tbl, {"correct": 0, "total": 0})
            pct = d["correct"] / d["total"] * 100 if d["total"] else 0
            row += f"{pct:>{col_w}.1f}"
        print(row)

    # Verdict dağılımı
    print(f"\n  Verdict Dağılımı:")
    vhdr = f"  {'Verdict':<14}" + "".join(f"{m[:col_w]:>{col_w}}" for m in model_names)
    print(vhdr)
    print(f"  {'─'*14}" + "─" * (col_w * len(model_names)))
    for v in VERDICTS:
        row = f"  {v:<14}"
        for b in all_benchmarks:
            cnt = sum(1 for r in b["results"] if r["verdict"] == v)
            row += f"{cnt:>{col_w}}"
        print(row)
    print(f"  {'Beklenen':<14}")
    row_exp = f"  {'(ground truth)':<14}"
    if all_benchmarks:
        exp_counts = Counter(r["expected"] for r in all_benchmarks[0]["results"])
        for b in all_benchmarks:
            row_exp += " " * (col_w - 1) + "—"
        print()
        for v in VERDICTS:
            print(f"    {v}: {exp_counts.get(v, 0)} beklenen")

    print(f"\n{sep}\n")


# ── Ana ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Model-boyutu merdiveni benchmark")
    parser.add_argument("--ladder", action="store_true",
                        help="config.MODEL_LADDER'deki tüm modelleri (yerel + Groq) çalıştır")
    parser.add_argument("--models", nargs="+", default=None,
                        help="Yalnız bu Ollama modelleri (geriye dönük uyum)")
    parser.add_argument("--skip-pull", action="store_true",
                        help="Ollama model indirme adımını atla")
    parser.add_argument("--limit", type=int, default=0,
                        help="Test edilecek maksimum senaryo sayısı (0=hepsi)")
    parser.add_argument("--scenarios", type=Path, default=None,
                        help="Test senaryoları JSON dosyası (varsayılan: data/test_scenarios.json)")
    parser.add_argument("--tag", type=str, default=None,
                        help="Çıktı dosyası öneki, ör. set1/set2/set3 (varsayılan: senaryolar dosyasından türetilir)")
    args = parser.parse_args()

    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)

    # Senaryo dosyası ve çıktı etiketi
    scenarios_path = args.scenarios if args.scenarios else SCENARIOS_PATH
    if args.tag:
        run_tag = args.tag
    else:
        stem = Path(scenarios_path).stem          # ör. test_scenarios_set2
        run_tag = stem.replace("test_scenarios", "").strip("_") or "set1"
        if not run_tag:
            run_tag = "set1"

    # Çalıştırılacak model girdileri (entry: {label, params_b, provider})
    if args.models:
        ladder_map = {e["label"]: e for e in MODEL_LADDER}
        entries = [
            ladder_map[m] if m in ladder_map
            else {"label": m, "params_b": 0.0, "provider": "ollama"}
            for m in args.models
        ]
    elif args.ladder:
        entries = list(MODEL_LADDER)
    else:
        entries = [e for e in MODEL_LADDER if e["provider"] == "ollama"]  # varsayılan: yerel

    # Senaryolar
    scenarios = json.loads(scenarios_path.read_text())
    if args.limit:
        scenarios = scenarios[:args.limit]
    print(f"\n✔ {len(scenarios)} senaryo yüklendi ({scenarios_path.name}, etiket: {run_tag})")

    # KB meta
    kb_meta = json.loads(KB_META_PATH.read_text())
    print(f"✔ Bilgi tabanı: {kb_meta['kb_name']} "
          f"({kb_meta['tables']} tablo + {kb_meta['chunks']} chunk)")

    cache = _load_cache()
    print(f"✔ Verdict cache: {len(cache)} kayıtlı (tekrar çağrı = 0 token)")

    # Model hazırlık (yalnız Ollama indirme gerektirir)
    print(f"\n── Model Hazırlık {'─'*44}")
    ready_entries = []
    for e in entries:
        if e["provider"] == "ollama" and not args.skip_pull:
            if ensure_model(e["label"]):
                ready_entries.append(e)
            else:
                print(f"  ✗ {e['label']} kurulamadı, atlanıyor.")
        else:
            ready_entries.append(e)

    if not ready_entries:
        print("Hiçbir model hazır değil. Çıkılıyor.")
        sys.exit(1)

    # Benchmark
    all_benchmarks = []
    for e in ready_entries:
        bm = run_benchmark(e, kb_meta, scenarios, cache)

        # JSON kaydet
        safe_name = e["label"].replace(":", "_").replace("/", "_")
        out_path  = BENCHMARK_DIR / f"{run_tag}_{safe_name}_results.json"
        out_path.write_text(
            json.dumps(bm["results"], ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"  💾 Kayıt: {out_path.relative_to(ROOT.parent)}")

        all_benchmarks.append(bm)

    # Tez için makine-okur merdiven JSON'u (params_b vs accuracy)
    ladder_json = []
    for b in sorted(all_benchmarks, key=lambda x: x.get("params_b", 0.0)):
        ev = evaluate(b["results"])
        ladder_json.append({
            "label"    : b["model"],
            "params_b" : b.get("params_b", 0.0),
            "provider" : b.get("provider", "?"),
            "accuracy" : round(ev["accuracy"], 2),
            "per_class": {k: round(v, 1) for k, v in _class_accuracy(b["results"]).items()},
            "per_table": {t: round(d["correct"]/d["total"]*100, 1) if d["total"] else 0.0
                          for t, d in ev["by_table"].items()},
            "avg_s"    : round(b["avg_s"], 2),
        })
    ladder_file = BENCHMARK_DIR / f"{run_tag}_ladder_comparison.json"
    ladder_file.write_text(json.dumps(ladder_json, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  📊 Merdiven JSON: {ladder_file.relative_to(ROOT.parent)}")

    # Karşılaştırma
    print_comparison(all_benchmarks)

    # Özet metin dosyası
    import io
    old_stdout = sys.stdout
    sys.stdout = buffer = io.StringIO()
    print_comparison(all_benchmarks)
    sys.stdout = old_stdout
    comparison_text = buffer.getvalue()
    cmp_path = BENCHMARK_DIR / f"{run_tag}_comparison.txt"
    cmp_path.write_text(comparison_text, encoding="utf-8")
    print(f"  📄 Karşılaştırma raporu: {cmp_path.relative_to(ROOT.parent)}")

    # eval_200.py uyumlu özet
    for b in all_benchmarks:
        ev = evaluate(b["results"])
        safe = b["model"].replace(":", "_").replace("/", "_")
        eval_path = BENCHMARK_DIR / f"{run_tag}_{safe}_eval.json"
        eval_path.write_text(
            json.dumps(ev, ensure_ascii=False, indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
