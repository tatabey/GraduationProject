"""
FastAPI sunucusu — Standart Uygunluk Denetim Sistemi
Çalıştırmak için:
    python3 system/server.py
"""

import base64
import os
import queue
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from config import MINERU_API_KEY as _DEFAULT_MINERU, DATA_DIR, ERROR_VERDICT
from pipeline.kb_builder import build_kb, list_kbs, delete_kb as _delete_kb
from pipeline.report_parser import parse_report
from pipeline.auditor import audit_items

KB_DIR = DATA_DIR / "kbs"
KB_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Denetim Sistemi")
templates = Jinja2Templates(directory=str(ROOT / "templates"))

# ── İş kuyrukları (job_id → {logs, status, result}) ──────────────────────
_jobs: dict[str, dict] = {}


# ── HTML üreticiler ────────────────────────────────────────────────────────
VERDICT_CFG = {
    "UYGUN"             : ("#15803d", "#f0fdf4", "#bbf7d0", "#16a34a", "✓"),
    "UYGUN DEĞİL"       : ("#b91c1c", "#fef2f2", "#fecaca", "#dc2626", "✗"),
    "DEĞERLENDİRİLEMEDİ": ("#475569", "#f8fafc", "#e2e8f0", "#64748b", "—"),
}


def render_kb_list() -> str:
    kbs = list_kbs(KB_DIR)
    if not kbs:
        return """
        <div class="card flex flex-col items-center justify-center py-14 text-center">
          <svg class="w-12 h-12 text-slate-200 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                  d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"/>
          </svg>
          <p class="text-sm font-semibold text-slate-400">Henüz bilgi tabanı yok</p>
          <p class="text-xs text-slate-300 mt-1">Soldan PDF yükleyerek başlayın</p>
        </div>"""
    rows = ""
    for kb in kbs:
        kb_attr = kb["kb_name"].replace('"', "&quot;")
        rows += f"""
        <div class="kb-row relative rounded-2xl overflow-hidden" data-kb="{kb_attr}">
          <!-- Kaydırınca açığa çıkan silme butonu (iOS tarzı) -->
          <button type="button" onclick="confirmKbDelete(this)" title="Bilgi tabanını sil"
                  class="absolute inset-y-0 right-0 w-20 bg-red-500 hover:bg-red-600
                         flex flex-col items-center justify-center gap-1 text-white transition-colors">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
            <span class="text-xs font-bold">Sil</span>
          </button>
          <div class="kb-card-inner card relative flex items-center gap-5 px-5 py-4
                      hover:border-indigo-300 hover:shadow-md duration-150"
               style="transition:transform .25s ease; touch-action:pan-y;">
            <div class="w-11 h-11 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center flex-shrink-0">
              <svg class="w-5 h-5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                      d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4"/>
              </svg>
            </div>
            <div class="flex-1 min-w-0">
              <div class="font-bold text-slate-800 text-sm">{kb['kb_name']}</div>
              <div class="text-xs text-slate-400 mt-0.5 truncate">{kb.get('pdf','—')} · {kb.get('created_at','')}</div>
            </div>
            <div class="flex items-center gap-4 flex-shrink-0">
              <div class="text-center">
                <div class="text-xl font-extrabold text-emerald-600">{kb.get('tables',0)}</div>
                <div class="text-xs text-slate-400">Tablo</div>
              </div>
              <div class="w-px h-8 bg-slate-100"></div>
              <div class="text-center">
                <div class="text-xl font-extrabold text-indigo-500">{kb.get('chunks',0)}</div>
                <div class="text-xs text-slate-400">Chunk</div>
              </div>
              <div class="w-px h-8 bg-slate-100"></div>
              <div class="text-center">
                <div class="text-xl font-extrabold text-slate-700">{kb.get('total',0)}</div>
                <div class="text-xs text-slate-400">Toplam</div>
              </div>
            </div>
          </div>
        </div>"""
    return rows


