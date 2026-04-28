# Phase 2 — Görev Listesi

Güncelleme: 2026-04-28

---

## ✅ Tamamlananlar

### Altyapı & Pipeline
- [x] `table_context_assembler.py` — MinerU JSON → SemanticUnit; sayfa sınırını aşan notlar yakalanıyor
- [x] `multi_vector_indexer.py` — SemanticUnit → ChromaDB; Groq ile LLM özeti üretimi
- [x] `hyde_retriever.py` — HyDE rewrite + hybrid semantic search
- [x] `text_chunker.py` — Bölüm hiyerarşisine göre text chunk üretimi
- [x] `mineru_batch.py` — 207 sayfalık PDF'i 50'şer sayfalık chunk'larla MinerU API'ye gönderir (resume destekli)

### Veri & Veritabanı
- [x] Tam AASTP-1 PDF işlendi (207 sayfa, 4 API çağrısı)
- [x] ChromaDB: **98 döküman** (43 tablo + 55 text chunk)
- [x] Table T.1 (kimyasal tablo) eklendi — Calcium Phosphide, WP, Napalm sorguları artık çalışıyor

### Uygulama & Arayüz
- [x] Gradio app iki sekme: **Audit** + **Index New Document**
- [x] 3 audit modu: Full (HyDE+LLM) / Fast (no HyDE+LLM) / Context Only (0 token)
- [x] `INFORMATIONAL` verdict tipi — bilgi soruları COMPLIANT olarak etiketlenmeyecek
- [x] Karanlık (dark) tema — askeri/savunma görünümü
- [x] API key'ler sabit değişken olarak tanımlandı, UI'dan kaldırıldı
- [x] Klasör temizliği — eski scriptler, eski DB, kısmi veri dosyaları silindi

---

## ⏳ Yapılacaklar

### Öncelik 1 — Sunum için Kritik

- [x] **`eval.py` — Metrik hesaplama**
  - 30 soruluk test seti: matrix / chemical / emergency / hazard_div / text
  - Hit Rate@3 ve MRR hesapla (0 Groq token — sadece semantic search)
  - Hedef: HR@3 ≥ 0.85 · MRR ≥ 0.75 (1. dönem 2. sunumda vaat edildi)
  - Çalıştır: `python3 Ikinci_Donem/pipeline/eval.py`

- [ ] **Sunum slaytları** (2. dönem 2. sunum, ~10 slayt)
  - Problem & motivasyon
  - Sistem mimarisi (OFFLINE/ONLINE pipeline)
  - Teknik katkılar: TableContextAssembler, HyDE, Multi-Vector
  - Eval sonuçları (HR@3 / MRR)
  - Canlı demo ekran görüntüleri
  - Sonuç ve gelecek çalışmalar

### Öncelik 2 — Retrieval Kalitesi (API'siz)

- [x] **Cross-encoder reranker — HyDE alternatifi**
  - `hyde_retriever.py`: semantic top-12 → cross-encoder rerank → top-3
  - Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (indirildi, cache'de)
  - **Sonuç: HR@3 0.633 → 0.867 ✅ · MRR 0.461 → 0.811 ✅**
  - Sıfır API, re-indexing gerektirmedi

- [x] **eval.py güncelle** — sunum_taslak.md Slayt 8 rakamlar güncellendi

### Öncelik 3 — Arayüz

- [x] **"Prove Evidence" butonu**
  - Her audit kartında `<details>` bloğu: tıklanınca görsel açılır
  - Tablo: MinerU bbox + pdf2image ile PDF sayfasından crop (144 DPI, 1:1 uyumlu)
  - Text: ilgili PDF sayfasının tamamı
  - `_BBOX_LOOKUP` dict: full content JSON'dan img_path → bbox eşlemesi
  - `_PAGE_CACHE`: aynı sayfa tekrar render edilmez
  - `page_idx` ve `img_path` zaten ChromaDB metadata'sında mevcut

### Öncelik 4 — Kalite İyileştirme

- [ ] **Noise table filtresi**
  - Assembler'a `NOISE_CAPTIONS` kümesi ekle
  - Filtre edilecekler: "NATO/PFP UNCLASSIFIED", "RECORD OF CHANGES", "Figure B-I/III/IV"
  - DB'yi yeniden indekslemek gerekecek (Groq token kullanır)

- [ ] **Text chunk genişletme**
  - `text_chunker.py` şu an yalnızca Chapter 2-3'ü kapsıyor
  - Tam PDF üzerinde çalıştırılacak → daha fazla text chunk eklenecek

- [ ] **Napalm retrieval fix**
  - Napalm sorgusu Table T.1'i #2 olarak getiriyor, #1 olmalı
  - Çözüm: indexer'daki özetleme promptunu iyileştir
