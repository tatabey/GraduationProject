"""
Retriever
=========
ChromaDB semantic search + cross-encoder reranking.
KB'ye özgü chroma_dir ve collection_name ile çalışır.

Dışarıya açık:
    retrieve(query, chroma_dir, collection_name, top_k) -> list[dict]
    format_context(matches)                             -> str
"""

import re
from collections import defaultdict
from pathlib import Path
from statistics import mean, pstdev
from typing import Callable

import chromadb
from chromadb.utils import embedding_functions

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import (
    EMBED_MODEL, RERANKER_MODEL, TOP_K, RERANK_FACTOR,
    TABLE_POOL_MAX, CODE_TOKEN_BONUS, TABLE_FLOOR,
    TEXT_FETCH_K, BM25_ENABLED, BM25_TOP_N, RERANK_SHORTLIST,
)

# Jenerik "kod-benzeri" token yakalayıcı: HD 1.1, 1.2.1, Group K, Q-D, Table 4 vb.
# Domain'e özel DEĞİL — herhangi bir standardın kodlarına uyar.
_CODE_RE = re.compile(
    r'\b(?:[A-Z]{1,4}[\s-]?)?\d+(?:\.\d+)+\b'   # 1.1, 1.2.1, HD 1.1
    r'|\b[A-Z]{1,4}[\s-]?\d+\b'                  # Table 4, Q-D 9
    r'|\bGroup\s+[A-Z]\b'                         # Group K, Group S
)


def _code_tokens(text: str) -> set[str]:
    """Metindeki kod-benzeri tokenları normalize ederek (boşluk/tire/case yok) döndürür."""
    out = set()
    for m in _CODE_RE.findall(text):
        norm = re.sub(r'[\s-]+', '', m).upper()
        if norm:
            out.add(norm)
    return out


def _code_overlap(query: str, serialized: str) -> float:
    """
    Sorgu ve doc kod-tokenları arasındaki örtüşme oranı (0–1).
    Sorgudaki tüm kodlar doc'ta varsa 1.0; hiç kod yoksa 0.0.
    """
    q = _code_tokens(query)
    if not q:
        return 0.0
    d = _code_tokens(serialized)
    if not d:
        return 0.0
    return len(q & d) / len(q)

# Cross-encoder lazy load
_reranker = None

def _get_reranker():
    global _reranker
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            _reranker = CrossEncoder(RERANKER_MODEL)
        except Exception:
            _reranker = False
    return _reranker if _reranker else None


def _meta_to_match(meta: dict, doc: str, distance: float | None = None) -> dict:
    return {
        "type"        : meta.get("type", "table"),
        "table_name"  : meta.get("table_name", ""),
        "display_name": meta.get("display_name", meta.get("table_name", "")),
        "serialized"  : meta.get("serialized", ""),
        "html"        : meta.get("html", ""),
        "notes"       : meta.get("notes", ""),
        "legend"      : meta.get("legend", ""),
        "footnotes"   : meta.get("footnotes", ""),
        "chunk_id"    : meta.get("chunk_id", ""),
        "title"       : meta.get("title", ""),
        "section_path": meta.get("section_path", ""),
        "content"     : meta.get("content", ""),
        "summary"     : doc,
        "synth"       : meta.get("synth", 0),
        "distance"    : distance,
        "page_idx"    : meta.get("page_idx"),
        "img_path"    : meta.get("img_path", ""),
        "llm_summary" : meta.get("llm_summary", ""),
    }


