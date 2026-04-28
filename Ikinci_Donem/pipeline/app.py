"""
AASTP-1 AI Audit System — Phase 2
Pipeline: HyDE Retriever (ChromaDB) + Groq LLM
"""

import base64
import json
import os
import re
import sys
import time
from io import BytesIO
from pathlib import Path

import gradio as gr
from groq import Groq

PIPELINE_DIR_IMPORT = Path(__file__).parent
sys.path.insert(0, str(PIPELINE_DIR_IMPORT))
sys.path.insert(0, str(PIPELINE_DIR_IMPORT / "scripts"))

from hyde_retriever import retrieve, format_context_for_llm
from table_context_assembler import assemble_semantic_units, save_semantic_units
from multi_vector_indexer import run_indexing
import mineru_batch as mb

# ---------------------------------------------------------------------------
# Yapılandırma — API anahtarları
# ---------------------------------------------------------------------------
MINERU_API_KEY = os.getenv("MINERU_API_KEY","***REMOVED***")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "***REMOVED***")
GROQ_MODEL   = "llama-3.3-70b-versatile"

PIPELINE_DIR = PIPELINE_DIR_IMPORT

try:
    groq_client = Groq(api_key=GROQ_API_KEY)
except Exception:
    groq_client = None

# ---------------------------------------------------------------------------
# Test setleri
# ---------------------------------------------------------------------------
TEST_SET_MATRIX = """Found 100kg of Group D stored with Group E without separation.
Found 50kg of Group B stored with 20kg of Group K.
Found 50kg of Group B stored with 20kg of Group D.
Compatibility Group C articles are stored with Compatibility Group S articles.
Compatibility Group H articles are stored in the same magazine as Compatibility Group J articles.
Mixing of Compatibility Group L articles with Compatibility Group F articles."""

TEST_SET_CHEMICAL = """Found Toxic Agents (Group K) stored without full protective clothing Set 1.
Found Napalm stored while water suppression system was active.
What are the safety rules for White Phosphorous (WP)?
Found Smoke HC stored without breathing apparatus.
Can I use water on Calcium Phosphide?"""

TEST_SET_COMPLEX = """Found suspect ammunition stored with Group D items.
Articles of Compatibility Group N are stored with Group S.
Found Group B fuses stored with Group D without NEQ aggregation.
Toxic Agents without explosives components stored as Group K."""

# ---------------------------------------------------------------------------
# LLM çağrısı
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a senior AASTP-1 Storage Auditor. You handle two types of inputs:

TYPE A — COMPLIANCE SCENARIO: Describes a storage situation that may violate rules.
  Examples: "Found Group B stored with Group D", "Group K stored without protective clothing"
  → Use verdict: COMPLIANT | NON-COMPLIANT | CONDITIONAL

TYPE B — INFORMATION QUESTION: Asks what the rules say about a substance or group.
  Examples: "What are the rules for WP?", "What does Group K require?", "How should Napalm be stored?"
  → Use verdict: INFORMATIONAL

HOW TO READ THE RULES:
- "PERMITTED" or "X = Mixing permitted" → COMPLIANT
- "PROHIBITED" or mixing not listed → NON-COMPLIANT
- "CONDITIONAL (Note N)" → Check the note, then decide
- Table T.1 columns: Full Protective Clothing (Set 1/2/3), Breathing Apparatus, Apply No Water

