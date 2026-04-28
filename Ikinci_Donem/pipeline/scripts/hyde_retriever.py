"""
HyDE Retriever + Cross-Encoder Reranker
========================================
İki katmanlı retrieval:
  Katman 1 — Semantic search (all-MiniLM-L6-v2, ChromaDB)
             Geniş ağ: top_k * RERANK_FETCH_FACTOR sonuç alınır.
  Katman 2 — Cross-encoder reranking (ms-marco-MiniLM-L-6-v2, yerel model)
             (query, document) çifti birlikte değerlendirilir →
             kısaltma/paraphrase farklarını köprüler, API gerekmez.

Opsiyonel HyDE:
  groq_client verilirse sorgu önce LLM ile kural diline çevrilir.
  Verilmezse sadece cross-encoder reranking çalışır (0 API token).

Dışarıya açık ana fonksiyon:
  retrieve(query: str, groq_client=None) -> RetrievalResult
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions
from groq import Groq

# Cross-encoder (lazy load)
_reranker = None

def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
            print("  ✅ Cross-encoder reranker yüklendi.")
        except Exception as e:
            print(f"  ⚠️  Cross-encoder yüklenemedi: {e} — sadece semantic search.")
            _reranker = False   # False = denendi ama başarısız, tekrar deneme
    return _reranker if _reranker else None

# ---------------------------------------------------------------------------
# Yapılandırma
# ---------------------------------------------------------------------------
PIPELINE_DIR = Path(__file__).resolve().parents[1]
DB_PATH      = PIPELINE_DIR / "data" / "chroma_db"
COLLECTION  = "aastp_multivector_v1"
EMBED_MODEL = "all-MiniLM-L6-v2"

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = "llama-3.3-70b-versatile"

TOP_K = 3              # kaç sonuç dönsün
RERANK_FETCH_FACTOR = 4  # reranker için semantic'te kaç kat fazla al (3 * 4 = 12)

# Uyumluluk grupları (AASTP-1'deki geçerli harfler — A dahil)
_COMPAT_GROUPS = set("ABCDEFGHJKLNS")
_GROUP_RE = re.compile(r"\bGroup\s+([A-S])\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Veri modeli
# ---------------------------------------------------------------------------
@dataclass
class RetrievalResult:
    query_original : str
    query_rewritten: str                  # HyDE çıktısı (veya orijinal)
    method         : str                  # "metadata_filter" | "hyde" | "semantic"
    matches        : list[dict] = field(default_factory=list)
    # Her match: {table_name, html, notes, legend, footnotes, summary, score}


# ---------------------------------------------------------------------------
# ChromaDB bağlantısı (singleton benzeri, modül yüklendiğinde bir kez)
# ---------------------------------------------------------------------------
def _get_collection():
    chroma = chromadb.PersistentClient(path=str(DB_PATH))
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=EMBED_MODEL
    )
    return chroma.get_collection(name=COLLECTION, embedding_function=emb_fn)


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------
def _extract_groups(text: str) -> list[str]:
    """Sorgudan geçerli uyumluluk grubu harflerini çıkarır."""
    found = _GROUP_RE.findall(text)
    return [g.upper() for g in found if g.upper() in _COMPAT_GROUPS]


def _meta_to_match(meta: dict, doc: str, distance: float | None = None) -> dict:
    return {
        "type"         : meta.get("type", "table"),
        # table fields
        "table_name"   : meta.get("table_name", ""),
        "html"         : meta.get("html", ""),
        "notes"        : meta.get("notes", ""),
        "legend"       : meta.get("legend", ""),
        "footnotes"    : meta.get("footnotes", ""),
        # text_chunk fields
        "title"        : meta.get("title", ""),
        "section_path" : meta.get("section_path", ""),
        "content"      : meta.get("content", ""),
        # shared
        "summary"      : doc,
        "distance"     : distance,
        "page_idx"     : meta.get("page_idx"),
        "img_path"     : meta.get("img_path", ""),
    }


def _build_context_block(match: dict) -> str:
    """Inference LLM'e gönderilecek bağlam bloğunu oluşturur."""
    if match["type"] == "text_chunk":
        parts = [f"[TEXT] {match['title']}"]
        if match["section_path"]:
            parts.append(f"[SECTION] {match['section_path']}")
        parts.append(f"[CONTENT]\n{match['content']}")
    else:
        parts = [f"[TABLE] {match['table_name']}"]
        if match["legend"]:
            parts.append(f"[LEGEND] {match['legend']}")
        parts.append(f"[HTML]\n{match['html']}")
        if match["notes"]:
            parts.append(f"[NOTES]\n{match['notes']}")
        if match["footnotes"]:
            parts.append(f"[FOOTNOTES]\n{match['footnotes']}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# HyDE — sorgu yeniden yazma
# ---------------------------------------------------------------------------
_HYDE_SYSTEM = (
    "You are an expert on NATO AASTP-1 ammunition storage rules. "
    "Given a user question, write a short hypothetical passage (2-3 sentences) "
    "that would appear in the official AASTP-1 standard document as the answer. "
    "Use the exact terminology of the standard: Compatibility Groups, Hazard Divisions, "
    "NEQ aggregation, mixing permitted/prohibited, etc. "
    "Do NOT answer the question yourself — write AS IF you are excerpting from the document."
)


def _hyde_rewrite(client: Groq, query: str) -> str:
    """Sorguyu kural dilinde hipotetik bir belge pasajına çevirir."""
    try:
        resp = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": _HYDE_SYSTEM},
                {"role": "user",   "content": f"User question: {query}"},
            ],
            temperature=0.1,
            max_tokens=120,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"  ⚠️  HyDE rewrite hatası: {e} — orijinal sorgu kullanılacak.")
        return query


