"""
KB Builder
==========
PDF → MinerU → TableAssembler + TextChunker → ChromaDB

Dışarıya açık:
    build_kb(pdf_path, kb_name, data_dir, ...) -> dict
    list_kbs(data_dir)                         -> list[dict]
    delete_kb(kb_name, data_dir)               -> bool
"""

import json
import re
import shutil
import time
from pathlib import Path
from typing import Callable

import chromadb
from chromadb.utils import embedding_functions

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (
    EMBED_MODEL, EMBED_MODEL_MULTILINGUAL, AUTO_EMBED_BY_LANG,
    EMBED_SECTION_PATH, CHUNK_EMBED_MAX_CHARS, CHUNK_SYNTH_QUERIES,
    MINERU_API_KEY, MINERU_CHUNK_SIZE, TIMING_LOGS, CHROMA_ADD_BATCH,
)


# ── Dil tespiti → embedding seçimi ────────────────────────────────────────────
# Bağımlılıksız sezgisel: İngilizce mi, İngilizce-dışı (çok-dilli) mı?
# bge-large-en yalnız İngilizce; Türkçe vb. için çok-dilli model gerekir.
_EN_STOP = {"the", "and", "of", "to", "in", "for", "is", "are", "be", "as",
            "that", "with", "this", "or", "by", "an", "from", "at", "which",
            "shall", "not", "on", "all", "any", "such", "where", "when"}
_TR_STOP = {"ve", "bir", "bu", "için", "ile", "olan", "da", "de", "en", "çok",
            "veya", "göre", "gibi", "ancak", "ise", "her", "daha", "olarak",
            "madde", "edilir", "yapılır", "şekilde", "durumda", "ya"}


def detect_embed_model(text: str) -> tuple[str, str]:
    """Belge metninden embedding modelini seçer.
    Döner: (embed_model, açıklama). İngilizce → EMBED_MODEL,
    İngilizce-dışı → EMBED_MODEL_MULTILINGUAL."""
    sample = text[:20000].lower()
    words = re.findall(r"[a-zçğıöşü]+", sample)
    if len(words) < 30:                      # yetersiz metin → güvenli varsayılan
        return EMBED_MODEL, "İngilizce (yetersiz metin → varsayılan)"
    en = sum(w in _EN_STOP for w in words) / len(words)
    tr = sum(w in _TR_STOP for w in words) / len(words)
    # ı/ğ/ş İngilizce'de hiç yok → güçlü İngilizce-dışı sinyali
    tr_chars = sample.count("ı") + sample.count("ğ") + sample.count("ş")
    non_english = tr_chars >= 5 or tr > en or en < 0.04
    model = EMBED_MODEL_MULTILINGUAL if non_english else EMBED_MODEL
    lang  = "İngilizce-dışı (çok-dilli)" if non_english else "İngilizce"
    return model, f"{lang}  (EN-stop={en:.1%} TR-stop={tr:.1%} ı/ğ/ş={tr_chars})"


class _BatchAdder:
    """ChromaDB'ye dokümanları parti hâlinde ekler — parti başına TEK embedding
    batch'i çalışır (doküman-başına add'e göre GPU'da ~4-5x hızlı)."""

    def __init__(self, collection, batch_size: int = CHROMA_ADD_BATCH):
        self.collection = collection
        self.batch_size = max(1, batch_size)
        self._docs: list[str] = []
        self._metas: list[dict] = []
        self._ids: list[str] = []

    def add(self, document: str, metadata: dict, doc_id: str) -> None:
        self._docs.append(document)
        self._metas.append(metadata)
        self._ids.append(doc_id)
        if len(self._docs) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._docs:
            return
        self.collection.add(documents=self._docs, metadatas=self._metas, ids=self._ids)
        self._docs, self._metas, self._ids = [], [], []
from scripts.mineru_batch import process_all
from scripts.table_assembler import assemble_semantic_units, save_semantic_units
from scripts.text_chunker import chunk_text_blocks, save_text_chunks
from pipeline.table_serializer import serialize_table, table_display_name


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def _sanitize(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name.strip())[:63].strip("_")


def _scaled_log(log_fn: Callable, offset: int, scale: int) -> Callable:
    """__PROGRESS__:0–100 mesajlarını offset–(offset+scale) aralığına ölçekler."""
    def wrapper(m: str):
        if m.startswith("__PROGRESS__:"):
            parts = m.split(":", 2)
            try:
                pct = int(parts[1])
                step = parts[2] if len(parts) > 2 else ""
                scaled = min(offset + int(pct * scale / 100), offset + scale)
                log_fn(f"__PROGRESS__:{scaled}:{step}")
            except (ValueError, IndexError):
                log_fn(m)
        else:
            log_fn(m)
    return wrapper


