"""
Lexical (BM25) kanal
====================
Aday havuzu genişletici: sorguya lexical olarak en yakın top-N dökümanı döndürür.
FINAL sıralamaya karışmaz — adaylar retriever'daki tek rerank zincirine girer.

Embedding'in köprüleyemediği birebir atıfları yakalar:
"para 1.2.2.1", "HD 1.1", "Table 4" gibi kod-tokenlar normalize edilerek
(boşluk/tire/case bağımsız) ayrı token olarak indekslenir. Domain'e özel değil.

Dışarıya açık:
    bm25_top(collection, query, n) -> list[(doc, meta)]
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_WORD_RE = re.compile(r"\w+", re.UNICODE)

# Tek girişlik cache: reindex sonrası collection.count() değiştiği için
# anahtar otomatik geçersizleşir ve indeks yeniden kurulur.
_INDEX: dict = {}


def _tokenize(text: str) -> list[str]:
    # retriever'daki jenerik kod-token normalizasyonunu paylaş (lazy import,
    # döngüsel bağımlılık olmasın diye fonksiyon içinde).
    from pipeline.retriever import _code_tokens
    toks = [t.lower() for t in _WORD_RE.findall(text)]
    toks += [t.lower() for t in _code_tokens(text)]
    return toks


def bm25_top(collection, query: str, n: int) -> list[tuple[str, dict]]:
    """Koleksiyonun tamamı üzerinde BM25; skoru > 0 olan top-n (doc, meta)."""
    key = (collection.name, collection.count())
    if _INDEX.get("key") != key:
        from rank_bm25 import BM25Okapi
        got   = collection.get(include=["documents", "metadatas"])
        docs  = got["documents"]
        metas = got["metadatas"]
        _INDEX.clear()
        _INDEX.update({
            "key"  : key,
            "docs" : docs,
            "metas": metas,
            "bm25" : BM25Okapi([_tokenize(d) for d in docs]),
        })
    docs, metas, bm25 = _INDEX["docs"], _INDEX["metas"], _INDEX["bm25"]
    scores = bm25.get_scores(_tokenize(query))
    order  = sorted(range(len(docs)), key=lambda i: scores[i], reverse=True)[:n]
    return [(docs[i], metas[i]) for i in order if scores[i] > 0]