RESPONSE FORMAT (strict):
VERDICT: COMPLIANT | NON-COMPLIANT | CONDITIONAL | INFORMATIONAL
REASONING: One concise paragraph. For INFORMATIONAL, state the exact rules found (compatibility group, required PPE, restrictions)."""

def get_llm_verdict(scenario: str, context: str) -> tuple[str, str]:
    if not groq_client:
        return "UNKNOWN", "Groq client not available."
    try:
        resp = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"RULES:\n{context}\n\nSCENARIO: {scenario}"},
            ],
            temperature=0.0,
            max_tokens=250,
        )
        text = resp.choices[0].message.content.strip()
    except Exception as e:
        return "UNKNOWN", f"API Error: {e}"

    verdict = "UNKNOWN"
    for v in ("NON-COMPLIANT", "CONDITIONAL", "INFORMATIONAL", "COMPLIANT"):
        if v in text.upper():
            verdict = v
            break

    parts = re.split(r"REASONING[:\s\-]+", text, flags=re.IGNORECASE)
    reasoning = parts[-1].strip() if len(parts) > 1 else text
    return verdict, reasoning

# ---------------------------------------------------------------------------
# HTML kart üretici (Audit tab)
# ---------------------------------------------------------------------------
def make_card(
    index: int, scenario: str, verdict: str, reasoning: str, context: str,
) -> str:
    palette = {
        "COMPLIANT":     ("#22c55e", "#0f2a1a", "#4ade80", "✅"),
        "NON-COMPLIANT": ("#ef4444", "#2a0f0f", "#fca5a5", "⛔"),
        "CONDITIONAL":   ("#f59e0b", "#2a1f00", "#fcd34d", "⚠️"),
        "INFORMATIONAL": ("#3b82f6", "#0f1e3a", "#93c5fd", "ℹ️"),
        "UNKNOWN":       ("#6b7280", "#1c2333", "#9ca3af", "❓"),
    }
    color, bg, text, icon = palette.get(verdict, palette["UNKNOWN"])
    context_html = context.replace("\n", "<br>")

    return f"""
    <div style="border:1px solid {color}50; border-left:5px solid {color}; border-radius:10px;
                margin-bottom:20px; background:{bg};
                font-family:'Segoe UI',sans-serif;
                box-shadow:0 4px 16px rgba(0,0,0,0.4);">
      <div style="padding:20px;">
        <div style="font-weight:900; font-size:1.25em; color:{color}; margin-bottom:14px;
                    letter-spacing:-0.3px;">
          {icon} CASE {index}: {verdict}
        </div>
        <div style="margin-bottom:12px;">
          <p style="margin:0; color:#8b949e; font-size:0.72em; font-weight:700;
                     text-transform:uppercase; letter-spacing:1.2px;">SCENARIO</p>
          <p style="margin:5px 0; color:#e2e8f0; font-size:1em; font-weight:600;
                    border-left:3px solid {color}; padding-left:10px;">"{scenario}"</p>
        </div>
        <div style="margin-bottom:12px;">
          <p style="margin:0; color:#8b949e; font-size:0.72em; font-weight:700;
                     text-transform:uppercase; letter-spacing:1.2px;">REASONING</p>
          <p style="margin:5px 0; color:#c9d1d9; font-weight:500; line-height:1.6;">{reasoning}</p>
        </div>
        <details style="margin-top:10px; border-top:1px solid {color}20; padding-top:10px;">
          <summary style="cursor:pointer; color:#8b949e; font-size:0.82em; font-weight:600;
                          user-select:none;">
            🔍 Retrieved Context (click to expand)
          </summary>
          <div style="font-size:0.82em; color:#8b949e; margin-top:8px;
                      max-height:300px; overflow-y:auto; white-space:pre-wrap;
                      background:#0d1117; padding:12px; border-radius:6px;
                      border:1px solid #30363d; font-family:'Consolas',monospace;">
            {context_html}
          </div>
        </details>
      </div>
    </div>"""

# ---------------------------------------------------------------------------
# Audit işleme
# ---------------------------------------------------------------------------
# Mod açıklamaları:
#   Full         — HyDE rewrite + LLM verdict  (~2000 token/senaryo)
#   Fast         — Sadece semantic search + LLM verdict  (~800 token/senaryo)
#   Context Only — Sadece semantic search, LLM YOK  (0 token)

MODE_LABELS = {
    "🔍 Full  (HyDE + LLM)":          "full",
    "⚡ Fast  (No HyDE + LLM)":        "fast",
    "🗂️ Context Only  (No LLM — 0 token)": "context",
}

def _make_context_card(index: int, scenario: str, context: str) -> str:
    """LLM çağrısı olmadan sadece retrieved context'i gösterir."""
    context_html = context.replace("\n", "<br>")

    return f"""
    <div style="border:1px solid #6366f150; border-left:5px solid #6366f1; border-radius:10px;
                margin-bottom:20px; background:#13102a;
                font-family:'Segoe UI',sans-serif;
                box-shadow:0 4px 16px rgba(0,0,0,0.4);">
      <div style="padding:20px;">
        <div style="font-weight:900; font-size:1.1em; color:#818cf8; margin-bottom:12px;">
          🗂️ CASE {index}: RETRIEVED CONTEXT
        </div>
        <div style="margin-bottom:12px;">
          <p style="margin:0; color:#8b949e; font-size:0.72em; font-weight:700;
                     text-transform:uppercase; letter-spacing:1.2px;">QUERY</p>
          <p style="margin:5px 0; color:#e2e8f0; font-size:1em; font-weight:600;
                    border-left:3px solid #6366f1; padding-left:10px;">"{scenario}"</p>
        </div>
        <div style="font-size:0.82em; color:#8b949e; margin-top:8px;
                    max-height:400px; overflow-y:auto; white-space:pre-wrap;
                    background:#0d1117; padding:12px; border-radius:6px;
                    border:1px solid #30363d; font-family:'Consolas',monospace;">
          {context_html}
        </div>
      </div>
    </div>"""