# ---------------------------------------------------------------------------
# ChromaDB indeksleme
# ---------------------------------------------------------------------------
def _index_tables(
    units: list[dict],
    collection,
    log_fn: Callable,
) -> int:
    """Tabloları deterministik serializer ile ChromaDB'ye ekler (LLM yok)."""
    n = len(units)
    log_fn(f"Tablolar vektörleştiriliyor ({n} adet)...")
    adder = _BatchAdder(collection)
    indexed = 0
    for i, unit in enumerate(units):
        pct  = int((i + 1) / n * 100)
        dname = table_display_name(unit)
        log_fn(f"__PROGRESS__:{pct}:Tablo {i+1}/{n}: {dname[:50]}")
        log_fn(f"  [{i+1}/{n}] {dname[:50]}")

        serialized = serialize_table(unit)
        doc_id     = f"table_p{unit.get('page_idx', i)}_idx{unit.get('table_idx', i)}"
        document   = dname + "\n" + serialized
        metadata   = {
            "type"        : "table",
            "table_name"  : unit["table_name"][:200],
            "display_name": dname[:200],
            "page_idx"    : unit.get("page_idx", -1),
            "img_path"    : unit.get("img_path", ""),
            "legend"      : unit.get("legend", "") or "",
            "html"        : unit["html"],
            "notes"       : "\n".join(unit.get("notes", [])),
            "footnotes"   : "\n".join(unit.get("footnotes", [])),
            "serialized"  : serialized,
        }
        adder.add(document, metadata, doc_id)
        indexed += 1
    adder.flush()
    return indexed


def reindex_from_units(
    units: list[dict],
    chunks: list[dict],
    chroma_dir: str | Path,
    col_name: str,
    log_fn: Callable[[str], None] = print,
    embed_model: str = EMBED_MODEL,
) -> dict:
    """
    Hazır semantic_units + text_chunks listesinden ChromaDB'yi sıfırdan kurar.
    MinerU veya Ollama gerektirmez — tamamen deterministik.

    Dönüş: {"tables": int, "chunks": int, "total": int}
    """
    chroma_dir = Path(chroma_dir)
    chroma_dir.mkdir(parents=True, exist_ok=True)

    chroma  = chromadb.PersistentClient(path=str(chroma_dir))
    from pipeline.retriever import best_device
    emb_fn  = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=embed_model, device=best_device() or "cpu"
    )
    try:
        chroma.delete_collection(col_name)
        log_fn(f"Eski koleksiyon silindi: {col_name}")
    except Exception:
        pass
    collection  = chroma.create_collection(name=col_name, embedding_function=emb_fn)

    tc = _index_tables(units, collection, log_fn)
    cc = _index_chunks(chunks, collection, log_fn)
    total = collection.count()
    log_fn(f"✅ Reindex tamamlandı: {tc} tablo + {cc} chunk = {total} döküman")
    return {"tables": tc, "chunks": cc, "total": total}


def _window_text(text: str, max_chars: int) -> list[str]:
    """Uzun metni paragraf sınırlarından max_chars'lık pencerelere paketler."""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    windows: list[str] = []
    cur = ""
    for para in text.split("\n"):
        if cur and len(cur) + 1 + len(para) > max_chars:
            windows.append(cur)
            cur = para
        else:
            cur = cur + "\n" + para if cur else para
    if cur.strip():
        windows.append(cur)
    return windows