def _table_btn(s: dict, kb_name: str = "") -> str:
    """Tablo kaynağı için tıklanabilir önizleme butonu üretir."""
    name_safe  = s["name"].replace("'", "\\'").replace('"', '&quot;')
    notes_b64  = base64.b64encode(s["notes"].encode()).decode()  if s.get("notes")  else ""
    legend_b64 = base64.b64encode(s["legend"].encode()).decode() if s.get("legend") else ""

    # Görsel URL — img_path "images/xxx.jpg" formatında gelir
    img_path = s.get("img_path", "")
    if img_path and kb_name:
        img_filename = Path(img_path).name
        img_url = f"/table-img/{kb_name}/{img_filename}"
    else:
        img_url = ""

    img_url_safe = img_url.replace("'", "\\'")
    return (
        f'<button type="button" '
        f"onclick=\"openTableModal('{name_safe}','{img_url_safe}','{notes_b64}','{legend_b64}')\" "
        f'class="inline-flex items-center gap-1 text-xs font-medium px-2.5 py-1 rounded '
        f'bg-indigo-50 text-indigo-700 border border-indigo-200 '
        f'hover:bg-indigo-100 hover:border-indigo-400 transition-colors cursor-pointer">'
        f'⊞ {s["name"][:40]}'
        f'<svg class="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
        f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
        f'd="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/></svg>'
        f'</button>'
    )


def render_verdict_card(r: dict, kb_name: str = "") -> str:
    text_col, bg_col, border_col, accent, sym = VERDICT_CFG.get(
        r["verdict"], ("#475569", "#f8fafc", "#e2e8f0", "#94a3b8", "·")
    )
    # 3+3 retrieval: kaynaklar modalite gruplarıyla etiketlenir
    tbl_btns = "".join(_table_btn(s, kb_name) for s in r["sources"] if s["type"] == "table")
    txt_tags = "".join(
        f'<span class="inline-flex items-center gap-1 text-xs text-slate-500 '
        f'bg-slate-100 border border-slate-200 rounded px-2 py-0.5">'
        f'¶ {s["name"][:38]}</span>'
        for s in r["sources"] if s["type"] != "table"
    )
    sources = ""
    if tbl_btns:
        sources += (
            '<div class="flex flex-wrap items-center gap-2 mb-2">'
            '<span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider '
            'w-12 flex-shrink-0">Tablo</span>' + tbl_btns + "</div>"
        )
    if txt_tags:
        sources += (
            '<div class="flex flex-wrap items-center gap-2">'
            '<span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider '
            'w-12 flex-shrink-0">Metin</span>' + txt_tags + "</div>"
        )
    return f"""
    <div class="bg-white rounded-2xl border border-slate-200 overflow-hidden mb-3 shadow-sm transition-shadow hover:shadow-md"
         style="border-left:4px solid {accent};">
      <div class="flex items-start gap-4 px-5 py-4">
        <div class="w-9 h-9 rounded-xl flex-shrink-0 flex items-center justify-center font-extrabold text-sm"
             style="background:{bg_col};color:{text_col};border:2px solid {border_col};">
          {r['item_no']:02d}
        </div>
        <p class="flex-1 text-sm leading-relaxed text-slate-700 pt-1">{r['text']}</p>
        <span class="flex-shrink-0 font-bold text-sm px-3 py-1.5 rounded-full self-start"
              style="background:{bg_col};color:{text_col};border:2px solid {border_col};">
          {sym} {r['verdict']}
        </span>
      </div>
      <details class="group">
        <summary class="cursor-pointer flex items-center gap-2 px-5 py-3
                        border-t border-slate-100 bg-slate-50/80 text-sm font-semibold
                        text-slate-500 hover:text-indigo-700 select-none list-none
                        hover:bg-indigo-50 transition-all">
          <svg class="w-4 h-4 transition-transform group-open:rotate-90 flex-shrink-0"
               fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"/>
          </svg>
          Gerekçe &amp; Kaynaklar
        </summary>
        <div class="px-5 py-4 border-t border-slate-100 bg-white">
          <p class="text-sm text-slate-600 leading-relaxed mb-4">{r['reasoning']}</p>
          <div>{sources}</div>
        </div>
      </details>
    </div>"""


