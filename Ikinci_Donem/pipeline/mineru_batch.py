"""
MinerU Batch Processor — AASTP-1 Tam PDF İşleme
===============================================
207 sayfalık PDF'i 50'şer sayfalık parçalara böler (4 chunk), her parçayı
MinerU API'ye gönderir, tüm sonuçları birleştirerek tek bir
full_content_list.json üretir.

NOT: MinerU API'de sayfa sınırı YOK (sadece web demoda 20 sayfa var).
     50 sayfalık chunk'lar → sadece 4 API çağrısı yeterli.

CLI Kullanımı:
    MINERU_API_KEY="eyJ..." python3 mineru_batch.py
    python3 mineru_batch.py --merge-only

İmport Kullanımı (app.py'den):
    from mineru_batch import process_all, merge_chunks
    process_all(api_key="eyJ...", pdf_path=..., log_fn=my_logger)

Resume desteği: daha önce tamamlanan chunk'lar tekrar işlenmez.
"""

import argparse
import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable

import requests
from pypdf import PdfReader, PdfWriter

# ---------------------------------------------------------------------------
# Varsayılan yollar (CLI modu için)
# ---------------------------------------------------------------------------
PIPELINE_DIR  = Path(__file__).parent
PDF_PATH      = PIPELINE_DIR.parent / "AASTP-1-May2006.003973.pdf"
CHUNKS_DIR    = PIPELINE_DIR / "input" / "chunks"
MERGED_OUTPUT = PIPELINE_DIR / "input" / "full_content_list.json"

CHUNK_SIZE = 50  # API'de sayfa sınırı yok; 50 → 4 chunk = 4 API çağrısı

MINERU_TASK_URL = "https://mineru.net/api/v4/extract/task"
CATBOX_URL      = "https://catbox.moe/user/api.php"

# ---------------------------------------------------------------------------
# PDF Bölme
# ---------------------------------------------------------------------------

def get_chunks(pdf_path: Path, chunk_size: int) -> list[tuple[int, int]]:
    """0-indexed (start, end) tuple listesi döner."""
    total = len(PdfReader(str(pdf_path)).pages)
    return [(s, min(s + chunk_size, total)) for s in range(0, total, chunk_size)]


def extract_chunk_bytes(pdf_path: Path, start: int, end: int) -> bytes:
    """pages[start:end] aralığını PDF bytes olarak çıkarır."""
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
        print(f"  Catbox beklenmedik yanıt: {resp.status_code} {resp.text[:100]}")
    except Exception as e:
        print(f"  Catbox upload hatası: {e}")
    return None

# ---------------------------------------------------------------------------
# MinerU API
# ---------------------------------------------------------------------------

def submit_task(public_url: str, api_key: str) -> str | None:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
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
        print(f"  MinerU submit hatası: {r.get('msg')} (code={r.get('code')})")
    except Exception as e:
        print(f"  MinerU submit exception: {e}")
    return None


def poll_task(
    task_id: str,
    api_key: str,
    timeout_sec: int = 900,
    log_fn: Callable[[str], None] = print,
) -> str | None:
    """Görev tamamlanana kadar bekler. ZIP URL döner, hata/timeout'ta None."""
    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://mineru.net/api/v4/extract/task/{task_id}"
    deadline = time.time() + timeout_sec
    elapsed = 0
    while time.time() < deadline:
        time.sleep(6)
        elapsed += 6
        try:
            r = requests.get(url, headers=headers, timeout=15).json()
            state = r.get("data", {}).get("state", "unknown")
            log_fn(f"MinerU işliyor... [{state}] (~{elapsed}s)")
            if state == "done":
                return r["data"].get("full_zip_url")
            if state == "failed":
                log_fn(f"Görev başarısız: {r.get('data', {}).get('err_msg', 'bilinmiyor')}")
                return None
        except Exception as e:
            log_fn(f"Poll hatası: {e}")
    log_fn(f"Timeout ({timeout_sec}s aşıldı)")
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
    """
    ZIP'i indirir: content_list.json'ı kaydeder.
    images_dir verilirse ZIP içindeki images/ klasörünü oraya çıkarır.
    """
    try:
        resp = requests.get(zip_url, timeout=180)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ZIP indirme hatası: {e}")
        return None

    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        candidates = [n for n in z.namelist() if n.endswith("content_list.json")]
        if not candidates:
            print(f"  ZIP içinde content_list.json bulunamadı: {z.namelist()[:8]}")
            return None
        raw = json.loads(z.read(candidates[0]))

        if images_dir is not None:
            images_dir.mkdir(parents=True, exist_ok=True)
            img_entries = [n for n in z.namelist()
                          if n.startswith("images/") and not n.endswith("/")]
            for name in img_entries:
                dest = images_dir / Path(name).name
                if not dest.exists():
                    dest.write_bytes(z.read(name))
            if img_entries:
                print(f"  {len(img_entries)} görsel → {images_dir}")

    # MinerU çıktısı bazen sarmalanmış gelebilir
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
    """
    Tüm chunk content_list'lerini sayfa offset'i düzelterek birleştirir.
    Birleştirilen toplam öğe sayısını döner.
    """
    files = sorted(chunks_dir.glob("pages_*_content_list.json"))
    if not files:
        return 0

    merged = []
    for f in files:
        name = f.stem  # pages_001-050_content_list
        try:
            page_start = int(name.split("_")[1].split("-")[0]) - 1  # 0-indexed
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
# Ana İşleme Fonksiyonu
# ---------------------------------------------------------------------------