def _index_chunks(chunks: list[dict], collection, log_fn: Callable) -> int:
    log_fn(f"Text chunk'lar indeksleniyor ({len(chunks)} adet)...")
    adder = _BatchAdder(collection)
    docs = 0
    for chunk in chunks:
        # section_path hiyerarşisi embed dokümanına bağlam katar; title ile
        # aynıysa tekrar edilmez. (content zaten title satırıyla başlıyor.)
        sec_path = " > ".join(chunk["section_path"])
        if EMBED_SECTION_PATH and sec_path and sec_path != chunk["title"]:
            header = sec_path + "\n" + chunk["title"]
        else:
            header = chunk["title"]
        metadata = {
            "type"        : "text_chunk",
            "chunk_id"    : chunk["chunk_id"],
            "title"       : chunk["title"][:200],
            "section_path": sec_path,
            "content"     : chunk["content"],
            "page_idx"    : chunk["page_idx"],
        }
        # Embedding sınırını aşan chunk'lar pencere pencere indekslenir;
        # metadata (tam content dahil) hepsinde aynı → retriever dedupe
        # chunk_id üzerinden tek match'e indirger.
        windows = _window_text(chunk["content"], CHUNK_EMBED_MAX_CHARS)
        for w_i, win in enumerate(windows):
            doc_id   = chunk["chunk_id"] if len(windows) == 1 else f"{chunk['chunk_id']}__w{w_i}"
            document = header + "\n" + win
            adder.add(document, metadata, doc_id)
            docs += 1
        # Sentetik soru vektörleri: aynı chunk_id metadata'sı, "synth" işareti
        # (retriever rerank'te soru metnini değil chunk içeriğini kullansın diye)
        if CHUNK_SYNTH_QUERIES > 0:
            for q_i, q in enumerate(chunk.get("synth_queries", [])[:CHUNK_SYNTH_QUERIES]):
                adder.add(q, {**metadata, "synth": 1}, f"{chunk['chunk_id']}__q{q_i}")
                docs += 1
    adder.flush()
    log_fn(f"  {len(chunks)} text chunk kaydedildi ({docs} embedding dokümanı).")
    return len(chunks)


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------
def build_kb(
    pdf_path: str | Path,
    kb_name: str,
    data_dir: str | Path,
    api_key: str = MINERU_API_KEY,
    chunk_size: int = MINERU_CHUNK_SIZE,
    log_fn: Callable[[str], None] = print,
    skip_mineru: bool = False,
    merged_json: str | Path | None = None,
    embed_model: str | None = None,
) -> dict:
    """
    PDF'den tam KB indekslemesi yürütür.

    embed_model=None (varsayılan) → belge dili otomatik tespit edilip embedding
    seçilir (AUTO_EMBED_BY_LANG açıksa). Açıkça verilirse o model kullanılır.

    skip_mineru=True ve merged_json verilirse MinerU atlanır
    (zaten işlenmiş JSON kullanılır).

    Dönüş: {"success": bool, "collection": str, "tables": int,
             "chunks": int, "total": int, "error": str | None}
    """
    pdf_path = Path(pdf_path)
    data_dir = Path(data_dir)
    col_name = _sanitize(kb_name) or "knowledge_base"

    kb_dir       = data_dir / col_name
    chunks_dir   = kb_dir / "mineru_chunks"
    merged_out   = kb_dir / "merged_content_list.json"
    units_dir    = kb_dir / "semantic_units"
    text_dir     = kb_dir / "text_chunks"
    chroma_dir   = kb_dir / "chroma_db"
    kb_dir.mkdir(parents=True, exist_ok=True)
    timings: dict[str, float] = {}
    _t0 = time.perf_counter()

    # ── Adım 1: MinerU (0–65%) ────────────────────────────────────────────
    if skip_mineru and merged_json:
        merged_out = Path(merged_json)
        log_fn(f"__PROGRESS__:5:Hazır JSON yükleniyor")
        log_fn(f"MinerU atlandı — mevcut JSON kullanılıyor: {merged_out.name}")
    else:
        log_fn(f"__PROGRESS__:0:MinerU başlatılıyor")
        result = process_all(
            pdf_path=pdf_path,
            chunks_dir=chunks_dir,
            merged_output=merged_out,
            api_key=api_key,
            chunk_size=chunk_size,
            log_fn=_scaled_log(log_fn, offset=0, scale=65),
        )
        if not result["success"] and result["output"] is None:
            return {"success": False, "collection": col_name,
                    "tables": 0, "chunks": 0, "total": 0,
                    "error": result.get("error", "MinerU başarısız")}
        if result.get("error"):
            log_fn(f"Uyarı: {result['error']}")
    timings["mineru_s"] = round(time.perf_counter() - _t0, 1)

    # ── Adım 2: Tablo çıkarma (65–75%) ───────────────────────────────────
    _t0 = time.perf_counter()
    log_fn(f"__PROGRESS__:65:Tablolar analiz ediliyor")
    log_fn("Tablolar ve veri yapıları çıkarılıyor...")
    units, rejected = assemble_semantic_units(merged_out)

    images_dest = kb_dir / "images"
    src_images  = merged_out.parent / "images"
    if not src_images.exists():
        src_images = merged_out.parent.parent / "images"
    if src_images.exists():
        images_dest.mkdir(parents=True, exist_ok=True)
        for unit in units:
            raw = unit.get("img_path", "")
            if not raw:
                continue
            src = src_images / Path(raw).name
            if src.exists():
                dest = images_dest / src.name
                if not dest.exists():
                    shutil.copy2(src, dest)
                unit["img_path"] = f"images/{src.name}"

    save_semantic_units(units, rejected, units_dir)
    log_fn(f"  ✅ {len(units)} tablo bulundu ({len(rejected)} gürültü tablosu atlandı).")
    timings["assemble_s"] = round(time.perf_counter() - _t0, 1)

    # ── Adım 3: Metin bölümleri (75–80%) ─────────────────────────────────
    _t0 = time.perf_counter()
    log_fn(f"__PROGRESS__:75:Metin bölümleri oluşturuluyor")
    log_fn("Metin bölümleri oluşturuluyor...")
    text_chunks = chunk_text_blocks(merged_out)
    save_text_chunks(text_chunks, text_dir)
    log_fn(f"  ✅ {len(text_chunks)} metin bölümü hazır.")
    timings["chunk_s"] = round(time.perf_counter() - _t0, 1)

    # ── Embedding seçimi: açık verilmediyse dile göre otomatik ───────────────
    if embed_model is None:
        if AUTO_EMBED_BY_LANG:
            doc_text = " ".join(
                f"{c.get('title','')} {c.get('content','')}" for c in text_chunks
            )
            embed_model, why = detect_embed_model(doc_text)
            log_fn(f"  🌐 Dil tespiti → {why}")
            log_fn(f"     embedding: {Path(embed_model).name if '/' in embed_model else embed_model}")
        else:
            embed_model = EMBED_MODEL

    # ── Adım 4: ChromaDB indeksleme (80–99%) ─────────────────────────────
    _t0 = time.perf_counter()
    log_fn(f"__PROGRESS__:80:Vektör veritabanı oluşturuluyor")
    log_fn("Vektör veritabanı oluşturuluyor...")
    idx = reindex_from_units(
        units, text_chunks, chroma_dir, col_name,
        _scaled_log(log_fn, offset=80, scale=19),
        embed_model=embed_model,
    )
    timings["index_s"] = round(time.perf_counter() - _t0, 1)
    timings["total_s"] = round(sum(timings.values()), 1)
    if TIMING_LOGS:
        log_fn(f"⏱ Aşama süreleri: MinerU {timings['mineru_s']}s · "
               f"tablo {timings['assemble_s']}s · chunk {timings['chunk_s']}s · "
               f"indeks {timings['index_s']}s · TOPLAM {timings['total_s']}s")
    log_fn(f"__PROGRESS__:99:İndeksleme tamamlandı")
    table_count = idx["tables"]
    chunk_count = idx["chunks"]
    total       = idx["total"]

    log_fn(f"✅ Tamamlandı: {table_count} tablo + {chunk_count} metin bölümü = {total} döküman")
    log_fn(f"__PROGRESS__:99:İndeksleme tamamlandı")

    # KB meta dosyası
    meta = {
        "kb_name"   : kb_name,
        "collection": col_name,
        "pdf"       : pdf_path.name,
        "tables"    : table_count,
        "chunks"    : chunk_count,
        "total"     : total,
        "chroma_dir": str(chroma_dir),
        "created_at": time.strftime("%Y-%m-%d %H:%M"),
        "embed_model": embed_model,
        "timings"   : timings,
    }
    (kb_dir / "kb_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return {"success": True, "collection": col_name,
            "tables": table_count, "chunks": chunk_count,
            "total": total, "error": None}


# ---------------------------------------------------------------------------
# KB Yönetim
# ---------------------------------------------------------------------------
def list_kbs(data_dir: str | Path) -> list[dict]:
    data_dir = Path(data_dir)
    kbs = []
    for meta_file in sorted(data_dir.glob("*/kb_meta.json")):
        try:
            kbs.append(json.loads(meta_file.read_text(encoding="utf-8")))
        except Exception:
            pass
    return kbs


def delete_kb(kb_name: str, data_dir: str | Path) -> bool:
    import shutil
    data_dir = Path(data_dir)
    col_name = _sanitize(kb_name)
    kb_dir   = data_dir / col_name
    if not kb_dir.exists():
        return False
    shutil.rmtree(kb_dir)
    return True