def run_audit(input_text, mode_label, progress=gr.Progress()):
    scenarios = [line.strip() for line in input_text.splitlines() if line.strip()]
    if not scenarios:
        yield "<p>Please enter at least one scenario.</p>"
        return

    mode = MODE_LABELS.get(mode_label, "full")
    retriever_client = groq_client if mode == "full" else None

    full_html = ""
    total = len(scenarios)

    mode_hint = {
        "full":    "HyDE rewrite + LLM verdict",
        "fast":    "Semantic search + LLM verdict (no HyDE)",
        "context": "Semantic search only — no LLM called",
    }[mode]

    for i, scenario in enumerate(scenarios):
        loading = f"""
        <div style="padding:20px; margin-bottom:20px; border:1px dashed #3b82f6;
                    border-radius:10px; background:#0f1e3a; color:#93c5fd;
                    text-align:center; font-family:'Segoe UI',sans-serif;">
          <div style="font-weight:800; font-size:1.1em; margin-bottom:8px; color:#60a5fa;">
            ⚙️ ANALYZING: CASE {i+1} / {total}
          </div>
          <div style="font-style:italic; color:#93c5fd;">"{scenario}"</div>
          <div style="margin-top:8px; font-size:0.78em; color:#4b7fc4;">{mode_hint}</div>
        </div>"""
        yield full_html + loading

        result  = retrieve(scenario, retriever_client)
        context = format_context_for_llm(result)

        if mode == "context":
            full_html += _make_context_card(i + 1, scenario, context)
        else:
            verdict, reasoning = get_llm_verdict(scenario, context)
            full_html += make_card(i + 1, scenario, verdict, reasoning, context)

        yield full_html

# ---------------------------------------------------------------------------
# Indexing pipeline yardımcıları
# ---------------------------------------------------------------------------
def _get_db_stats() -> dict:
    """ChromaDB'deki mevcut döküman sayısını döner."""
    try:
        import chromadb
        from chromadb.utils import embedding_functions
        db_path = PIPELINE_DIR / "data" / "chroma_db"
        client = chromadb.PersistentClient(path=str(db_path))
        ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
        col = client.get_collection(name="aastp_multivector_v1", embedding_function=ef)
        count = col.count()
        meta = col.get(limit=1, include=["metadatas"])
        types = {}
        for m in meta.get("metadatas", []):
            t = m.get("type", "unknown")
            types[t] = types.get(t, 0) + 1
        return {"count": count, "types": types, "error": None}
    except Exception as e:
        return {"count": 0, "types": {}, "error": str(e)}


