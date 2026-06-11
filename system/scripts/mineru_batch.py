"""
MinerU Batch Processor
======================
PDF'i chunk'lara böler, MinerU API ile işler,
birleştirilmiş content_list.json üretir.

Import kullanımı:
    from scripts.mineru_batch import process_all, merge_chunks
"""

import io
import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import requests
from pypdf import PdfReader, PdfWriter

from config import (
    MINERU_API_KEY, MINERU_CHUNK_SIZE, MINERU_PARALLEL_CHUNKS, TIMING_LOGS,
)

MINERU_TASK_URL = "https://mineru.net/api/v4/extract/task"
CATBOX_URL      = "https://catbox.moe/user/api.php"


# ---------------------------------------------------------------------------
# PDF Bölme
# ---------------------------------------------------------------------------
def get_chunks(pdf_path: Path, chunk_size: int = MINERU_CHUNK_SIZE) -> list[tuple[int, int]]:
    total = len(PdfReader(str(pdf_path)).pages)
    return [(s, min(s + chunk_size, total)) for s in range(0, total, chunk_size)]


def extract_chunk_bytes(pdf_path: Path, start: int, end: int) -> bytes:
    reader = PdfReader(str(pdf_path))
    writer = PdfWriter()
    for i in range(start, end):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Catbox Upload
# ---------------------------------------------------------------------------
def upload_catbox(pdf_bytes: bytes, filename: str) -> str | None:
    try:
        resp = requests.post(
            CATBOX_URL,
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (filename, pdf_bytes, "application/pdf")},
            timeout=90,
        )
        if resp.status_code == 200 and resp.text.strip().startswith("https"):
            return resp.text.strip()
    except Exception as e:
        print(f"  Catbox upload hatası: {e}")
    return None


# ---------------------------------------------------------------------------
# MinerU API
# ---------------------------------------------------------------------------
def submit_task(
    public_url: str,
    api_key: str = MINERU_API_KEY,
    log_fn: Callable[[str], None] = print,
) -> str | None:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    payload = {
        "url": public_url,
        "model_version": "vlm",
        "is_ocr": True,
        "enable_formula": True,
        "enable_table": True,
        "lang": "en",
    }
    try:
        r = requests.post(MINERU_TASK_URL, headers=headers, json=payload, timeout=20).json()
        if r.get("code") == 0:
            data = r.get("data", {})
            return data.get("task_id") or data.get("data_id")
        msg = str(r.get("msg", "Sunucu hatası"))
        if any(x in msg.lower() for x in ["auth", "authenticate", "token", "login", "invalid"]):
            log_fn("  ✗ API kimlik doğrulaması başarısız.")
            log_fn("    → mineru.net adresinden hesabınıza giriş yaparak yeni API anahtarı alın.")
            log_fn("    → Ardından 'Gelişmiş Seçenekler > MinerU'yu atla' ile mevcut JSON'u kullanabilirsiniz.")
        else:
            log_fn(f"  ✗ MinerU hatası: {msg}")
    except Exception as e:
        log_fn(f"  ✗ MinerU bağlantı hatası: {e}")
    return None


def poll_task(
    task_id: str,
    api_key: str = MINERU_API_KEY,
    timeout_sec: int = 900,
    log_fn: Callable[[str], None] = print,
) -> str | None:
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://mineru.net/api/v4/extract/task/{task_id}"
    deadline = time.time() + timeout_sec
    elapsed = 0
    next_log_at = 20
    while time.time() < deadline:
        time.sleep(6)
        elapsed += 6
        try:
            r = requests.get(url, headers=headers, timeout=15).json()
            state = r.get("data", {}).get("state", "unknown")
            if elapsed >= next_log_at or state in ("done", "failed"):
                log_fn(f"  Yapay zeka işliyor... ({elapsed}s geçti)")
                next_log_at = elapsed + 30
            if state == "done":
                return r["data"].get("full_zip_url")
            if state == "failed":
                err = r.get("data", {}).get("err_msg", "Bilinmeyen hata")
                log_fn(f"  ✗ İşlem başarısız: {err}")
                return None
        except Exception as e:
            log_fn(f"  Bağlantı sorunu: {e}")
    log_fn(f"  ✗ Zaman aşımı ({timeout_sec // 60} dakika). İşlem çok uzun sürdü.")
    return None


