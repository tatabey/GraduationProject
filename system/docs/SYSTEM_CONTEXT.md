# Standart Uygunluk Denetim Sistemi — Bağlam Dosyası

Her konuşmanın başında bu dosyayı oku. Sıfırdan açıklamak yerine buradan devam et.

---

## Projenin Amacı

Genel amaçlı bir **RAG tabanlı standart uygunluk denetim sistemi**.
- Kullanıcı herhangi bir standart belgesini (PDF) yükler → sistem ChromaDB'ye indeksler
- Kullanıcı bir denetim raporu (PDF, numaralı maddeler) yükler → her madde KB'ye sorgulanır → LLM verdict üretir
- Verdict'ler: **UYGUN / UYGUN DEĞİL** (binary)
- Teknik aksaklıklar için ayrı durum: **DEĞERLENDİRİLEMEDİ** (verdict sayılmaz, metriği bozmaz)
- Test standardı: NATO AASTP-1 (patlayıcı depolama kuralları)

---

## Klasör Yapısı

```
system/
├── config.py                  ← tüm sabitler (API key, model, dizinler)
├── server.py                  ← FastAPI sunucusu (GİRİŞ NOKTASI)
├── pipeline/                  ← çekirdek RAG mantığı
│   ├── kb_builder.py          ← PDF → ChromaDB (MinerU + embedding)
│   ├── report_parser.py       ← denetim raporu PDF → numaralı maddeler
│   ├── retriever.py           ← dual-query semantic search + cross-encoder rerank
│   ├── auditor.py             ← retrieve → Cerebras gpt-oss-120B → verdict
│   └── table_serializer.py    ← tablo HTML → LLM bağlamı
├── scripts/                   ← veri hazırlama (pipeline tarafından kullanılır)
│   ├── mineru_batch.py        ← PDF → MinerU API → content_list.json
│   ├── table_assembler.py     ← JSON → SemanticUnit (tablo + notlar)
│   └── text_chunker.py        ← JSON → TextChunk (bölüm hiyerarşisi)
├── tools/                     ← geliştirme / değerlendirme araçları
│   ├── benchmark_local.py     ← çok-model doğruluk karşılaştırması (138 senaryo)
│   ├── eval_verdict.py        ← verdict doğruluğu ölçümü (benchmark çıktısına karşı)
│   ├── eval_retrieval.py      ← retrieval-only metrik ölçümü (HR@k, MRR)
│   ├── diagnose_retrieval.py  ← retrieval + LLM girdi/çıktı tanı scripti
│   ├── reindex_tables.py      ← ChromaDB'yi mevcut JSON'lardan sıfırdan kurar
│   └── table_experiment.py    ← 6 serileştirme metodunu karşılaştıran ablasyon
├── docs/                      ← belgeler
│   ├── SYSTEM_CONTEXT.md      ← bu dosya
│   ├── TEST_RAPORU.md         ← tüm test geçmişi ve kararların gerekçeleri
│   └── GELISTIRME_PLANI.md    ← P0→P2 teknik geliştirme planı
├── templates/
│   └── index.html             ← Tailwind + HTMX tek sayfa arayüz
└── data/
    ├── kbs/                   ← KB'lerin depolandığı yer
    │   └── aastp_test/        ← aktif KB (NATO AASTP-1, 207 sayfa)
    │       ├── kb_meta.json
    │       ├── chroma_db/     ← aktif ChromaDB vektör indeksi (73 MB)
    │       ├── semantic_units/← 30 tablo (semantic_units.json)
    │       ├── text_chunks/   ← 438 text chunk (text_chunks.json)
    │       └── mineru_chunks/ ← ham MinerU çıktıları (5 × 50 sayfa)
    ├── benchmark/             ← model doğruluk sonuçları
    ├── reports/               ← test/denetim PDF'leri
    │   ├── Denetim Raporu.pdf ← test raporu (10 madde, AASTP-1 karşı)
    │   └── test_scenarios.pdf ← test senaryoları PDF görünümü
    └── test_scenarios.json    ← 138 binary senaryo (75 UYGUN + 63 UYGUN DEĞİL)
```

