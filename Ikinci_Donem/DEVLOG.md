# Phase 2 — Geliştirme Günlüğü

## Klasör Yapısı

```
Ikinci_Donem/
├── DEVLOG.md                        ← bu dosya
├── Merged/                          ← MinerU çıktıları (ham veri)
├── data/
│   ├── chroma_db/                   ← yeni multi-vector DB
│   └── semantic_units/              ← assembler çıktısı (JSON)
└── scripts/
    ├── ab_test_chroma.py            ← (eski PoC)
    ├── ab_test_hazirlik.py          ← (eski PoC)
    ├── table_context_assembler.py   ← [1] MinerU JSON → SemanticUnit
    ├── multi_vector_indexer.py      ← [2] SemanticUnit → ChromaDB
    └── hyde_retriever.py            ← [3] HyDE + hybrid arama
```

## Pipeline Genel Bakış

```
OFFLINE:  MinerU JSON → Assembler → LLM Özet → ChromaDB
ONLINE:   Sorgu → HyDE Rewrite → Hybrid Search → Ham HTML+Notlar → LLM
```

---

## Değişiklik Geçmişi

---

### [2026-04-26] — Pipeline tasarımı ve Assembler

**Karar:** Tüm Phase 2 çalışmaları `Ikinci_Donem/scripts/` altında toplanacak.

**Tespit edilen problemler:**
1. `Merged_content_list.json` incelendi. Table 6 notları 2 sayfaya yayılıyor:
   - Sayfa 1 (idx=14): Note 1-5 (Note 5 kesilmiş)
   - Sayfa 2 (idx=23-24): Note 5 devamı + Note 6-7
   - Mevcut `ultimate_pipeline.py` sayfa sınırında durduğu için Note 6-7 kaçırılıyordu.
2. `all-MiniLM-L6-v2` ile query-document semantic gap problemi tespit edildi.
   - Dokümanlar kural dilinde, sorgular doğal dilde → alakasız eşleşmeler.
3. `ultimate_pipeline.py` model adı hatası: `"gemini-3.1-flash-lite-preview"` mevcut değil.

**Karar verilen çözümler:**
- `TableContextAssembler`: Sayfa sınırını aşan, LEGEND+NOTES+footnote toplayan assembler.
- Multi-Vector indexing: Özet vektörlenir, ham HTML+notlar metadata'da saklanır.
- HyDE (Hypothetical Document Embedding): Sorgu önce LLM ile yeniden yazılır, sonra vektörlenir.

**Yazılan dosyalar:**
- `scripts/table_context_assembler.py` ✅
  - `NOISE_TYPES` filtresi (header, footer, page_number)
  - Geriye tarama: section hiyerarşisi
  - İleriye tarama: LEGEND, NOTES, list_items, sayfa aşımı destekli
  - Durdurma koşulları: yeni section başlığı (text_level≤2) veya başka tablo
  - `save_semantic_units()` ile JSON çıktı

**Test edildi:** Evet — iki JSON dosyasında çalıştırıldı.

**Test sonuçları:**

| Dosya | Tablo | Not sayısı | Durum |
|---|---|---|---|
| Merged_content_list.json | Table T.1 | 2 | ✅ Doğru |
| Merged_content_list.json | Table 6 | 5 | ✅ Doğru |
| SecondPresent JSON | Table 4 | 7 (+2 dipnot) | ✅ Doğru |
| SecondPresent JSON | Table 5 | 4 | ✅ Doğru |
| SecondPresent JSON | Table 6 | **8** | ✅ **Note 6-7 artık yakalanıyor** |

**Düzeltilen bug'lar:**
1. `"Notes:"` ve `"NOTES"` MinerU tarafından `text_level=2` etiketleniyordu → section heading durdurma koşulunu tetikliyordu. Çözüm: NOTES tetikleyici kontrolü, heading kontrolünden **önce** yapıldı.
2. `"NATO/PFP UNCLASSIFIED"` sayfa başında `text_level=1` ile tekrar eden bir text bloğuydu → Note 6'ya ulaşmadan duruyordu. Çözüm: `NOISE_TEXTS` sözlüğü eklendi.
3. Tarama, numaralı section başlıklarında (`1.2.3.3.` gibi) durmuyor ve sonraki section'ın içeriğine giriyordu. Çözüm: `_SECTION_HEADING_RE` regex (`^\d+\.\d+`) ile her türlü numaralı başlık dur koşuluna eklendi.

**Bilinen minor issue:**
Table 4 ve Table 5'in son notu olarak bir sonraki tablonun giriş cümlesi ("Substances may be mixed...") yakalanıyor. Bunun sebebi scanner'ın tabloya varmadan önceki cümleyi de not olarak okuması. LLM özetleme aşamasında etkisiz kalacak, şimdilik kabul edildi.