def process_all(
    api_key: str,
    pdf_path: Path = PDF_PATH,
    chunks_dir: Path = CHUNKS_DIR,
    merged_output: Path = MERGED_OUTPUT,
    chunk_size: int = CHUNK_SIZE,
    log_fn: Callable[[str], None] = print,
    images_dir: Path | None = None,
) -> dict:
    """
    PDF'i MinerU ile işler ve birleştirilmiş content_list.json üretir.

    Dönen dict:
      success   : bool
      chunks_ok : int   — başarılı chunk sayısı
      chunks_total: int
      output    : Path | None
      error     : str | None
    """
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunks = get_chunks(pdf_path, chunk_size)
    total_pages = sum(e - s for s, e in chunks)
    log_fn(f"PDF: {pdf_path.name} | {total_pages} sayfa | {len(chunks)} chunk")

    failed = []
    for i, (start, end) in enumerate(chunks):
        prefix = f"pages_{start+1:03d}-{end:03d}"
        out_file = chunks_dir / f"{prefix}_content_list.json"

        if out_file.exists():
            log_fn(f"[{i+1}/{len(chunks)}] {prefix} — zaten mevcut, atlanıyor ✓")
            continue

        log_fn(f"[{i+1}/{len(chunks)}] {prefix} işleniyor (sayfa {start+1}–{end})...")

        pdf_bytes = extract_chunk_bytes(pdf_path, start, end)
        log_fn(f"  PDF chunk: {len(pdf_bytes)//1024} KB")

        log_fn("  Catbox'a yükleniyor...")
        pub_url = upload_catbox(pdf_bytes, f"{prefix}.pdf")
        if not pub_url:
            log_fn("  ✗ Catbox yüklemesi başarısız")
            failed.append(prefix)
            continue
        log_fn(f"  URL: {pub_url}")

        task_id = submit_task(pub_url, api_key)
        if not task_id:
            log_fn("  ✗ MinerU görevi gönderilemedi")
            failed.append(prefix)
            continue
        log_fn(f"  Task ID: {task_id}")

        zip_url = poll_task(task_id, api_key, log_fn=log_fn)
        if not zip_url:
            log_fn("  ✗ Görev tamamlanamadı")
            failed.append(prefix)
            continue

        result = download_chunk(zip_url, chunks_dir, prefix, images_dir=images_dir)
        if result is None:
            log_fn("  ✗ JSON indirilemedi")
            failed.append(prefix)
        else:
            log_fn(f"  ✅ Kaydedildi: {result.name}")

        if i < len(chunks) - 1:
            time.sleep(4)

    log_fn("Chunk'lar birleştiriliyor...")
    total_items = merge_chunks(chunks_dir, merged_output)

    if total_items == 0:
        return {"success": False, "chunks_ok": 0, "chunks_total": len(chunks),
                "output": None, "error": "Birleştirilecek veri bulunamadı."}

    chunks_ok = len(chunks) - len(failed)
    log_fn(f"✅ Birleştirme tamamlandı: {total_items} öğe → {merged_output.name}")
    return {
        "success": len(failed) == 0,
        "chunks_ok": chunks_ok,
        "chunks_total": len(chunks),
        "output": merged_output,
        "error": f"Başarısız: {', '.join(failed)}" if failed else None,
    }

# ---------------------------------------------------------------------------
# CLI Giriş Noktası
# ---------------------------------------------------------------------------

def _merge_only():
    print("Sadece birleştirme modu...")
    count = merge_chunks(CHUNKS_DIR, MERGED_OUTPUT)
    print(f"Birleştirilen öğe: {count} → {MERGED_OUTPUT}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--merge-only", action="store_true",
                        help="Yeni chunk işleme, sadece mevcut chunk'ları birleştir")
    args = parser.parse_args()

    if args.merge_only:
        _merge_only()
    else:
        key = os.getenv("MINERU_API_KEY", "")
        if not key:
            print("HATA: MINERU_API_KEY ortam değişkeni ayarlanmamış.")
            print("  Kullanım: MINERU_API_KEY='eyJ...' python3 mineru_batch.py")
            sys.exit(1)
        if not PDF_PATH.exists():
            print(f"HATA: PDF bulunamadı: {PDF_PATH}")
            sys.exit(1)
        result = process_all(api_key=key)
        if not result["success"]:
            print(f"\nUyarı: {result['error']}")
        print(f"\nSonuç: {result['chunks_ok']}/{result['chunks_total']} chunk başarılı")
