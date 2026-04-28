"""
MultiVectorIndexer
==================
Hem tablo hem de text chunk'larını ChromaDB'ye yazar.

Tablolar (type=table):
  document  → LLM özeti          (semantik aramada isabetli eşleşir)
  metadata  → html, notes, legend, footnotes, table_name, page_idx

Text chunk'lar (type=text_chunk):
  document  → doğal dil içerik   (LLM özeti gerekmez, zaten okunabilir)
  metadata  → title, section_path, content, page_idx

Çıktı ChromaDB koleksiyonu: "aastp_multivector_v1"
"""

import json
import os
import time
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from groq import Groq

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------
PIPELINE_DIR  = Path(__file__).resolve().parents[1]
UNITS_FILE    = PIPELINE_DIR / "data" / "semantic_units" / "semantic_units.json"
CHUNKS_FILE   = PIPELINE_DIR / "data" / "text_chunks" / "text_chunks.json"
DB_PATH       = PIPELINE_DIR / "data" / "chroma_db"
COLLECTION    = "aastp_multivector_v1"
EMBED_MODEL   = "all-MiniLM-L6-v2"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"

# Groq rate-limit koruması (ücretsiz katman: ~30 req/dk)
REQUEST_DELAY = 3  # saniye


# ---------------------------------------------------------------------------
# LLM Özetleme
# ---------------------------------------------------------------------------
def build_prompt(unit: dict) -> str:
    notes_text = "\n".join(f"  - {n}" for n in unit["notes"]) if unit["notes"] else "  (none)"
    footnotes_text = "\n".join(f"  - {f}" for f in unit["footnotes"]) if unit["footnotes"] else "  (none)"
    hierarchy_text = " > ".join(unit["hierarchy"].values()) if unit["hierarchy"] else "(unknown)"

    return f"""You are a data engineer preparing a RAG (Retrieval-Augmented Generation) vector database for NATO AASTP-1 military ammunition storage standards.

Your task: Write a DENSE RETRIEVAL SUMMARY for the table below. This summary will be embedded as a vector and used for semantic search. It is NOT meant for human reading.

STRICT RULES:
1. Write a single dense paragraph (3-5 sentences). NO bullet points.
2. Do NOT start with "This table..." or "The following table...".
3. Embed every key concept: table name, groups/divisions mentioned, permitted/prohibited combinations, AND all note conditions.
4. Use the exact terminology from the source (e.g. "Compatibility Group B", "Hazard Division 1.1", "NEQ aggregation").
5. A user asking "Can Group B be stored with Group F?" must be able to find this table through this summary.

--- SOURCE MATERIAL ---
Section hierarchy : {hierarchy_text}
Table name        : {unit['table_name']}
Legend            : {unit['legend'] or '(none)'}

Table HTML (structure):
{unit['html'][:1500]}

Notes (CRITICAL — include all conditions):
{notes_text}

Footnotes:
{footnotes_text}
--- END SOURCE ---

Write the dense retrieval summary now (single paragraph, English):"""


def generate_summary(client: Groq, unit: dict) -> str:
    prompt = build_prompt(unit)
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"  ⚠️  Groq hatası: {e}")
        return ""


# ---------------------------------------------------------------------------
# ChromaDB Yazma
# ---------------------------------------------------------------------------
def build_table_metadata(unit: dict, summary: str) -> dict:
    return {
        "type"       : "table",
        "table_name" : unit["table_name"][:200],
        "page_idx"   : unit["page_idx"],
        "img_path"   : unit["img_path"] or "",
        "legend"     : unit["legend"] or "",
        "html"       : unit["html"],
        "notes"      : "\n".join(unit["notes"]),
        "footnotes"  : "\n".join(unit["footnotes"]),
        "llm_summary": summary,
    }


def build_chunk_metadata(chunk: dict) -> dict:
    return {
        "type"        : "text_chunk",
        "title"       : chunk["title"][:200],
        "section_path": " > ".join(chunk["section_path"]),
        "content"     : chunk["content"],
        "page_idx"    : chunk["page_idx"],
    }


def _get_or_create_collection(chroma, emb_fn, reset: bool = True):
    if reset:
        try:
            chroma.delete_collection(COLLECTION)
            print(f"🗑️  Eski '{COLLECTION}' koleksiyonu silindi.")
        except Exception:
            pass
        col = chroma.create_collection(name=COLLECTION, embedding_function=emb_fn)
        print(f"✅ Yeni koleksiyon oluşturuldu: '{COLLECTION}'\n")
    else:
        col = chroma.get_or_create_collection(name=COLLECTION, embedding_function=emb_fn)
    return col