def render_results(results: list, kb_name: str = "") -> str:
    if not results:
        return ""
    counts = {v: 0 for v in VERDICT_CFG}
    for r in results:
        if r["verdict"] in counts:
            counts[r["verdict"]] += 1
    total = len(results)
    # Uygunluk oranı yalnız değerlendirilen maddeler üzerinden (teknik aksaklık hariç)
    evaluated = counts["UYGUN"] + counts["UYGUN DEĞİL"]
    pct = round(counts["UYGUN"] / evaluated * 100) if evaluated else 0

    stat_cards = ""
    for verdict, cnt in counts.items():
        tc, bg, border, acc, sym = VERDICT_CFG[verdict]
        stat_cards += f"""
        <div class="text-center px-5 py-3 rounded-xl border-2"
             style="background:{bg}; border-color:{border};">
          <div class="text-2xl font-bold" style="color:{tc};">{cnt}</div>
          <div class="text-xs font-medium mt-1" style="color:{acc};">{sym} {verdict}</div>
        </div>"""

    summary = f"""
    <div class="bg-white rounded-xl border border-slate-200 p-5 mb-5">
      <div class="flex flex-wrap gap-3 mb-4">{stat_cards}</div>
      <div class="flex items-center justify-between mb-2">
        <span class="text-sm text-slate-500">Genel Uygunluk</span>
        <span class="text-sm font-bold text-emerald-600">{pct}%</span>
      </div>
      <div class="h-2 bg-slate-100 rounded-full overflow-hidden">
        <div class="h-full bg-emerald-400 rounded-full transition-all"
             style="width:{pct}%"></div>
      </div>
      <p class="text-xs text-slate-400 mt-2">
        {total} madde · {counts['UYGUN']} uygun · {counts['UYGUN DEĞİL']} ihlal{f" · {counts['DEĞERLENDİRİLEMEDİ']} değerlendirilemedi" if counts['DEĞERLENDİRİLEMEDİ'] else ""}
      </p>
    </div>"""

    cards = "".join(render_verdict_card(r, kb_name) for r in results)
    return summary + cards


# ── Tablo görseli endpoint ────────────────────────────────────────────────
@app.get("/table-img/{kb_name}/{filename}")
async def table_image(kb_name: str, filename: str):
    img_path = KB_DIR / kb_name / "images" / filename
    if not img_path.exists():
        return HTMLResponse("Not found", status_code=404)
    return FileResponse(str(img_path))


# ── Rotalar ────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "kb_list_html": render_kb_list(),
        "kb_choices": [kb["kb_name"] for kb in list_kbs(KB_DIR)],
    })


# ── KB: İndeksleme başlat ──────────────────────────────────────────────────
@app.post("/kb/index", response_class=HTMLResponse)
async def kb_index(
    kb_name: str = Form(""),
    groq_key: str = Form(""),
    skip_mineru: bool = Form(False),
    pdf_file: Optional[UploadFile] = File(None),
    existing_json: Optional[UploadFile] = File(None),
):
    kb_name = kb_name.strip()
    if not kb_name:
        return HTMLResponse(_error_html("Bilgi tabanı adı boş olamaz."))
    if not skip_mineru and (not pdf_file or not pdf_file.filename):
        return HTMLResponse(_error_html("Lütfen bir PDF dosyası seçin."))
    if skip_mineru and (not existing_json or not existing_json.filename):
        return HTMLResponse(_error_html("Lütfen JSON dosyasını seçin."))

    pdf_name = (pdf_file.filename if pdf_file and pdf_file.filename
                else existing_json.filename if existing_json and existing_json.filename
                else "—")
    job_id = uuid.uuid4().hex[:10]
    _jobs[job_id] = {
        "logs": [], "status": "running", "progress": 0, "step": "Hazırlanıyor...",
        "pdf_name": pdf_name, "kb_name_label": kb_name,
        "start_time": time.time(), "duration_sec": 0, "build_result": None,
    }

    tmp_pdf = tmp_json = None
    if pdf_file and pdf_file.filename:
        data = await pdf_file.read()
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(data); tmp.close()
        tmp_pdf = tmp.name
    if existing_json and existing_json.filename:
        data = await existing_json.read()
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.write(data); tmp.close()
        tmp_json = tmp.name

    def worker():
        try:
            def log(m):
                if m.startswith("__PROGRESS__:"):
                    parts = m.split(":", 2)
                    try:
                        _jobs[job_id]["progress"] = min(99, int(parts[1]))
                        _jobs[job_id]["step"] = parts[2] if len(parts) > 2 else ""
                    except (ValueError, IndexError):
                        pass
                else:
                    _jobs[job_id]["logs"].append(m)
            result = build_kb(
                pdf_path=Path(tmp_pdf) if tmp_pdf else Path(""),
                kb_name=kb_name,
                data_dir=KB_DIR,
                api_key=_DEFAULT_MINERU,
                log_fn=log,
                skip_mineru=skip_mineru,
                merged_json=Path(tmp_json) if tmp_json else None,
            )
            _jobs[job_id]["build_result"] = result
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["progress"] = 100
            _jobs[job_id]["step"] = "Tamamlandı"
        except Exception as e:
            _jobs[job_id]["logs"].append(f"Hata: {e}")
            _jobs[job_id]["status"] = "error"
        finally:
            _jobs[job_id]["duration_sec"] = time.time() - _jobs[job_id]["start_time"]
            if tmp_pdf and os.path.exists(tmp_pdf): os.unlink(tmp_pdf)
            if tmp_json and os.path.exists(tmp_json): os.unlink(tmp_json)

    threading.Thread(target=worker, daemon=True).start()
    return HTMLResponse(_poll_html(job_id, "kb", progress=0, step="Hazırlanıyor...",
                                   start_ms=int(_jobs[job_id]["start_time"] * 1000)))