def retrieve(
    query: str,
    chroma_dir: str | Path,
    collection_name: str,
    top_k: int = TOP_K,
    embed_model: str = EMBED_MODEL,
    log_fn: Callable[[str], None] | None = None,
) -> list[dict]:
    """
    Sorgu için en iyi top_k eşleşmeyi döndürür.
    Semantic search → cross-encoder rerank.
    """
    chroma = chromadb.PersistentClient(path=str(chroma_dir))
    emb_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=embed_model
    )
    collection = chroma.get_collection(name=collection_name, embedding_function=emb_fn)

    if collection.count() == 0:
        return []

    # ── İKİ AŞAMALI SEÇİM ──────────────────────────────────────────────
    # 1) Slot tahsisi: DAR havuz (baseline ile birebir aynı: genel top-12 +
    #    tüm tablolar) final top_k'daki tablo/text slot dağılımını belirler.
    #    Tablo davranışı bu sayede İNŞA GEREĞİ değişmez.
    # 2) Slot içeriği: head'deki text slotlarına hangi chunk'ın gireceğini
    #    GENİŞ text kanalı (TEXT_FETCH_K + BM25) seçer. Text yerine text
    #    takası tablo isabetini etkileyemez.
    fetch_k = top_k * RERANK_FACTOR

    # Dar havuz: genel arama
    results = collection.query(query_texts=[query], n_results=min(fetch_k, collection.count()))
    candidates = [
        _meta_to_match(meta, doc, dist)
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]

    # Dar havuz: tablo kanalı — tüm tablolar her zaman adaydır, böylece
    # kalabalık text popülasyonunda boğulmazlar.
    try:
        tbl_results = collection.query(
            query_texts=[query],
            n_results=TABLE_POOL_MAX,
            where={"type": "table"},
        )
        for doc, meta, dist in zip(
            tbl_results["documents"][0],
            tbl_results["metadatas"][0],
            tbl_results["distances"][0],
        ):
            candidates.append(_meta_to_match(meta, doc, dist))
    except Exception:
        pass

    # Geniş text kanalı: embedding recall darboğazına karşı derin havuz.
    # Yalnızca text slotlarının İÇERİĞİNİ seçmek için kullanılır.
    wide_text: list[dict] = []
    if TEXT_FETCH_K > fetch_k:
        try:
            wt = collection.query(
                query_texts=[query],
                n_results=min(TEXT_FETCH_K, collection.count()),
                where={"type": "text_chunk"},
            )
            for doc, meta, dist in zip(
                wt["documents"][0], wt["metadatas"][0], wt["distances"][0]
            ):
                wide_text.append(_meta_to_match(meta, doc, dist))
        except Exception:
            pass

    # BM25 lexical kanal: birebir kod/paragraf atıflarını ("para 1.2.2.1")
    # embedding kaçırsa da geniş kanala sokar. (Tablolar zaten eksiksiz dar
    # havuzda olduğundan BM25 tablo adayı ekleyemez — text'e filtrelenir.)
    if BM25_ENABLED:
        try:
            from pipeline.lexical import bm25_top
            for doc, meta in bm25_top(collection, query, BM25_TOP_N):
                if meta.get("type") == "text_chunk":
                    wide_text.append(_meta_to_match(meta, doc, None))
        except Exception as e:
            if log_fn:
                log_fn(f"BM25 kanalı atlandı: {e}")

    def _key(m: dict) -> str:
        return m["table_name"] if m["type"] == "table" else m["chunk_id"] or m["title"]

    # Duplicate temizle (dar havuz)
    seen: set[str] = set()
    unique: list[dict] = []
    for m in candidates:
        if _key(m) not in seen:
            seen.add(_key(m))
            unique.append(m)

    # Duplicate temizle (geniş kanal, kendi içinde)
    wseen: set[str] = set()
    wide: list[dict] = []
    for m in wide_text:
        if _key(m) not in wseen:
            wseen.add(_key(m))
            wide.append(m)

    # Cross-encoder rerank — dar + geniş tüm adaylar TEK seferde skorlanır
    reranker = _get_reranker()
    if reranker and len(unique) > top_k:
        to_score: dict[str, dict] = {}
        for m in unique + wide:
            to_score.setdefault(_key(m), m)
        keys  = list(to_score)
        pairs = []
        for k in keys:
            m = to_score[k]
            if m["type"] == "text_chunk" and m.get("synth"):
                # Sentetik-soru vektörü: rerank sorgu↔chunk İÇERİĞİ üzerinden
                # yapılmalı, sorgu↔sentetik-soru üzerinden değil.
                doc_text = (m.get("section_path", "") + "\n" + m.get("title", "")
                            + "\n" + m.get("content", ""))[:800]
            else:
                doc_text = m["summary"] or m.get("content", "")[:800] or m.get("html", "")[:500]
            pairs.append((query, doc_text))
        scores = reranker.predict(pairs)
        score_of = {k: float(s) for k, s in zip(keys, scores)}
        for m in unique + wide:
            m["rerank_score"] = score_of[_key(m)]

        # 1) Modalite-içi z-normalizasyon: ms-marco tabloyu web-passage gibi
        #    puanlamaz (sistematik kayma). Skorları her `type` grubu içinde
        #    ayrı normalize ederek modaliteler arası adil kıyas sağlanır.
        #    Domain anahtar kelimesi gerektirmez → her PDF'de çalışır.
        #    Z-norm'dan ÖNCE her tip raw skora göre RERANK_SHORTLIST'e kırpılır:
        #    aksi hâlde büyük havuzun (ör. 160 text adayı) örneklem-maksimumu
        #    küçük havuza (31 tablo) karşı istatistiksel avantaj kazanır.
        by_type: dict[str, list[dict]] = defaultdict(list)
        for m in unique:
            by_type[m["type"]].append(m)
        shortlisted: list[dict] = []
        for grp in by_type.values():
            grp.sort(key=lambda x: x["rerank_score"], reverse=True)
            if RERANK_SHORTLIST > 0:
                grp = grp[:RERANK_SHORTLIST]
            s  = [m["rerank_score"] for m in grp]
            mu = mean(s)
            sd = pstdev(s) or 1.0
            for m in grp:
                m["norm_score"] = (m["rerank_score"] - mu) / sd
            shortlisted.extend(grp)
        unique = shortlisted

        # 2) Jenerik kod-token bonusu: sorgu↔doc kod örtüşmesine küçük ek puan.
        #    (tabloda serialized, text'te tam content — synth/window'dan bağımsız)
        for m in unique:
            doc_text = m.get("serialized") or m.get("content") or m.get("summary", "")
            ov = _code_overlap(query, doc_text)
            m["code_score"]  = ov
            m["norm_score"] += CODE_TOKEN_BONUS * ov

        unique.sort(key=lambda x: x.get("norm_score", -9999), reverse=True)

        # 3) Yumuşak tablo tabanı: en iyi tablo adayı medyanın altında değilse
        #    final top_k içinde yer garantisi (zorlama değil, rekabetçiyse dahil).
        unique = _apply_table_floor(unique, top_k)

        # 4) Slot içeriği seçimi: head'deki text slotları geniş kanalın en iyi
        #    adaylarıyla (sırayla) doldurulur. Slot SAYISI dar zincirden gelir,
        #    İÇERİK geniş havuzdan — tablo sonuçları bu adımdan etkilenemez.
        if wide:
            s  = [m["rerank_score"] for m in wide]
            mu = mean(s)
            sd = pstdev(s) or 1.0
            for m in wide:
                doc_text = m.get("content") or m.get("summary", "")
                ov = _code_overlap(query, doc_text)
                m["code_score"] = ov
                m["norm_score"] = (m["rerank_score"] - mu) / sd + CODE_TOKEN_BONUS * ov
            wide.sort(key=lambda x: x["norm_score"], reverse=True)
            head = unique[:top_k]
            wi = 0
            for i, m in enumerate(head):
                if m["type"] == "text_chunk" and wi < len(wide):
                    head[i] = wide[wi]
                    wi += 1
            unique = head + [m for m in unique[top_k:] if _key(m) not in {_key(h) for h in head}]
    else:
        for m in unique:
            m["code_score"] = 0.0
        unique.sort(key=lambda x: x["distance"] if x["distance"] is not None else 9999)

    return unique[:top_k]