def index_tables(units: list[dict], collection, groq_client: Groq) -> int:
    print(f"📋 {len(units)} tablo indeksleniyor...\n")
    indexed = 0
    for i, unit in enumerate(units):
        print(f"  [{i+1}/{len(units)}] {unit['table_name'][:60]}...")
        summary = generate_summary(groq_client, unit)
        if not summary:
            print("    ⛔ Özet üretilemedi, atlandı.")
            continue
        print(f"    📝 Özet ({len(summary)} kr) üretildi.")
        doc_id   = f"table_p{unit['page_idx']}_idx{unit['table_idx']}"
        metadata = build_table_metadata(unit, summary)
        collection.add(documents=[summary], metadatas=[metadata], ids=[doc_id])
        print(f"    💾 Kaydedildi (id={doc_id})")
        indexed += 1
        if i < len(units) - 1:
            time.sleep(REQUEST_DELAY)
    return indexed


def index_chunks(chunks: list[dict], collection) -> int:
    print(f"\n📄 {len(chunks)} text chunk indeksleniyor...")
    indexed = 0
    for chunk in chunks:
        doc_id   = chunk["chunk_id"]
        document = chunk["title"] + "\n" + chunk["content"]
        metadata = build_chunk_metadata(chunk)
        collection.add(documents=[document], metadatas=[metadata], ids=[doc_id])
        indexed += 1
    print(f"  💾 {indexed} text chunk kaydedildi.")
    return indexed


def run_indexing(units: list[dict], chunks: list[dict]) -> None:
    DB_PATH.mkdir(parents=True, exist_ok=True)
    chroma = chromadb.PersistentClient(path=str(DB_PATH))
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    collection = _get_or_create_collection(chroma, emb_fn, reset=True)
    groq_client = Groq(api_key=GROQ_API_KEY)

    table_count = index_tables(units, collection, groq_client)
    chunk_count = index_chunks(chunks, collection)

    total = collection.count()
    print(f"\n🎉 Tamamlandı.")
    print(f"   Tablo : {table_count} döküman")
    print(f"   Text  : {chunk_count} chunk")
    print(f"   Toplam: {total} döküman  →  {DB_PATH}")


# ---------------------------------------------------------------------------
# Doğrulama sorgusu
# ---------------------------------------------------------------------------
def run_sanity_check() -> None:
    queries = [
        "Can Group B be stored with Group F?",
        "What is Compatibility Group K?",
        "Suspect ammunition storage rules",
    ]
    chroma = chromadb.PersistentClient(path=str(DB_PATH))
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    collection = chroma.get_collection(name=COLLECTION, embedding_function=emb_fn)
    count = collection.count()
    if count == 0:
        print("  ⚠️  Koleksiyon boş.")
        return

    print(f"\n{'='*60}")
    print("🔍 Doğrulama sorguları")
    print(f"{'='*60}")
    for query in queries:
        print(f"\n  Sorgu: \"{query}\"")
        results = collection.query(query_texts=[query], n_results=min(2, count))
        for rank, (doc, meta) in enumerate(
            zip(results["documents"][0], results["metadatas"][0]), 1
        ):
            doc_type = meta.get("type", "?")
            label    = meta.get("table_name", meta.get("title", "?"))[:60]
            print(f"    [{rank}] [{doc_type}] {label}")
            print(f"         {doc[:100]}...")


# ---------------------------------------------------------------------------
# Giriş noktası
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY ortam değişkeni ayarlanmamış.")
        raise SystemExit(1)

    if not UNITS_FILE.exists():
        print(f"❌ {UNITS_FILE} bulunamadı. Önce table_context_assembler.py çalıştırın.")
        raise SystemExit(1)

    if not CHUNKS_FILE.exists():
        print(f"❌ {CHUNKS_FILE} bulunamadı. Önce text_chunker.py çalıştırın.")
        raise SystemExit(1)

    with open(UNITS_FILE, encoding="utf-8") as f:
        units = json.load(f)
    with open(CHUNKS_FILE, encoding="utf-8") as f:
        chunks = json.load(f)

    print(f"📂 Tablolar  : {UNITS_FILE}  ({len(units)} adet)")
    print(f"📂 Text chunk: {CHUNKS_FILE}  ({len(chunks)} adet)\n")

    run_indexing(units, chunks)
    run_sanity_check()