# ── KB: Polling ────────────────────────────────────────────────────────────
@app.get("/kb/poll/{job_id}", response_class=HTMLResponse)
async def kb_poll(job_id: str):
    job = _jobs.get(job_id, {"logs": ["Bilinmeyen iş."], "status": "error", "progress": 0, "step": ""})
    log_text = "\n".join(job["logs"])
    status   = job["status"]
    progress = job.get("progress", 0)
    step     = job.get("step", "")

    if status == "running":
        start_ms = int(job.get("start_time", 0) * 1000)
        return HTMLResponse(_poll_html(job_id, "kb", log_text, progress=progress, step=step, start_ms=start_ms))

    kb_list_html = render_kb_list()
    kb_choices = [kb["kb_name"] for kb in list_kbs(KB_DIR)]
    opts = "".join(f'<option value="{k}">{k}</option>' for k in kb_choices)
    return HTMLResponse(f"""
    <div id="index-result">
      {_kb_summary_card(job)}
    </div>
    <div id="kb-list" hx-swap-oob="true">{kb_list_html}</div>
    <select id="kb-select" hx-swap-oob="true"
            name="kb_name" class="w-full border border-slate-200 rounded-lg px-3 py-2.5
                                  text-sm text-slate-700 bg-white focus:outline-none
                                  focus:ring-2 focus:ring-indigo-300 focus:border-indigo-400">{opts}</select>
    """)


# ── KB: Liste yenile ───────────────────────────────────────────────────────
@app.get("/kb/list", response_class=HTMLResponse)
async def kb_list_route():
    return HTMLResponse(render_kb_list())


# ── KB: Sil ───────────────────────────────────────────────────────────────
@app.post("/kb/delete", response_class=HTMLResponse)
async def kb_delete(kb_name: str = Form("")):
    _delete_kb(kb_name.strip(), KB_DIR)
    # Liste + denetim sekmesindeki KB seçimi (OOB) birlikte tazelenir
    opts = "".join(f'<option value="{k["kb_name"]}">{k["kb_name"]}</option>'
                   for k in list_kbs(KB_DIR))
    return HTMLResponse(render_kb_list() + f"""
    <select id="kb-select" hx-swap-oob="true"
            name="kb_name" class="inp inp-sm appearance-none pr-10 cursor-pointer">
      <option value="">— Seçin —</option>{opts}</select>""")