def _render_pipeline_panel(
    steps: list[dict],
    logs: list[str],
    progress_pct: int,
    done: bool = False,
    error: str | None = None,
) -> str:
    """
    Pipeline durum panelini HTML olarak üretir.

    steps: [{"label": str, "status": "done"|"active"|"pending"|"error"}]
    """
    status_icon = {"done": "✅", "active": "⏳", "pending": "○", "error": "❌"}
    status_color = {
        "done":    "#22c55e",
        "active":  "#3b82f6",
        "pending": "#4b5563",
        "error":   "#ef4444",
    }
    status_bg = {
        "done":    "#0f2a1a",
        "active":  "#0f1e3a",
        "pending": "#161b22",
        "error":   "#2a0f0f",
    }

    # Progress bar
    bar_color = "#ef4444" if error else ("#22c55e" if done else "#3b82f6")
    progress_html = f"""
    <div style="margin-bottom:20px;">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
        <span style="font-size:0.82em; font-weight:700; color:#8b949e; text-transform:uppercase; letter-spacing:.5px;">
          Overall Progress
        </span>
        <span style="font-size:0.85em; font-weight:800; color:{bar_color};">{progress_pct}%</span>
      </div>
      <div style="height:8px; background:#21262d; border-radius:99px; overflow:hidden;">
        <div style="height:100%; width:{progress_pct}%; background:{bar_color};
                    border-radius:99px; transition:width .4s ease;
                    box-shadow: 0 0 8px {bar_color}80;"></div>
      </div>
    </div>"""

    # Adım listesi
    steps_html = ""
    for step in steps:
        s = step["status"]
        icon  = status_icon.get(s, "○")
        color = status_color.get(s, "#9ca3af")
        bg    = status_bg.get(s, "#f9fafb")
        detail = f'<div style="font-size:0.78em; color:#8b949e; margin-top:2px;">{step["detail"]}</div>' if step.get("detail") else ""
        steps_html += f"""
        <div style="display:flex; align-items:flex-start; gap:12px; padding:10px 14px;
                    margin-bottom:6px; border-radius:8px; background:{bg};
                    border-left:4px solid {color};">
          <span style="font-size:1.1em; line-height:1.4;">{icon}</span>
          <div>
            <div style="font-weight:700; color:#c9d1d9; font-size:0.9em;">{step['label']}</div>
            {detail}
          </div>
        </div>"""

    # Log kutusu
    log_lines = logs[-18:]  # son 18 satır
    log_html_inner = "\n".join(
        f'<div style="padding:2px 0; border-bottom:1px solid #21262d; color:{"#f87171" if l.startswith("✗") or "hata" in l.lower() else "#4ade80" if "✅" in l else "#c9d1d9"};">'
        f'{l}</div>'
        for l in log_lines
    )
    log_html = f"""
    <div style="margin-top:16px;">
      <div style="font-size:0.78em; font-weight:700; color:#8b949e; text-transform:uppercase;
                  letter-spacing:.5px; margin-bottom:6px;">Processing Log</div>
      <div style="background:#0d1117; border:1px solid #30363d; border-radius:8px;
                  padding:12px; max-height:220px; overflow-y:auto;
                  font-family:'Consolas','Monaco',monospace; font-size:0.8em; line-height:1.6;">
        {log_html_inner or '<span style="color:#4b5563;">Başlatılıyor...</span>'}
      </div>
    </div>"""

    # Son mesaj bandı
    if error:
        banner = f'<div style="margin-top:16px; padding:14px; background:#2a0f0f; border:1px solid #ef4444; border-radius:8px; color:#fca5a5; font-weight:700;">❌ {error}</div>'
    elif done:
        banner = '<div style="margin-top:16px; padding:14px; background:#0f2a1a; border:1px solid #22c55e; border-radius:8px; color:#4ade80; font-weight:700;">🎉 Knowledge base başarıyla güncellendi! Audit sekmesinde sorgulama yapabilirsiniz.</div>'
    else:
        banner = ""

    return f"""
    <div style="font-family:'Segoe UI',sans-serif; padding:4px; color:#c9d1d9;">
      {progress_html}
      <div style="font-size:0.78em; font-weight:700; color:#8b949e; text-transform:uppercase;
                  letter-spacing:.5px; margin-bottom:8px;">Pipeline Steps</div>
      {steps_html}
      {log_html}
      {banner}
    </div>"""


def _make_steps(active: int, error_step: int = -1) -> list[dict]:
    """0-indexed active adımına göre adım listesi döner."""
    labels = [
        ("1. PDF Split",           "PDF'i 50 sayfalık chunk'lara böl"),
        ("2. MinerU OCR/Parsing",  "Her chunk'ı MinerU API ile işle (VLM modeli)"),
        ("3. Merge Chunks",        "Tüm chunk JSON'larını birleştir"),
        ("4. Semantic Assembly",   "Tabloları not ve bağlamlarıyla eşleştir"),
        ("5. ChromaDB Indexing",   "Özetleri vektörleştir ve kaydet"),
    ]
    steps = []
    for i, (label, detail) in enumerate(labels):
        if i == error_step:
            status = "error"
        elif i < active:
            status = "done"
        elif i == active:
            status = "active"
        else:
            status = "pending"
        steps.append({"label": label, "detail": detail, "status": status})
    return steps