# ---------------------------------------------------------------------------
# Arama stratejileri
# ---------------------------------------------------------------------------
def _semantic_search(collection, query_text: str, top_k: int,
                     type_filter: str | None = None) -> list[dict]:
    """Standart semantik arama. type_filter='table' veya 'text_chunk' ile sınırlanabilir."""
    kwargs: dict = {"query_texts": [query_text], "n_results": top_k}
    if type_filter:
        kwargs["where"] = {"type": type_filter}
    results = collection.query(**kwargs)
    matches = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        matches.append(_meta_to_match(meta, doc, dist))
    return matches


# ---------------------------------------------------------------------------
# Ana retrieval fonksiyonu
# ---------------------------------------------------------------------------
def retrieve(query: str, groq_client: Groq | None = None) -> RetrievalResult:
    """
    Sorgu için en iyi eşleşmeleri döndürür.

    Strateji:
      1. Semantic search (orijinal sorgu)  → ilk sonuç kaydedilir.
      2. HyDE rewrite                      → aynı semantic search.
      3. İki sonuç listesi birleştirilir, distance'a göre sıralanır,
         duplicate'ler temizlenir.

    Groq istemcisi yoksa HyDE atlanır, sadece semantic search yapılır.
    """
    collection = _get_collection()

    if collection.count() == 0:
        return RetrievalResult(
            query_original=query,
            query_rewritten=query,
            method="empty_db",
        )

    result = RetrievalResult(query_original=query, query_rewritten=query, method="semantic")

    groups = _extract_groups(query)
    has_groups = len(groups) >= 1

    # --- 1. HyDE rewrite ---
    search_query = query
    if groq_client is not None:
        rewritten = _hyde_rewrite(groq_client, query)
        result.query_rewritten = rewritten
        result.method = "hyde"
        print(f"  ✏️  HyDE rewrite: {rewritten[:120]}...")
        search_query = rewritten

    fetch_k = TOP_K * RERANK_FETCH_FACTOR  # geniş ağ

    # --- 2. Tip bazlı arama ---
    if has_groups:
        table_matches = _semantic_search(collection, search_query, fetch_k, type_filter="table")
        if not table_matches:
            table_matches = _semantic_search(collection, query, fetch_k, type_filter="table")
        text_matches  = _semantic_search(collection, search_query, TOP_K, type_filter="text_chunk")
        candidates = table_matches + text_matches
    else:
        candidates = _semantic_search(collection, search_query, fetch_k)

    # --- 3. Duplicate temizle ---
    seen_keys: set[str] = set()
    merged: list[dict] = []
    for m in candidates:
        key = m["table_name"] if m["type"] == "table" else m["title"]
        if key not in seen_keys:
            seen_keys.add(key)
            merged.append(m)

    # --- 4. Cross-encoder reranking ---
    reranker = _get_reranker()
    if reranker and len(merged) > TOP_K:
        # Reranker için (query, document_text) çiftleri hazırla
        pairs = []
        for m in merged:
            doc_text = m["summary"] or m.get("html", "")[:500] or m.get("content", "")[:500]
            pairs.append((query, doc_text))
        scores = reranker.predict(pairs)
        for m, s in zip(merged, scores):
            m["rerank_score"] = float(s)
        merged.sort(key=lambda x: x.get("rerank_score", -9999), reverse=True)
        result.method = result.method + "+rerank"
    else:
        merged.sort(key=lambda x: x["distance"] if x["distance"] is not None else 9999)

    result.matches = merged[:TOP_K]
    return result


def format_context_for_llm(result: RetrievalResult) -> str:
    """retrieve() çıktısını inference LLM'e hazır bağlam stringine dönüştürür."""
    blocks = [_build_context_block(m) for m in result.matches]
    return "\n\n" + ("=" * 60 + "\n\n").join(blocks)


# ---------------------------------------------------------------------------
# CLI test modu
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if not GROQ_API_KEY:
        print("❌ GROQ_API_KEY ayarlanmamış.")
        print("   Kullanım: GROQ_API_KEY=\"gsk_...\" python3 hyde_retriever.py")
        raise SystemExit(1)

    groq_client = Groq(api_key=GROQ_API_KEY)

    test_queries = [
        "Can Group B be stored with Group F?",
        "What happens if Group N articles are mixed with Group S?",
        "Is water allowed for Calcium Phosphide suppression?",
        "Group L articles storage requirements.",
    ]

    queries = sys.argv[1:] if len(sys.argv) > 1 else test_queries

    for q in queries:
        print(f"\n{'='*60}")
        print(f"SORGU: {q}")
        res = retrieve(q, groq_client=groq_client)
        print(f"Yöntem : {res.method}")
        print(f"Rewrite: {res.query_rewritten[:100]}...")
        print(f"\nSonuçlar ({len(res.matches)}):")
        for i, m in enumerate(res.matches, 1):
            print(f"  [{i}] {m['table_name'][:70]}  (dist={m['distance']:.4f})")
            print(f"       Not önizleme: {m['notes'][:120]}")