# ── Denetim: Başlat ────────────────────────────────────────────────────────
@app.post("/audit/run", response_class=HTMLResponse)
async def audit_run(
    kb_name: str = Form(""),
    groq_key: str = Form(""),
    report_pdf: Optional[UploadFile] = File(None),
):
    if not kb_name:
        return HTMLResponse(_error_html("Bilgi tabanı seçin."))
    if not report_pdf or not report_pdf.filename:
        return HTMLResponse(_error_html("Denetim raporu PDF'i yükleyin."))

    key = groq_key.strip()   # boşsa auditor config'deki sağlayıcı anahtarını kullanır
    kbs = list_kbs(KB_DIR)
    kb_meta = next((k for k in kbs if k["kb_name"] == kb_name), None)
    if not kb_meta:
        return HTMLResponse(_error_html(f"'{kb_name}' bilgi tabanı bulunamadı."))

    data = await report_pdf.read()
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp.write(data); tmp.close()
    tmp_path = tmp.name

    try:
        items = parse_report(Path(tmp_path))
    except Exception as e:
        os.unlink(tmp_path)
        return HTMLResponse(_error_html(f"PDF okunamadı: {e}"))

    if not items:
        os.unlink(tmp_path)
        return HTMLResponse(_error_html("PDF'de numaralı madde bulunamadı."))

    job_id = uuid.uuid4().hex[:10]
    _jobs[job_id] = {
        "logs": [], "status": "running", "results": None,
        "kb_name": kb_name, "progress": 0, "step": "Denetim başlatılıyor...",
        "report_name": report_pdf.filename, "item_count": len(items),
        "start_time": time.time(), "duration_sec": 0,
        "_job_id": job_id,
    }

    def worker():
        try:
            def log(m):
                if m.startswith("__PROGRESS__:"):
                    parts = m.split(":", 2)
                    try:
                        _jobs[job_id]["progress"] = min(99, int(parts[1]))
                        _jobs[job_id]["step"] = parts[2] if len(parts) > 2 else ""
                    except (ValueError, IndexError):
                        pass
                else:
                    _jobs[job_id]["logs"].append(m)
            results = audit_items(items, kb_meta, api_key=key or None, log_fn=log)
            _jobs[job_id]["results"] = results
            _jobs[job_id]["status"] = "done"
            _jobs[job_id]["progress"] = 100
            _jobs[job_id]["step"] = "Tamamlandı"
        except Exception as e:
            _jobs[job_id]["logs"].append(f"Hata: {e}")
            _jobs[job_id]["status"] = "error"
        finally:
            _jobs[job_id]["duration_sec"] = time.time() - _jobs[job_id]["start_time"]
            if os.path.exists(tmp_path): os.unlink(tmp_path)

    threading.Thread(target=worker, daemon=True).start()
    return HTMLResponse(_poll_html(job_id, "audit", progress=0, step="Denetim başlatılıyor...",
                                   start_ms=int(_jobs[job_id]["start_time"] * 1000)))


# ── Denetim: Polling ───────────────────────────────────────────────────────
@app.get("/audit/poll/{job_id}", response_class=HTMLResponse)
async def audit_poll(job_id: str):
    job = _jobs.get(job_id, {"logs": [], "status": "error", "results": None, "progress": 0, "step": ""})
    log_text = "\n".join(job["logs"])
    status   = job["status"]
    progress = job.get("progress", 0)
    step     = job.get("step", "")

    if status == "running":
        n     = job.get("item_count", 0)
        done  = max(0, int(progress * n / 100)) if n else 0
        step_label = f"Madde {done}/{n} analiz ediliyor..." if n else step
        start_ms = int(job.get("start_time", 0) * 1000)
        return HTMLResponse(_poll_html(job_id, "audit", log_text, progress=progress, step=step_label, start_ms=start_ms))

    results_html = render_results(job.get("results") or [], kb_name=job.get("kb_name", ""))
    return HTMLResponse(f"""
    <div id="audit-result">
      {_audit_summary_card(job)}
    </div>
    <div id="audit-results" hx-swap-oob="true">{results_html or _empty_results()}</div>
    """)


# ── Denetim: Sonuç JSON indirme ────────────────────────────────────────────
@app.get("/audit/download/{job_id}")
async def audit_download(job_id: str):
    import json as _json
    from fastapi.responses import Response
    job = _jobs.get(job_id)
    if not job or not job.get("results"):
        return HTMLResponse("Sonuç bulunamadı.", status_code=404)
    payload = _json.dumps(job["results"], ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="audit_results_{job_id}.json"'},
    )


# ── Yardımcı HTML parçaları ────────────────────────────────────────────────
def _error_html(msg: str) -> str:
    return f"""
    <div class="flex items-center gap-2 px-4 py-3 bg-red-50 border border-red-200
                rounded-lg text-sm text-red-600">
      ⚠️ {msg}
    </div>"""