---

## Çalıştırma

```bash
python3 system/server.py
# → http://127.0.0.1:8000
```

---

## Mimari

```
OFFLINE (indeksleme):
  PDF
    → scripts/mineru_batch.py      (MinerU VLM API, 50 sayfa/chunk)
    → scripts/table_assembler.py   (30 tablo, NOTES/LEGEND sayfa aşımıyla)
    → scripts/text_chunker.py      (438 text chunk, bölüm hiyerarşisi)
    → pipeline/kb_builder.py       (BAAI/bge-large-en-v1.5 → ChromaDB)

ONLINE (denetim):
  Denetim raporu PDF
    → pipeline/report_parser.py    (numaralı maddeler çıkarır)
    → pipeline/retriever.py        (dual-query + z-norm + cross-encoder rerank)
    → pipeline/auditor.py          (Cerebras gpt-oss-120B → verdict + gerekçe)
```

**Embedding:** `BAAI/bge-large-en-v1.5` (1024-dim)  
**Reranker:** `cross-encoder/ms-marco-MiniLM-L-6-v2` (modalite-içi z-normalizasyon)  
**LLM (denetim):** Cerebras `gpt-oss-120b` (%89.1 doğruluk, 5 RPM exponential backoff)

---

## Retrieval Mimarisi

Karma modaliteli KB (tablo + metin) için özel çözümler:

| Teknik | Sorun | Çözüm |
|--------|-------|-------|
| **Dual-query** | Tablolar 438 chunk içinde boğuluyordu | Genel sorguya ek tablo-specific sorgu havuza eklenir |
| **Modalite-içi z-normalizasyon** | ms-marco tabloları ~10 puan düşük skorluyordu | Tablo ve metin skorları kendi grubu içinde normalize edilir |
| **Jenerik kod-token bonusu** | HD 1.1, Table 4 gibi token örtüşmesi kaçırılıyordu | Domain-agnostik regex bonus (HD'ye özel sabit yok) |
| **Yumuşak tablo tabanı** | Tablolar zaman zaman 2.-3. sıraya düşüyordu | En iyi tablo medyan üstüyse 1 slot rezerve edilir |

**Ölçüm:** HR@3 = %98.5, MRR = 0.908 (5 kritik tablo, 138 senaryo)

---

## Mevcut Test KB'si

`system/data/kbs/aastp_test/` — NATO AASTP-1 standardı (207 sayfa, Mayıs 2006):
- **30 tablo** (semantic_units.json) + **438 text chunk** = **468 döküman**
- Aktif koleksiyon: `kb_meta.json` içindeki `collection` alanına bakılır
- Önceki `aastp_v2` (292 döküman) — artık kullanılmıyor

---

## Model Doğruluk Sonuçları

| Model | Params | Sağlayıcı | Doğruluk |
|-------|--------|-----------|----------|
| qwen2.5:3b | 3B | ollama | %65.9 |
| llama-4-scout | 17B | groq | %80.4 |
| **gpt-oss-120b** | **120B** | **cerebras** | **%89.1** ← üretim |

Ayrıntılar: `docs/TEST_RAPORU.md`

---

## Önemli Teknik Notlar

- **HTMX polling:** Form submit → job → `hx-get="/kb/poll/{job_id}"` her 1.5sn → job bittinde `hx-swap-oob`
- **Tablo görseli:** `_source_label()` → `img_path` → `_table_btn()` → URL → `openTableModal()` → `<img>`
- **Cerebras 5 RPM:** `auditor.py`'de exponential backoff: 429 → 5s → 10s → 20s bekle, 4 deneme
- **content=None koruması:** Reasoning modeli token bitince None döner; `content or ""` + `LLM_MAX_TOKENS=2000`
- **Verdict cache (benchmark):** SHA256(label + prompt_hash + item + context); prompt değişince otomatik geçersiz
- **API key'ler:** `config.py`'de env var öncelikli, hardcoded fallback var (P1.1: .env'e taşınmalı)