# ---------------------------------------------------------------------------
# Indexing Pipeline — Gradio generator
# ---------------------------------------------------------------------------
def run_indexing_pipeline(pdf_file):
    logs: list[str] = []
    mineru_key = MINERU_API_KEY
    groq_key   = GROQ_API_KEY

    def log(msg: str):
        logs.append(msg)

    def render(active_step: int, pct: int, done=False, error=None, error_step=-1):
        return _render_pipeline_panel(
            _make_steps(active_step, error_step),
            logs,
            pct,
            done=done,
            error=error,
        )

    # --- Ön doğrulama ---
    if not pdf_file:
        yield render(0, 0, error="PDF dosyası seçilmedi.")
        return
    if not mineru_key:
        yield render(0, 0, error="MINERU_API_KEY tanımlı değil.")
        return
    if not groq_key:
        yield render(0, 0, error="GROQ_API_KEY ortam değişkeni tanımlı değil.")
        return

    pdf_path = Path(pdf_file.name)
    if not pdf_path.exists():
        yield render(0, 0, error=f"Dosya bulunamadı: {pdf_path}")
        return

    # Çıktı dizinleri — yüklenen PDF'e özel klasör
    safe_stem  = re.sub(r"[^\w\-]", "_", pdf_path.stem)[:40]
    run_dir    = PIPELINE_DIR / "input" / "chunks" / safe_stem
    merged_json = PIPELINE_DIR / "input" / f"{safe_stem}_content_list.json"
    images_dir = PIPELINE_DIR / "input" / "images"
    run_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    # ── ADIM 1: PDF Split ─────────────────────────────────────────────────
    log(f"PDF yüklendi: {pdf_path.name}")
    yield render(0, 5)

    try:
        chunks = mb.get_chunks(pdf_path, mb.CHUNK_SIZE)
        total_pages = sum(e - s for s, e in chunks)
        log(f"Toplam sayfa: {total_pages} | Chunk sayısı: {len(chunks)}")
        yield render(0, 10)
    except Exception as e:
        yield render(0, 10, error=f"PDF okunamadı: {e}", error_step=0)
        return

    # ── ADIM 2: MinerU ────────────────────────────────────────────────────
    log("MinerU işleme başlıyor...")
    yield render(1, 12)

    chunks_done = 0
    chunks_total = len(chunks)

    def mineru_log(msg: str):
        log(msg)

    failed_chunks = []
    for i, (start, end) in enumerate(chunks):
        prefix   = f"pages_{start+1:03d}-{end:03d}"
        out_file = run_dir / f"{prefix}_content_list.json"

        pct = 12 + int((i / chunks_total) * 48)  # 12% → 60%

        if out_file.exists():
            log(f"[{i+1}/{chunks_total}] {prefix} — zaten mevcut ✓")
            chunks_done += 1
            steps = _make_steps(1)
            steps[1]["detail"] = f"Chunk {i+1}/{chunks_total} — atlandı (zaten mevcut)"
            yield _render_pipeline_panel(steps, logs, pct)
            continue

        log(f"[{i+1}/{chunks_total}] {prefix} işleniyor...")
        steps = _make_steps(1)
        steps[1]["detail"] = f"Chunk {i+1}/{chunks_total} — Catbox'a yükleniyor..."
        yield _render_pipeline_panel(steps, logs, pct)

        try:
            pdf_bytes = mb.extract_chunk_bytes(pdf_path, start, end)
            log(f"  Chunk boyutu: {len(pdf_bytes)//1024} KB")

            steps[1]["detail"] = f"Chunk {i+1}/{chunks_total} — Catbox upload ({len(pdf_bytes)//1024} KB)..."
            yield _render_pipeline_panel(steps, logs, pct)

            pub_url = mb.upload_catbox(pdf_bytes, f"{prefix}.pdf")
            if not pub_url:
                log(f"  ✗ Catbox yüklemesi başarısız")
                failed_chunks.append(prefix)
                continue
            log(f"  URL alındı")

            task_id = mb.submit_task(pub_url, mineru_key.strip())
            if not task_id:
                log(f"  ✗ MinerU görevi gönderilemedi")
                failed_chunks.append(prefix)
                continue
            log(f"  Task: {task_id[:18]}...")

            steps[1]["detail"] = f"Chunk {i+1}/{chunks_total} — MinerU işliyor (~2-4 dk)..."
            yield _render_pipeline_panel(steps, logs, pct)

            # poll_task her 6 saniyede log üretir → her update'de yield et
            zip_url = None
            headers = {"Authorization": f"Bearer {mineru_key.strip()}"}
            poll_url = f"https://mineru.net/api/v4/extract/task/{task_id}"
            deadline = time.time() + 900
            elapsed  = 0
            import requests as _req
            while time.time() < deadline:
                time.sleep(6)
                elapsed += 6
                try:
                    r = _req.get(poll_url, headers=headers, timeout=15).json()
                    state = r.get("data", {}).get("state", "unknown")
                    log(f"  MinerU [{state}] +{elapsed}s")
                    steps[1]["detail"] = f"Chunk {i+1}/{chunks_total} — MinerU [{state}] ({elapsed}s geçti)"
                    yield _render_pipeline_panel(steps, logs, pct)
                    if state == "done":
                        zip_url = r["data"].get("full_zip_url")
                        break
                    if state == "failed":
                        log(f"  ✗ Görev başarısız")
                        break
                except Exception as pe:
                    log(f"  Poll hatası: {pe}")

            if not zip_url:
                failed_chunks.append(prefix)
                continue

            result = mb.download_chunk(zip_url, run_dir, prefix, images_dir=images_dir)
            if result:
                log(f"  ✅ {result.name} ({sum(1 for _ in open(result))} satır)")
                chunks_done += 1
            else:
                log(f"  ✗ JSON indirilemedi")
                failed_chunks.append(prefix)

        except Exception as e:
            log(f"  ✗ Hata: {e}")
            failed_chunks.append(prefix)

        if i < chunks_total - 1:
            time.sleep(3)

    if chunks_done == 0:
        yield render(1, 60, error="Hiçbir chunk işlenemedi. MinerU API anahtarını kontrol edin.", error_step=1)
        return

    # ── ADIM 3: Merge ─────────────────────────────────────────────────────
    log("Chunk'lar birleştiriliyor...")
    yield render(2, 62)

    total_items = mb.merge_chunks(run_dir, merged_json)
    if total_items == 0:
        yield render(2, 65, error="Birleştirme başarısız: JSON içeriği okunamadı.", error_step=2)
        return
    log(f"Birleştirildi: {total_items} öğe → {merged_json.name}")
    yield render(2, 70)

    # ── ADIM 4: Semantic Assembly ──────────────────────────────────────────
    log("Semantik ünite oluşturma başlıyor...")
    yield render(3, 72)

    try:
        units = assemble_semantic_units(str(merged_json))
        out_dir = PIPELINE_DIR / "data" / "semantic_units"
        save_semantic_units(units, out_dir)
        log(f"Tablo üniteleri: {len(units)} adet")
        yield render(3, 82)
    except Exception as e:
        yield render(3, 82, error=f"Assembler hatası: {e}", error_step=3)
        return

    # Text chunk'ları da çalıştır
    chunks_file = PIPELINE_DIR / "data" / "text_chunks" / "text_chunks.json"
    if not chunks_file.exists():
        log("Uyarı: text_chunks.json bulunamadı, sadece tablolar indekslenecek.")
        text_chunks = []
    else:
        with open(chunks_file, encoding="utf-8") as f:
            text_chunks = json.load(f)
        log(f"Text chunk: {len(text_chunks)} adet")

    # ── ADIM 5: ChromaDB Indexing ──────────────────────────────────────────
    log("ChromaDB indeksleme başlıyor (Groq özetleme)...")
    yield render(4, 84)

    try:
        os.environ["GROQ_API_KEY"] = groq_key.strip()
        run_indexing(units, text_chunks)
        log("✅ ChromaDB güncellendi")
        yield render(4, 100, done=True)
    except Exception as e:
        yield render(4, 95, error=f"İndeksleme hatası: {e}", error_step=4)
        return