def _log_box(text: str, progress: int = -1, step: str = "", footer: str = "",
             start_ms: int = 0) -> str:
    lines = text.replace("<", "&lt;").replace(">", "&gt;") if text else "Başlatılıyor…"

    progress_section = ""
    if progress >= 0:
        bar_color = "background:#22c55e" if progress >= 100 else "background:#6366f1"
        # Canlı süre sayacı: sunucu sabit başlangıç epoch'unu verir, sayfadaki
        # global tik (index.html) her saniye akıcı günceller. İşlem bitince (100)
        # sayaç durur; nihai süre özet kartında gösterilir.
        timer_html = ""
        if start_ms:
            running_attr = "" if progress >= 100 else f'data-start-ms="{start_ms}"'
            timer_html = (
                f'<span class="elapsed-timer" {running_attr} '
                f'style="font-size:13px;font-weight:700;color:#64748b;'
                f'font-variant-numeric:tabular-nums;flex-shrink:0;">⏱ 0:00</span>'
            )
        progress_section = f"""
      <div style="padding:14px 20px 12px;border-bottom:1px solid #e2e8f0;background:#fff;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <span style="font-size:13px;font-weight:600;color:#334155;
                       white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
                       flex:1;min-width:0;">{step or 'İşleniyor...'}</span>
          <div style="display:flex;align-items:center;gap:10px;flex-shrink:0;margin-left:8px;">
            {timer_html}
            <span style="font-size:13px;font-weight:700;color:#6366f1;">{'✅' if progress >= 100 else f'{progress}%'}</span>
          </div>
        </div>
        <div style="height:8px;background:#e2e8f0;border-radius:99px;overflow:hidden;">
          <div style="height:100%;border-radius:99px;transition:width .6s ease;
                      width:{progress}%;{bar_color};"></div>
        </div>
      </div>"""

    return f"""
    <div class="rounded-xl border border-slate-200 overflow-hidden shadow-sm">
      {progress_section}
      <div class="bg-slate-900">
        <div class="flex items-center gap-2 px-4 py-2.5 border-b border-slate-700">
          <div class="w-2.5 h-2.5 rounded-full bg-red-400"></div>
          <div class="w-2.5 h-2.5 rounded-full bg-yellow-400"></div>
          <div class="w-2.5 h-2.5 rounded-full bg-green-400"></div>
        </div>
        <pre id="log-content"
             class="p-4 text-sm font-mono text-emerald-400 leading-relaxed
                    max-h-40 overflow-y-auto whitespace-pre-wrap">{lines}</pre>
        {f'<div class="px-4 py-2 border-t border-slate-700 text-xs text-slate-400 font-medium">{footer}</div>' if footer else ''}
      </div>
    </div>"""


def _poll_html(job_id: str, kind: str, log_text: str = "Başlatılıyor…",
               progress: int = 0, step: str = "Hazırlanıyor...",
               start_ms: int = 0) -> str:
    endpoint = f"/{kind}/poll/{job_id}"
    elem_id = "index-result" if kind == "kb" else "audit-result"
    return f"""
    <div id="{elem_id}"
         hx-get="{endpoint}"
         hx-trigger="every 1500ms"
         hx-swap="outerHTML">
      {_log_box(log_text, progress=progress, step=step, start_ms=start_ms)}
    </div>"""