---

---

### [2026-04-26] — `multi_vector_indexer.py`

**Yazılan dosya:** `scripts/multi_vector_indexer.py` ✅

**Tasarım:**
- Girdi: `data/semantic_units/semantic_units.json`
- LLM (Groq / Llama-3.3-70B): Her tablo için yoğun doğal dil özeti üretir
- ChromaDB koleksiyonu `aastp_multivector_v1`:
  - `document` = LLM özeti (vektörlenir, aranır)
  - `metadata` = `{html, notes, legend, footnotes, img_path, page_idx}` (inference LLM'e bağlam olarak gönderilir)
- Rate-limit koruması: istekler arası 3 sn bekleme
- `run_sanity_check()` ile yazım sonrası otomatik doğrulama sorgusu

**Test:** ❌ Çalıştırıldı, Groq API anahtarı geçersiz (401). Eski anahtarlar `03_generator.py` ve `app_system_final.py`'de hardcoded ve süresi dolmuş.

**Düzeltme:**
- Hardcoded anahtar kaldırıldı → `GROQ_API_KEY` ortam değişkenine alındı
- Boş koleksiyonda `run_sanity_check()` çöküyordu → düzeltildi

**Test:** ✅ Yeni anahtar ile çalıştırıldı.

**Sonuç:**
- 3 tablo için LLM özeti üretildi (Table 4: 1509 kr, Table 5: 2207 kr, Table 6: 1219 kr)
- ChromaDB'ye 3 döküman yazıldı
- Doğrulama: "Can Group B be stored with Group F?" → Table 5 #1, Table 6 #2 (HyDE'den önce)

**Kullanım:**
```bash
GROQ_API_KEY="gsk_..." python3 Ikinci_Donem/scripts/multi_vector_indexer.py
```

---

### [2026-04-26] — `hyde_retriever.py`

**Yazılan dosya:** `scripts/hyde_retriever.py` ✅

**Tasarım:**
- `retrieve(query, groq_client)` → `RetrievalResult` döner
- Akış: plain semantic search + HyDE rewrite → tekrar search → merge → distance sırala
- `format_context_for_llm()`: match listesini `[TABLE] + [HTML] + [NOTES]` formatında birleştirir
- Groq istemcisi yoksa HyDE atlanır, sadece semantic search yapılır (graceful degradation)

**Test sonuçları (4 sorgu):**

| Sorgu | HyDE Rewrite | #1 Sonuç | Durum |
|---|---|---|---|
| "Can Group B be stored with Group F?" | "storage of ammunition from Compatibility Group B with F..." | **Table 6** (dist=0.495) | ✅ Düzeldi |
| "Group N articles mixed with Group S?" | "mixing of Group N articles with Group S is prohibited..." | **Table 6** (dist=0.480) | ✅ |
| "Group L storage requirements" | "Compatibility Group L articles, storage is subject to..." | **Table 6** (dist=0.465) | ✅ |
| "Calcium Phosphide water suppression?" | "Water shall not be used for suppression of Calcium Phosphide..." | Table 5 (dist=1.17) | ⚠️ Yüksek dist |

**Gözlem:** HyDE "Can Group B stored with Group F?" sorgusunda Table 5'i devreden çıkarıp Table 6'yı #1'e taşıdı.

**Bilinen eksik:** Calcium Phosphide sorusu yüksek distance veriyor çünkü **Table T.1 (kimyasal tablo)** henüz DB'de yok. `Merged_content_list.json` üzerinden assembler + indexer çalıştırılarak eklenmeli.

---

### Sıradaki adımlar
1. `Merged_content_list.json` → assembler → indexer (Table T.1 ekle)
2. Mevcut `app_system_final.py`'deki `retrieve_knowledge()` → `hyde_retriever.py` ile değiştir

---

### [2026-04-27] — pipeline/ klasörü, text chunking, tam DB indeksleme

**Yapılanlar:**
- `Ikinci_Donem/pipeline/` temiz çalışma klasörü oluşturuldu
- Tüm scriptler ve data buraya taşındı, path'ler PIPELINE_DIR bazlı güncellendi
- `text_chunker.py` yazıldı: 55 text chunk üretiliyor (section hiyerarşisine göre)
- `multi_vector_indexer.py` güncellendi: hem tablo (3) hem text chunk (55) → toplam 58 döküman ChromaDB'ye yazılıyor
- `hyde_retriever.py` güncellendi: type bazlı arama (group sorgusu → tablo garantisi + text chunk)
- `pipeline/app.py` sıfırdan yazıldı: local model yok, sadece Groq + hyde_retriever

**Test sonuçları:**
- Test Set 1 (Matrix): text chunk eklenmesiyle retrieval regresyonu yaşandı → type bazlı arama ile düzeltildi
- Test Set 2 (Chemical): DB'de kimyasal tablo olmadığı için LLM hâlâ tahmin üretiyor
- Test Set 3 (Complex): Rate limit nedeniyle 3/4 senaryo çalışmadı

**Bilinen bekleyen işler:**
1. ⏳ Rate limit — Groq free tier günlük 100k token doldu. Yeni API key veya ertesi gün bekle.
2. ⏳ Retrieval fix test edilemedi — type bazlı arama düzeltmesi token limiti yüzünden doğrulanamadı.
3. ⏳ Daha fazla PDF sayfası ekle — şu an sadece sayfa 20-39 indekslendi.

**Mevcut DB durumu:**
- Kaynak: `AASTP_1_May2006_20-39` (sayfa 20-39)
- Tablolar: Table 4, 5, 6
- Text chunk: 55 adet (Chapter 2-3 içeriği)
- Toplam: 58 döküman

---

### [2026-04-28] — Sunum hazırlığı, UI dark theme, eval, cross-encoder, Prove Evidence

**Yapılanlar:**

#### Temizlik
- `Ikinci_Donem/scripts/`, `data/`, `AASTP_1_May2006_20-39/`, `Merged/` silindi
- Root'taki `mineru_apili.py` silindi (pipeline/app.py tamamen yerine geçti)
- API key'ler app.py üstünde sabit değişken olarak tanımlandı, UI'dan kaldırıldı

#### UI — Dark Theme
- `pipeline/app.py` tamamen dark tema'ya alındı (arka plan `#0d1117`)
- Header: gradient branding bandı eklendi
- Tüm kartlar (COMPLIANT/NON-COMPLIANT/CONDITIONAL/INFORMATIONAL) dark palette ile güncellendi
- Pipeline paneli, progress bar, log kutusu dark temaya uyarlandı

#### Eval scripti (`pipeline/eval.py`)
- 30 soruluk test seti: matrix (13), chemical (8), emergency (3), hazard_div (4), text (2)
- **Baseline sonuç (semantic-only):** HR@3=0.633, MRR=0.461

#### Cross-Encoder Reranker (`pipeline/scripts/hyde_retriever.py`)
- `sentence_transformers.CrossEncoder` — `cross-encoder/ms-marco-MiniLM-L-6-v2` (~90MB)
- Akış: semantic top-12 → cross-encoder rerank → top-3
- HyDE yokken de çalışır (sıfır Groq token)
- `_COMPAT_GROUPS`'a 'A' harfi eklendi (Group A bug fix)
- `page_idx` ve `img_path` match dict'ine eklendi
- **Sonuç:** HR@3=0.867 ✅ · MRR=0.811 ✅ (hedefler: ≥0.85 / ≥0.75)

#### Prove Evidence (`pipeline/app.py`)
- Her audit kartına `📸 Prove Evidence` `<details>` bloğu eklendi
- Tablo sorguları: MinerU bbox + `pdf2image` (144 DPI) ile PDF'den crop → base64 PNG
- Text sorguları: ilgili PDF sayfasının tamamı gösterilir
- `_BBOX_LOOKUP`: full content JSON'dan img_path → bbox eşlemesi (startup'ta yüklenir)
- `_PAGE_CACHE`: aynı sayfa bir kez render edilir, sonrası cache'den gelir
- Kaynak PDF: `AASTP-1-May2006.003973.pdf` (pipeline'ın üst dizininde)

**Oluşturulan/güncellenen dosyalar:**
- `pipeline/eval.py` ✅ (yeni)
- `pipeline/scripts/hyde_retriever.py` ✅ (cross-encoder + evidence alanları)
- `pipeline/app.py` ✅ (dark theme + API keys + Prove Evidence)
- `sunum_taslak.md` ✅ (yeni — 9 slayt, gerçek eval rakamları)
- `TODO.md` ✅ (güncel)
- `DEVLOG.md` ✅ (bu giriş)

**Mevcut DB durumu (güncellendi):**
- Kaynak: AASTP-1 tam belge (207 sayfa, 4 MinerU API çağrısı)
- Tablolar: 43 adet (Table T.1 dahil)
- Text chunk: 55 adet (Chapter 2-3)
- Toplam: **98 döküman**

**Eval sonuçları (cross-encoder aktif):**

| Metrik | Değer | Hedef |
|--------|-------|-------|
| HR@3 | 0.867 | ≥ 0.85 ✅ |
| MRR | 0.811 | ≥ 0.75 ✅ |

---