# ---------------------------------------------------------------------------
# ZIP İndir & JSON Çıkar
# ---------------------------------------------------------------------------
def download_chunk(
    zip_url: str,
    out_dir: Path,
    prefix: str,
    images_dir: Path | None = None,
) -> Path | None:
    try:
        resp = requests.get(zip_url, timeout=180)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ZIP indirme hatası: {e}")
        return None

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        candidates = [n for n in z.namelist() if n.endswith("content_list.json")]
        if not candidates:
            return None
        raw = json.loads(z.read(candidates[0]))

        if images_dir is not None:
            images_dir.mkdir(parents=True, exist_ok=True)
            for name in [n for n in z.namelist() if n.startswith("images/") and not n.endswith("/")]:
                dest = images_dir / Path(name).name
                if not dest.exists():
                    dest.write_bytes(z.read(name))

    if isinstance(raw, list):
        content = raw
    elif isinstance(raw, dict) and "content_list" in raw:
        content = raw["content_list"]
    elif isinstance(raw, dict) and "data" in raw:
        content = raw["data"].get("content_list", [])
    else:
        content = raw

    out_path = out_dir / f"{prefix}_content_list.json"
    out_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Birleştirme
# ---------------------------------------------------------------------------
def merge_chunks(chunks_dir: Path, output_path: Path) -> int:
    files = sorted(chunks_dir.glob("pages_*_content_list.json"))
    if not files:
        return 0
    merged = []
    for f in files:
        try:
            page_start = int(f.stem.split("_")[1].split("-")[0]) - 1
        except Exception:
            page_start = 0
        chunk = json.loads(f.read_text(encoding="utf-8"))
        if isinstance(chunk, dict):
            chunk = chunk.get("content_list", [])
        for item in chunk:
            item = dict(item)
            if "page_idx" in item:
                item["page_idx"] = item["page_idx"] + page_start
            merged.append(item)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(merged)


# ---------------------------------------------------------------------------
# Tek parça işleme (paralel worker gövdesi)
# ---------------------------------------------------------------------------
def _process_one_chunk(
    pdf_path: Path,
    chunks_dir: Path,
    images_dir: Path | None,
    api_key: str,
    idx: int,
    n: int,
    start: int,
    end: int,
    log_fn: Callable[[str], None],
) -> bool:
    """Bir parçayı uçtan uca işler: böl → yükle → MinerU → indir.
    Parçalar arasında veri bağımlılığı yoktur — güvenle paralel çalışır."""
    prefix   = f"pages_{start+1:03d}-{end:03d}"
    out_file = chunks_dir / f"{prefix}_content_list.json"
    tag      = f"[{idx+1}/{n}]"

    if out_file.exists():
        log_fn(f"✓ {tag} sayfa {start+1}–{end} (önbellekten)")
        return True

    t = {}
    t0 = time.perf_counter()
    pdf_bytes = extract_chunk_bytes(pdf_path, start, end)
    t["bölme"] = time.perf_counter() - t0

    log_fn(f"▶ {tag} sayfa {start+1}–{end}: sunucuya yükleniyor...")
    t0 = time.perf_counter()
    pub_url = upload_catbox(pdf_bytes, f"{prefix}.pdf")
    t["yükleme"] = time.perf_counter() - t0
    if not pub_url:
        log_fn(f"  ✗ {tag} yükleme başarısız. (İnternet bağlantısını kontrol edin)")
        return False

    task_id = submit_task(pub_url, api_key, log_fn=log_fn)
    if not task_id:
        log_fn(f"  ✗ {tag} görev oluşturulamadı.")
        return False
    log_fn(f"  {tag} yapay zekaya gönderildi, işleniyor...")

    t0 = time.perf_counter()
    zip_url = poll_task(task_id, api_key,
                        log_fn=lambda m: log_fn(f"  {tag} {m.strip()}"))
    t["MinerU"] = time.perf_counter() - t0
    if not zip_url:
        return False

    t0 = time.perf_counter()
    result = download_chunk(zip_url, chunks_dir, prefix, images_dir=images_dir)
    t["indirme"] = time.perf_counter() - t0
    if not result:
        log_fn(f"  ✗ {tag} sonuç indirilemedi.")
        return False

    if TIMING_LOGS:
        parts = " · ".join(f"{k} {v:.0f}s" for k, v in t.items())
        log_fn(f"  ⏱ {tag} {parts}")
    log_fn(f"  ✅ {tag} tamamlandı.")
    return True