def _kb_summary_card(job: dict) -> str:
    """İndeksleme tamamlandığında gösterilen son kullanıcı odaklı özet kart."""
    result   = job.get("build_result") or {}
    dur      = int(job.get("duration_sec", 0))
    mins, s  = divmod(dur, 60)
    dur_str  = f"{mins} dakika {s} saniye" if mins else f"{s} saniye"
    pdf_name = job.get("pdf_name", "—")
    kb_label = job.get("kb_name_label", "—")
    tables   = result.get("tables", 0)
    chunks   = result.get("chunks", 0)
    total    = result.get("total", 0)
    success  = job["status"] == "done"
    log_text = "\n".join(job["logs"]).replace("<", "&lt;").replace(">", "&gt;")

    if success:
        header = """
        <div class="flex items-center gap-3 px-5 py-4 bg-emerald-50 border-b border-emerald-200">
          <div class="w-10 h-10 bg-emerald-100 rounded-full flex items-center justify-center text-xl flex-shrink-0">✅</div>
          <div>
            <p class="font-semibold text-emerald-800 text-sm">Bilgi tabanı başarıyla oluşturuldu!</p>
            <p class="text-xs text-emerald-600 mt-0.5">Belgeniz sisteme kaydedildi, denetim sekmesinden kullanıma hazır.</p>
          </div>
        </div>"""
        stats = f"""
        <div class="grid grid-cols-3 divide-x divide-slate-100 border-b border-slate-200">
          <div class="text-center px-4 py-3">
            <div class="text-2xl font-bold text-emerald-600">{tables}</div>
            <div class="text-xs text-slate-400 mt-0.5">Tablo</div>
          </div>
          <div class="text-center px-4 py-3">
            <div class="text-2xl font-bold text-indigo-500">{chunks}</div>
            <div class="text-xs text-slate-400 mt-0.5">Metin Bölümü</div>
          </div>
          <div class="text-center px-4 py-3">
            <div class="text-2xl font-bold text-slate-700">{total}</div>
            <div class="text-xs text-slate-400 mt-0.5">Toplam Kayıt</div>
          </div>
        </div>"""
        border_cls = "border-emerald-200"
    else:
        header = """
        <div class="flex items-center gap-3 px-5 py-4 bg-red-50 border-b border-red-200">
          <div class="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center text-xl flex-shrink-0">❌</div>
          <div>
            <p class="font-semibold text-red-800 text-sm">İşlem hata ile sonuçlandı.</p>
            <p class="text-xs text-red-600 mt-0.5">Ayrıntılar için aşağıdaki günlüğü inceleyin.</p>
          </div>
        </div>"""
        stats = ""
        border_cls = "border-red-200"

    meta = f"""
    <div class="px-5 py-3 border-b border-slate-100 flex flex-wrap gap-x-5 gap-y-1
                text-xs text-slate-500 bg-slate-50">
      <span>📄 {pdf_name}</span>
      <span>🗄 {kb_label}</span>
      <span>⏱ {dur_str}</span>
    </div>"""

    toggle = f"""
    <details class="group">
      <summary class="flex items-center gap-2 px-5 py-2.5 cursor-pointer select-none list-none
                      text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors">
        <svg class="w-3 h-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"/>
        </svg>
        İşlem günlüğünü göster
      </summary>
      <div class="bg-slate-900">
        <pre class="p-4 text-xs font-mono text-emerald-400 leading-relaxed
                    max-h-56 overflow-y-auto whitespace-pre-wrap">{log_text or '(günlük boş)'}</pre>
      </div>
    </details>"""

    return f"""
    <div class="rounded-xl border {border_cls} overflow-hidden shadow-sm">
      {header}{stats}{meta}{toggle}
    </div>"""