# ---------------------------------------------------------------------------
# Veritabanı durum kartı
# ---------------------------------------------------------------------------
def get_db_status_html() -> str:
    stats = _get_db_stats()
    base = "font-family:'Segoe UI',sans-serif; border-radius:8px; padding:14px;"
    if stats["error"]:
        return f"""<div style="{base} background:#2d1b00; border:1px solid #d97706; color:#fcd34d;">
            <b>⚠️ Knowledge Base:</b> Henüz oluşturulmamış veya erişilemiyor.<br>
            <span style="font-size:0.85em; color:#fbbf24;">PDF indekslemesi yaparak başlayın.</span>
        </div>"""
    types_str = ', '.join(f"{v} {k}" for k, v in stats['types'].items())
    return f"""<div style="{base} background:#0f2a1a; border:1px solid #16a34a; color:#86efac;">
        <b>✅ Knowledge Base:</b> <span style="color:#4ade80; font-weight:800;">{stats['count']}</span> döküman mevcut
        <span style="font-size:0.82em; color:#6ee7b7; margin-left:10px;">({types_str})</span>
    </div>"""


# ---------------------------------------------------------------------------
# CSS — Dark military theme
# ---------------------------------------------------------------------------
CSS = """
/* ── Global background ── */
body, .gradio-container, .gradio-container > .main, .contain {
    background-color: #0d1117 !important;
    color: #e2e8f0 !important;
}

/* ── Tab bar ── */
.tabs > .tab-nav {
    background: #161b22 !important;
    border-bottom: 2px solid #30363d !important;
}
.tabs > .tab-nav > button {
    color: #8b949e !important;
    font-weight: 700 !important;
    border-bottom: 2px solid transparent !important;
}
.tabs > .tab-nav > button.selected {
    color: #58a6ff !important;
    border-bottom: 2px solid #58a6ff !important;
    background: transparent !important;
}

/* ── Panels / blocks ── */
.block, .form, .box {
    background-color: #161b22 !important;
    border: 1px solid #30363d !important;
    border-radius: 10px !important;
}

/* ── Labels ── */
.gradio-container label,
.gradio-container span.label-wrap,
.gradio-container .label-wrap span,
.gradio-container .svelte-1ipelgc {
    color: #c9d1d9 !important;
    font-weight: 700 !important;
}

/* ── Textareas & inputs ── */
textarea, input[type="text"], input[type="password"] {
    background-color: #0d1117 !important;
    color: #e2e8f0 !important;
    border: 1px solid #30363d !important;
    border-radius: 8px !important;
    font-family: 'Consolas', 'Monaco', monospace !important;
}
textarea:focus, input:focus {
    border-color: #58a6ff !important;
    box-shadow: 0 0 0 2px rgba(88,166,255,0.15) !important;
    outline: none !important;
}

/* ── Audit input special styling ── */
#audit_input textarea {
    min-height: 240px !important;
    font-size: 0.9em !important;
    line-height: 1.6 !important;
}

/* ── Buttons ── */
button.primary, button[variant="primary"] {
    background: linear-gradient(135deg, #1d4ed8, #2563eb) !important;
    color: #fff !important;
    border: none !important;
    border-radius: 8px !important;
    font-weight: 800 !important;
    letter-spacing: 0.5px !important;
    box-shadow: 0 4px 14px rgba(37,99,235,0.4) !important;
    transition: all .2s ease !important;
}
button.primary:hover {
    background: linear-gradient(135deg, #2563eb, #3b82f6) !important;
    box-shadow: 0 6px 20px rgba(37,99,235,0.5) !important;
}
button.secondary {
    background: #21262d !important;
    color: #c9d1d9 !important;
    border: 1px solid #30363d !important;
    border-radius: 6px !important;
}
button.secondary:hover {
    background: #30363d !important;
    border-color: #58a6ff !important;
    color: #58a6ff !important;
}

/* ── Markdown text ── */
.prose, .prose p, .prose li, .prose h1, .prose h2, .prose h3, .prose h4 {
    color: #c9d1d9 !important;
}
.prose h3 { color: #58a6ff !important; }
.prose strong { color: #e2e8f0 !important; }

/* ── File upload ── */
.file-preview, .upload-container {
    background: #161b22 !important;
    border: 2px dashed #30363d !important;
    border-radius: 8px !important;
    color: #8b949e !important;
}

/* ── Radio buttons ── */
.gradio-radio label span { color: #c9d1d9 !important; }

/* ── Scrollbars ── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #161b22; }
::-webkit-scrollbar-thumb { background: #30363d; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #58a6ff; }
"""