# ---------------------------------------------------------------------------
# Ana İşleme Fonksiyonu
# ---------------------------------------------------------------------------
def process_all(
    pdf_path: Path,
    chunks_dir: Path,
    merged_output: Path,
    api_key: str = MINERU_API_KEY,
    chunk_size: int = MINERU_CHUNK_SIZE,
    log_fn: Callable[[str], None] = print,
    images_dir: Path | None = None,
) -> dict:
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunks = get_chunks(pdf_path, chunk_size)
    total_pages = sum(e - s for s, e in chunks)
    n = len(chunks)

    # 0 = tüm parçalar aynı anda; 1 = sıralı (eski davranış); N = üst sınır
    workers = MINERU_PARALLEL_CHUNKS if MINERU_PARALLEL_CHUNKS > 0 else n
    workers = max(1, min(workers, n))

    mode = "paralel" if workers > 1 else "sıralı"
    log_fn(f"PDF'iniz {total_pages} sayfa. {n} parça {mode} işlenecek"
           + (f" ({workers} eşzamanlı)." if workers > 1 else "."))
    log_fn(f"__PROGRESS__:2:MinerU başlatılıyor ({n} parça, {mode})")

    done_count = 0
    lock = threading.Lock()

    def run_one(args) -> tuple[str, bool]:
        nonlocal done_count
        i, (start, end) = args
        prefix = f"pages_{start+1:03d}-{end:03d}"
        if workers > 1:
            time.sleep(min(i, 8) * 1.0)   # yüklemeleri hafifçe kademelendir
        ok = _process_one_chunk(pdf_path, chunks_dir, images_dir, api_key,
                                i, n, start, end, log_fn)
        with lock:
            done_count += 1
            pct = int(done_count / n * 95) + 2
            log_fn(f"__PROGRESS__:{pct}:{done_count}/{n} parça tamam")
        return prefix, ok

    t_mineru = time.perf_counter()
    if workers == 1:
        results = []
        for i, ch in enumerate(chunks):
            results.append(run_one((i, ch)))
            if i < n - 1:
                time.sleep(4)
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            results = list(ex.map(run_one, enumerate(chunks)))

    failed = [p for p, ok in results if not ok]

    # Dayanıklılık: başarısız parçalar havuz boşaldıktan sonra SIRALI yeniden denenir
    if failed:
        log_fn(f"⚠ {len(failed)} parça başarısız — sıralı yeniden deneniyor...")
        still_failed = []
        for i, (start, end) in enumerate(chunks):
            prefix = f"pages_{start+1:03d}-{end:03d}"
            if prefix not in failed:
                continue
            time.sleep(4)
            if not _process_one_chunk(pdf_path, chunks_dir, images_dir, api_key,
                                      i, n, start, end, log_fn):
                still_failed.append(prefix)
        failed = still_failed

    if TIMING_LOGS:
        log_fn(f"⏱ MinerU toplam: {time.perf_counter() - t_mineru:.0f}s ({mode}, {n} parça)")

    total_items = merge_chunks(chunks_dir, merged_output)
    if total_items == 0:
        return {"success": False, "chunks_ok": 0, "chunks_total": n,
                "output": None, "error": "Birleştirilecek veri bulunamadı."}

    chunks_ok = n - len(failed)
    log_fn(f"✅ {total_items} içerik öğesi birleştirildi.")
    log_fn(f"__PROGRESS__:99:MinerU tamamlandı")
    return {
        "success": len(failed) == 0,
        "chunks_ok": chunks_ok,
        "chunks_total": n,
        "output": merged_output,
        "error": f"Başarısız adımlar: {', '.join(failed)}" if failed else None,
    }
