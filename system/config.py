"""
Sistem genelinde kullanılan tüm yapılandırma değerleri.
Hiçbir script içinde sabit değer bulunmayacak — buradan okunacak.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Dizinler
# ---------------------------------------------------------------------------
BASE_DIR   = Path(__file__).resolve().parent
DATA_DIR   = BASE_DIR / "data"
CHROMA_DIR = DATA_DIR / "chroma_db"

# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------
CHROMA_COLLECTION = "knowledge_base"

# ---------------------------------------------------------------------------
# Embedding modeli (yerel, GPU destekli)
# ---------------------------------------------------------------------------
EMBED_MODEL = "BAAI/bge-large-en-v1.5"

# ---------------------------------------------------------------------------
# Cross-encoder reranker (yerel)
# ---------------------------------------------------------------------------
RERANKER_MODEL  = "cross-encoder/ms-marco-MiniLM-L-6-v2"
TOP_K           = 3       # kaç sonuç dönsün
RERANK_FACTOR   = 4       # reranker için kaç kat fazla candidate al

# ---------------------------------------------------------------------------
# Modalite-dengeli retrieval (text vs tablo)
# ---------------------------------------------------------------------------
# Tablolar büyük text_chunk havuzunda boğulmasın diye, tüm tablo adayları
# ayrı bir sorguyla havuza eklenir. KB'de asla bu sayıdan fazla tablo olmaz.
TABLE_POOL_MAX   = 50
# Cross-encoder modalite-içi z-normalize edildikten sonra, sorgu↔doc kod-token
# (HD 1.1, Group K, Q-D, 1.2.1 vb.) örtüşmesine eklenen küçük bonus ağırlığı.
CODE_TOKEN_BONUS = 1.0
# Final top_k içinde en iyi tablo adayı için rezerve edilecek slot sayısı
# (yalnızca rekabetçiyse dahil edilir). 0 = kapalı.
TABLE_FLOOR      = 1

# ---------------------------------------------------------------------------
# Text chunk indeksleme (modalite-bağımsız, jenerik)
# ---------------------------------------------------------------------------
# Chunk embed dokümanına section hiyerarşisini (section_path) dahil et.
# Embedding'e bağlam katar; reranker girdisini de zenginleştirir.
EMBED_SECTION_PATH = True
# Boilerplate satır filtresi: normalize edilmiş bir satır ≥ N FARKLI sayfada
# tekrarlıyorsa (sayfa başlığı/altlığı kalıntısı) chunk içeriğinden çıkarılır.
# Domain'e özel değil — her PDF'in kendi tekrar eden başlıklarını yakalar.
# 0 = kapalı.
TEXT_BOILERPLATE_MIN_PAGES = 5
# Uzun chunk'lar embedding'de kırpılır (bge ~512 token ≈ 2000 char görür).
# Bu sınırı aşan chunk'lar paragraf sınırından pencerelere bölünüp AYNI
# chunk_id metadata'sıyla çoklu vektör olarak indekslenir (retriever dedupe
# bunları tek match'e indirger). 0 = kapalı.
CHUNK_EMBED_MAX_CHARS = 2000
# Chunk başına en fazla bu kadar sentetik soru ek vektör olarak indekslenir
# (tools/enrich_chunks.py çıktısı; yerel Ollama, sıfır cloud token).
# Senaryo-dili ↔ mevzuat-dili embedding boşluğunu indeks tarafında kapatır.
# 0 = kapalı.
CHUNK_SYNTH_QUERIES = 2

# ---------------------------------------------------------------------------
# Retrieval aday havuzu
# ---------------------------------------------------------------------------
# GENİŞ text kanalının derinliği (iki aşamalı seçim, aşama 2):
# final head'deki text slotlarının İÇERİĞİ bu derinlikteki text havuzundan
# rerank ile seçilir. Slot tahsisi (tablo/text dağılımı) ise her zaman dar
# baseline zincirinden gelir → tablo sonuçları yapısal olarak korunur.
# ≤ top_k*RERANK_FACTOR = kanal kapalı (saf baseline).
TEXT_FETCH_K = 160
# (Deneysel kalıntı, varsayılan kapalı) Dar zincirde z-norm öncesi tip başına
# aday kırpma. İki aşamalı seçim varken gerekmez. 0 = kapalı.
RERANK_SHORTLIST = 0
# BM25 lexical kanal: aday havuzuna (final sıralamaya DEĞİL) BM25 top-N eklenir.
# Paragraf numarası / kod atıflarını ("para 1.2.2.1") yakalar. False = kapalı.
BM25_ENABLED = True
BM25_TOP_N   = 10

# ---------------------------------------------------------------------------
# LLM — Groq (inference için)
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY",
    "***REMOVED***")
GROQ_MODEL   = "llama-3.3-70b-versatile"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Cerebras (ücretsiz, yüksek throughput, OpenAI-uyumlu)
CEREBRAS_API_KEY  = os.getenv("CEREBRAS_API_KEY",
    "***REMOVED***")
CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"

# ---------------------------------------------------------------------------
# Üretim denetim modeli (arayüz / auditor.py bunu kullanır)
# ---------------------------------------------------------------------------
# Ölçtüğümüz en iyi binary model: gpt-oss-120b @ Cerebras (%89.1).
# provider: "cerebras" | "groq" | "ollama" — değiştirmek için tek satır.
AUDIT_PROVIDER = "cerebras"
AUDIT_MODEL    = "gpt-oss-120b"

# ---------------------------------------------------------------------------
# Model-boyutu merdiveni (benchmark) — parametreye göre artan
# ---------------------------------------------------------------------------
# provider: "ollama" (yerel) | "groq" (ücretsiz cloud, OpenAI-uyumlu)
MODEL_LADDER = [
    {"label": "llama3.2:3b",              "params_b": 3.0,   "provider": "ollama"},
    {"label": "qwen2.5:3b",               "params_b": 3.0,   "provider": "ollama"},
    {"label": "phi4-mini",                "params_b": 3.8,   "provider": "ollama"},
    {"label": "llama-3.1-8b-instant",     "params_b": 8.0,   "provider": "groq"},
    {"label": "meta-llama/llama-4-scout-17b-16e-instruct", "params_b": 17.0, "provider": "groq"},
    {"label": "openai/gpt-oss-20b",       "params_b": 20.0,  "provider": "groq"},
    {"label": "qwen/qwen3-32b",           "params_b": 32.0,  "provider": "groq"},
    {"label": "llama-3.3-70b-versatile",  "params_b": 70.0,  "provider": "groq"},
    {"label": "openai/gpt-oss-120b",      "params_b": 120.0, "provider": "groq"},
    {"label": "gpt-oss-120b",             "params_b": 120.0, "provider": "cerebras"},
]

# Benchmark dayanıklılık / token bütçesi
GROQ_RPM_DELAY   = 2.0    # Groq çağrıları arası saniye (~30 RPM free tier)
LLM_MAX_TOKENS   = 2000   # reasoning modelleri (gpt-oss/qwen3) düşünme + VERDICT için alan
CONTEXT_CHAR_CAP = 6000   # API'ye giden bağlam üst sınırı (input token tasarrufu)

# ---------------------------------------------------------------------------
# LLM — Ollama (indeksleme özeti için, yerel)
# ---------------------------------------------------------------------------
OLLAMA_URL   = "http://localhost:11434/v1"
OLLAMA_MODEL = "llama3.2:3b"

# ---------------------------------------------------------------------------
# MinerU API (PDF → JSON)
# ---------------------------------------------------------------------------
MINERU_API_KEY = os.getenv("MINERU_API_KEY",
    "***REMOVED***")
MINERU_CHUNK_SIZE = 50  # sayfa başına chunk boyutu

# ---------------------------------------------------------------------------
# Verdict etiketleri (LLM çıktısı için) — binary
# ---------------------------------------------------------------------------
VERDICTS = ["UYGUN", "UYGUN DEĞİL"]
# Sınıflandırma değil, teknik aksaklık durumu (retrieval boş / API hatası /
# parse hatası). VERDICTS'e dahil DEĞİL — doğruluk metriğine girmez.
ERROR_VERDICT = "DEĞERLENDİRİLEMEDİ"