def _audit_summary_card(job: dict) -> str:
    """Denetim tamamlandığında gösterilen özet kart + JSON indirme butonu."""
    import json as _json
    results   = job.get("results") or []
    dur       = int(job.get("duration_sec", 0))
    mins, s   = divmod(dur, 60)
    dur_str   = f"{mins} dakika {s} saniye" if mins else f"{s} saniye"
    report    = job.get("report_name", "—")
    kb_label  = job.get("kb_name", "—")
    n         = len(results)
    success   = job["status"] == "done"
    job_id    = job.get("_job_id", "")
    log_text  = "\n".join(job["logs"]).replace("<", "&lt;").replace(">", "&gt;")

    from collections import Counter
    counts = Counter(r.get("verdict", "?") for r in results)
    rate_limit_warn = (
        any("rate_limit" in m.lower() or "429" in m or "api limiti" in m.lower()
            for m in job.get("logs", []))
        or counts.get(ERROR_VERDICT, 0) > 0
    )

    if success:
        header = f"""
        <div class="flex items-center gap-3 px-5 py-4 bg-indigo-50 border-b border-indigo-200">
          <div class="w-10 h-10 bg-indigo-100 rounded-full flex items-center justify-center text-xl flex-shrink-0">🔍</div>
          <div>
            <p class="font-semibold text-indigo-800 text-sm">Denetim tamamlandı!</p>
            <p class="text-xs text-indigo-600 mt-0.5">{n} madde analiz edildi. Sonuçlar sağ panelde gösteriliyor.</p>
          </div>
        </div>"""
        border_cls = "border-indigo-200"
    else:
        header = """
        <div class="flex items-center gap-3 px-5 py-4 bg-red-50 border-b border-red-200">
          <div class="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center text-xl flex-shrink-0">❌</div>
          <div>
            <p class="font-semibold text-red-800 text-sm">Denetim hata ile sonuçlandı.</p>
            <p class="text-xs text-red-600 mt-0.5">Günlüğü inceleyin.</p>
          </div>
        </div>"""
        border_cls = "border-red-200"

    VCFG = {
        "UYGUN":              ("#15803d","#f0fdf4","#16a34a","✓"),
        "UYGUN DEĞİL":        ("#b91c1c","#fef2f2","#dc2626","✗"),
        "DEĞERLENDİRİLEMEDİ": ("#475569","#f8fafc","#64748b","—"),
    }
    stat_cells = ""
    for v, (tc, bg, acc, sym) in VCFG.items():
        cnt = counts.get(v, 0)
        stat_cells += f"""
        <div class="text-center px-3 py-3 border-r border-slate-100 last:border-0">
          <div class="text-xl font-bold" style="color:{tc};">{cnt}</div>
          <div class="text-xs mt-0.5" style="color:{acc};">{sym} {v}</div>
        </div>"""

    stats = f'<div class="grid grid-cols-3 divide-x divide-slate-100 border-b border-slate-200">{stat_cells}</div>'

    warn_html = ""
    if rate_limit_warn:
        warn_html = """
        <div class="px-5 py-2.5 bg-amber-50 border-b border-amber-200 flex items-center gap-2 text-xs text-amber-700">
          ⚠️ <strong>API limiti aşıldı.</strong>
          Bazı maddeler değerlendirilemedi. Biraz bekleyip tekrar deneyin veya kendi API anahtarınızı girin.
        </div>"""

    download_btn = ""
    if results and job_id:
        download_btn = f'<a href="/audit/download/{job_id}" class="inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 transition-colors" download>⬇ Sonuçları JSON İndir</a>'

    meta = f"""
    <div class="px-5 py-3 border-b border-slate-100 flex flex-wrap items-center justify-between gap-3 bg-slate-50">
      <div class="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
        <span>📄 {report}</span>
        <span>🗄 {kb_label}</span>
        <span>⏱ {dur_str}</span>
      </div>
      {download_btn}
    </div>"""

    toggle = f"""
    <details class="group">
      <summary class="flex items-center gap-2 px-5 py-2.5 cursor-pointer select-none list-none
                      text-xs text-slate-400 hover:text-slate-600 hover:bg-slate-50 transition-colors">
        <svg class="w-3 h-3 transition-transform group-open:rotate-90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M9 5l7 7-7 7"/>
        </svg>
        İşlem günlüğünü göster
      </summary>
      <div class="bg-slate-900">
        <pre class="p-4 text-xs font-mono text-emerald-400 leading-relaxed max-h-48 overflow-y-auto whitespace-pre-wrap">{log_text or '(günlük boş)'}</pre>
      </div>
    </details>"""

    return f"""
    <div class="rounded-xl border {border_cls} overflow-hidden shadow-sm">
      {header}{warn_html}{stats}{meta}{toggle}
    </div>"""


def _empty_results() -> str:
    return """
    <div class="text-center py-20 text-slate-300">
      <div class="text-5xl mb-4">🔍</div>
      <p class="text-sm font-medium text-slate-400">Denetim sonuçları burada görünecek</p>
      <p class="text-xs text-slate-300 mt-1">KB seçip rapor yükleyin, ardından başlatın</p>
    </div>"""


# ── Model ön-ısıtma: ilk denetimde ~25-30 sn'lik model yükleme beklenmesin ──
@app.on_event("startup")
async def _warmup_models():
    def _warm():
        try:
            from config import EMBED_MODEL
            from pipeline.retriever import _get_emb_fn, _get_reranker
            _get_emb_fn(EMBED_MODEL)(["warmup"])
            rr = _get_reranker()
            if rr:
                rr.predict([("warmup", "warmup")])
            print("  🔥 Modeller hazır (embedding + reranker GPU'da).")
        except Exception as e:
            print(f"  Ön-ısıtma atlandı: {e}")
    threading.Thread(target=_warm, daemon=True).start()


# ── Başlat ─────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("\n  🚀  http://127.0.0.1:8000\n")
    uvicorn.run("server:app", host="127.0.0.1", port=8000,
                reload=True, app_dir=str(ROOT))