def _apply_table_floor(ranked: list[dict], top_k: int) -> list[dict]:
    """
    norm_score'a göre sıralı listede, en iyi tablo adayı top_k dışında kaldıysa
    ama skoru tüm adayların medyanından düşük değilse, onu top_k'nın son sırasına
    ekleyerek tabloların metin kalabalığında tamamen boğulmasını önler.
    """
    if TABLE_FLOOR <= 0 or len(ranked) <= top_k:
        return ranked

    head = ranked[:top_k]
    if any(m["type"] == "table" for m in head):
        return ranked  # zaten tablo var

    best_tbl = next((m for m in ranked[top_k:] if m["type"] == "table"), None)
    if best_tbl is None:
        return ranked

    scores = [m.get("norm_score", 0.0) for m in ranked]
    median = sorted(scores)[len(scores) // 2]
    if best_tbl.get("norm_score", -9999) < median:
        return ranked  # rekabetçi değil, zorlama

    # en zayıf head üyesini tabloyla değiştir
    new_head = head[: top_k - 1] + [best_tbl]
    rest = [m for m in ranked if m not in new_head]
    return new_head + rest


def format_context(matches: list[dict]) -> str:
    """Retrieval sonuçlarını LLM bağlam stringine dönüştürür."""
    blocks = []
    for m in matches:
        if m["type"] == "text_chunk":
            parts = [f"[TEXT] {m['title']}"]
            if m["section_path"]:
                parts.append(f"[SECTION] {m['section_path']}")
            parts.append(f"[CONTENT]\n{m['content']}")
        else:
            # Serialized prose kullan (okunabilir, LLM için optimal)
            # Fallback: llm_summary → ham HTML (eski KB uyumu)
            serialized   = m.get("serialized") or m.get("llm_summary") or ""
            display_name = m.get("display_name") or m.get("table_name", "")
            if serialized:
                parts = [f"[TABLE] {display_name}", serialized]
            else:
                parts = [f"[TABLE] {m['table_name']}"]
                if m.get("legend"):
                    parts.append(f"[LEGEND] {m['legend']}")
                parts.append(f"[HTML]\n{m['html']}")
                if m.get("notes"):
                    parts.append(f"[NOTES]\n{m['notes']}")
                if m.get("footnotes"):
                    parts.append(f"[FOOTNOTES]\n{m['footnotes']}")
        blocks.append("\n\n".join(parts))
    return ("\n\n" + "=" * 60 + "\n\n").join(blocks)