# ---------------------------------------------------------------------------
# Arayüz
# ---------------------------------------------------------------------------
with gr.Blocks(theme=gr.themes.Base(), css=CSS, title="AASTP-1 AI Auditor") as demo:
    gr.HTML("""
    <div style="
        background: linear-gradient(135deg, #0d1117 0%, #161b22 60%, #1c2333 100%);
        border-bottom: 2px solid #21262d;
        padding: 28px 32px 20px 32px;
        margin-bottom: 4px;
    ">
      <div style="display:flex; align-items:center; gap:16px; margin-bottom:6px;">
        <div style="
            background: linear-gradient(135deg, #1d4ed8, #2563eb);
            border-radius: 12px; padding: 10px 14px;
            font-size: 1.6em; line-height:1; box-shadow: 0 4px 12px rgba(37,99,235,0.4);
        ">🛡️</div>
        <div>
          <h1 style="margin:0; font-size:1.6em; font-weight:900; color:#e2e8f0;
                     font-family:'Segoe UI',sans-serif; letter-spacing:-0.5px;">
            AASTP-1 Smart Ammunition Audit System
          </h1>
          <p style="margin:4px 0 0 0; font-size:0.85em; color:#58a6ff; font-weight:600;
                    font-family:'Segoe UI',sans-serif; letter-spacing:1px; text-transform:uppercase;">
          </p>
        </div>
      </div>
    </div>
    """)

    with gr.Tabs():

        # ═══════════════════════════════════════════════════════════════════
        # TAB 1 — Audit
        # ═══════════════════════════════════════════════════════════════════
        with gr.Tab("🔍 Audit"):
            with gr.Row():
                with gr.Column(scale=1):
                    input_box = gr.Textbox(
                        label="Audit Scenarios (one per line)",
                        lines=8,
                        placeholder="Ex: Found Group B stored with Group D...",
                        value=TEST_SET_MATRIX,
                        elem_id="audit_input",
                    )
                    gr.Markdown("### 🔽 Ready-to-Use Test Batches")
                    with gr.Row():
                        btn_matrix   = gr.Button("📂 Matrix Rules (Test 1)",       size="sm")
                        btn_chemical = gr.Button("🧪 Chemical Rules (Test 2)",     size="sm")
                        btn_complex  = gr.Button("🧩 Complex Scenarios (Test 3)",  size="sm")

                    btn_matrix.click(fn=lambda: TEST_SET_MATRIX,   inputs=None, outputs=input_box)
                    btn_chemical.click(fn=lambda: TEST_SET_CHEMICAL, inputs=None, outputs=input_box)
                    btn_complex.click(fn=lambda: TEST_SET_COMPLEX,  inputs=None, outputs=input_box)

                    gr.Markdown("### ⚙️ Mode")
                    mode_radio = gr.Radio(
                        choices=list(MODE_LABELS.keys()),
                        value="🔍 Full  (HyDE + LLM)",
                        label="Retrieval & Inference Mode",
                        info="Context Only = 0 token, retrieval kalitesini test etmek için",
                    )
                    gr.HTML("""
                    <div style="font-size:0.78em; color:#6b7280; background:#f8fafc;
                                border:1px solid #e2e8f0; border-radius:6px; padding:8px 10px;
                                line-height:1.7; margin-top:4px;">
                      <b>Full:</b> ~2000 tok/senaryo &nbsp;|&nbsp;
                      <b>Fast:</b> ~800 tok/senaryo &nbsp;|&nbsp;
                      <b>Context Only:</b> 0 tok — LLM çağrısı yok
                    </div>""")

                    audit_btn = gr.Button("🚀 START AUDIT", variant="primary", size="lg")

                with gr.Column(scale=2):
                    output_html = gr.HTML(label="🔍 Audit Report & Evidence")

            audit_btn.click(fn=run_audit, inputs=[input_box, mode_radio], outputs=output_html)

        # ═══════════════════════════════════════════════════════════════════
        # TAB 2 — PDF Indexing
        # ═══════════════════════════════════════════════════════════════════
        with gr.Tab("📦 Index New Document"):
            gr.Markdown("""
### Build or Update the Knowledge Base
Upload a PDF document to process it through the full indexing pipeline:
**MinerU OCR → Semantic Assembly → ChromaDB Vector Index**
""")

            with gr.Row():
                # ── Sol kolon: Girişler ──────────────────────────────────
                with gr.Column(scale=1, min_width=340):

                    db_status_box = gr.HTML(value=get_db_status_html)

                    gr.Markdown("---")
                    gr.Markdown("#### 📄 Document")

                    pdf_input = gr.File(
                        label="Upload PDF",
                        file_types=[".pdf"],
                        type="filepath",
                    )

                    gr.Markdown("---")
                    gr.Markdown("""
<div style="font-size:0.82em; color:#6b7280; line-height:1.7;">
<b>ℹ️ What happens when you click Start:</b><br>
1. PDF is split into 50-page chunks<br>
2. Each chunk is sent to MinerU for OCR & table extraction<br>
3. Results are merged into a single document<br>
4. Tables & text are assembled with full context<br>
5. Groq LLM generates summaries for vector search<br>
6. Everything is indexed to ChromaDB<br><br>
<b>⏱ Estimated time:</b> ~3–5 min per 50-page chunk
</div>
""")

                    start_btn = gr.Button(
                        "🚀  Start Indexing",
                        variant="primary",
                        size="lg",
                    )

                # ── Sağ kolon: İlerleme paneli ───────────────────────────
                with gr.Column(scale=2):
                    gr.Markdown("#### 📊 Pipeline Status")
                    progress_panel = gr.HTML(
                        value=_render_pipeline_panel(
                            _make_steps(-1),  # tüm adımlar pending
                            [],
                            0,
                        )
                    )

            start_btn.click(
                fn=run_indexing_pipeline,
                inputs=[pdf_input],
                outputs=progress_panel,
            )

if __name__ == "__main__":
    print("🚀 http://127.0.0.1:7860")
    demo.queue().launch(share=False)
