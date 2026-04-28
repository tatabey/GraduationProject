# 2. Dönem 2. Sunum — İçerik Taslağı
Güncelleme: 2026-04-28 | 9 slayt | ~15 dk sunum

---

## Slayt 1 — Kapak

**Başlık:** AASTP-1 Smart Ammunition Storage Audit System
**Alt başlık:** AI-Powered NATO Compliance Retrieval — Phase 2 Progress Report
İsim · Danışman · Tarih

---

## Slayt 2 — Proje Tanımı: Hatırlatma

**Bağlam:** 2 dönemlik bitirme projesi — bu sunum Phase 2'nin ara raporu

**Problem:**
- NATO AASTP-1 standardı: 200+ sayfa, onlarca karmaşık uyumluluk tablosu
- Patlayıcı depolama denetçisi hangi maddenin hangi grupla saklanamayacağını **elle** araştırmak zorunda
- Tablolar arası çapraz referanslar ve sayfa aşan notlar → kritik kurallar gözden kaçıyor
- Kimyasal tehlikeler (PPE, "Apply No Water") ayrı tablolarda dağınık

**Çözüm:**
- Doğal dilde sorgu → otomatik mevzuat taraması → şeffaf karar
- 4 verdict tipi: **COMPLIANT · NON-COMPLIANT · CONDITIONAL · INFORMATIONAL**
- Hangi tablodan, hangi nottan karar verildiği kullanıcıya gösterilir

**1. dönem sonunda belirlenen başarı kriterleri:**
- Hit Rate@3 ≥ 0.85
- MRR ≥ 0.75

**Görsel:** Sol — elle araştırma iş akışı (5 adım, çok zaman). Sağ — AI audit sistemi (1 adım, anlık).

---

## Slayt 3 — Phase 1 → Phase 2: Ne Değişti?

**1. dönem Ocak 2026 sunumundan bu yana yapılanlar:**

| | Phase 1 *(Ocak 2026)* | Phase 2 *(Nisan 2026)* |
|---|---|---|
| Veri kapsamı | Sayfa 20–39 (20 sayfa) | **Tam belge — 207 sayfa** |
| İndekslenen tablo | 3 | **43 tablo** |
| Toplam ChromaDB döküman | 58 | **98 (43 tablo + 55 chunk)** |
| Arama yöntemi | Basit semantic search | **Multi-Vector + Cross-Encoder** |
| Reranker | Yok | **ms-marco-MiniLM-L-6-v2 (yerel)** |
| Hit Rate@3 | ~0.46 | **0.867 ✅** |
| MRR | ~0.35 | **0.817 ✅** |
| Arayüz | Yok | **Gradio (Audit + Index, 3 mod)** |
| Yeni belge ekleme | Manuel script | **Arayüzden tek tıkla** |

**Görsel:** Tablo (Phase 1 sütunu soluk/gri, Phase 2 sütunu yeşil highlight ile)

---

## Slayt 4 — Sistem Mimarisi

**OFFLINE — Belge İndeksleme** *(bir kez çalışır)*
```
PDF
  → [1] MinerU API  (VLM-OCR: tablo yapısı + görseller korunur)
  → [2] TableContextAssembler  (notlar + sayfa aşımı çözülür)
  → [3] Groq LLM  (her tablo için arama özeti üretir)
  → [4] ChromaDB  (98 döküman: özet aranır, ham tablo LLM'e gider)
```

**ONLINE — Sorgu** *(anlık)*
```
Kullanıcı sorusu
  → [5] HyDE Rewrite (opsiyonel — Groq LLM)
  → [6] Semantic Search  → top-12 aday
  → [7] Cross-Encoder Rerank  → top-3
  → [8] Groq LLM  → COMPLIANT / NON-COMPLIANT / CONDITIONAL / INFORMATIONAL
```

**Kullanılan teknolojiler:**
MinerU VLM · Groq Llama-3.3-70B · ChromaDB · all-MiniLM-L6-v2 · ms-marco-MiniLM CrossEncoder · Gradio

**Görsel:** Dikey veya yatay akış diyagramı; OFFLINE kutusu mavi, ONLINE kutusu yeşil. Her adım numaralı.

---

## Slayt 5 — Karşılaşılan Zorluklar & Çözümler

### Zorluk 1: Sayfa Sınırını Aşan Tablo Notları
- **Problem:** MinerU her sayfayı ayrı JSON bloğu yazıyor; Table 6'nın notları iki sayfaya yayılıyor → pipeline Note 6-7'yi kaçırıyordu
- **Çözüm → TableContextAssembler:** Tablo bulununca ileriye tarama; yeni başlık veya farklı tablo gelene dek notlar toplanmaya devam eder
- **Sonuç:** Table 6 notları: 5 → **7** ✅ · Table T.1 kimyasal bilgisi eksiksiz

### Zorluk 2: Sorgu–Belge Semantik Uçurumu
- **Problem:** Kullanıcı dili (*"Can Group B be stored with F?"*) ile kural dili (*"Compatibility Group B × F: PERMITTED"*) vektör uzayında uzak → yanlış tablo geliyor
- **Çözüm → HyDE (Hypothetical Document Embedding):** LLM, sorguyu kural formatında yeniden yazar → vektörleştirme kural metnine yaklaşır

### Zorluk 3: Semantic Search Kısaltma Körlüğü
- **Problem:** *"HD 1.1"* ile *"Hazard Division 1.1"* farklı vektörde; ilgili tablo top-12'ye giremiyor
- **Çözüm → Cross-Encoder Reranker:** Semantic top-12 → `ms-marco-MiniLM-L-6-v2` → (sorgu, belge) çiftini birlikte değerlendirir → top-3
- **Sonuç:** Sıfır API token, yerel model

| | Semantic-only | + Cross-Encoder |
|---|---|---|
| HR@3 | 0.633 | **0.867** |
| MRR | 0.461 | **0.817** |

**Görsel:** 3 satır: her satırda ⚠️ Zorluk → 🔧 Çözüm → ✅ Sonuç formatında özet

---

## Slayt 6 — MinerU Entegrasyonu: Arayüze Gömülü Pipeline

**Önceki durum (Phase 1):**
- MinerU web arayüzü (mineru.net) → elle 20 sayfa sınırı
- JSON çıktısı manuel indirilip scriptle işleniyordu

**Şu anki durum (Phase 2):**
- MinerU **API** → sayfa sınırı yok
- Tüm pipeline Gradio arayüzüne gömüldü → tek tıkla yeni belge eklenebilir

**"Index New Document" akışı:**
1. PDF yükle
2. Otomatik 50 sayfalık chunk'lara bölünür
3. Her chunk MinerU API'ye gönderilir (VLM-OCR)
4. Tablo görselleri lokale kaydedilir
5. Chunk'lar birleştirilir → TableContextAssembler → Groq LLM → ChromaDB
6. Resume desteği: kesilirse kaldığı yerden devam eder

**Görsel:** Mevcut ekran görüntüsü (Index New Document sekmesi) + solunda 6 adımlı ok listesi

---

## Slayt 7 — Başarı Ölçütleri: Hedefler Aşıldı

**Test metodolojisi:** 30 sorgu · 5 kategori · Top-3 değerlendirme · **0 API token** (cross-encoder)

### Genel Metrikler

| Metrik | Sonuç | Hedef | Durum |
|---|---|---|---|
| Hit Rate@3 | **0.867** (26/30) | ≥ 0.85 | ✅ Aşıldı |
| MRR | **0.817** | ≥ 0.75 | ✅ Aşıldı |

### Kategori Kırılımı

| Kategori | Kaynak | Sorgu | HR@3 | MRR |
|---|---|---|---|---|
| Chemical | Table T.1 | 8 | **1.000** | **1.000** |
| Emergency | Table T.2 | 3 | **1.000** | **1.000** |
| Compatibility Matrix | Table 5–6 | 13 | **0.923** | **0.846** |
| Hazard Division | Table 4 | 4 | 0.750 | 0.625 |
| Text chunks | Ch. 2–3 | 2 | 0.000 | 0.000 |

**Başarısız 4 sorgu:** Hazard Div. kısaltma sorunu (HD 1.x) + text chunk yetersiz temsil → finale kadar iyileştirilecek

**Görsel:** İki tablo yan yana; genel metrikler büyük puntolu, kategori tablosunda Chemical ve Emergency satırları tam yeşil

---

## Slayt 8 — Çalışma Tablosu: Kim Nerede Ne Yaptı?

### Tamamlananlar

| Bileşen | Kendi Bilgisayarım | İşbirliği Firması |
|---|---|---|
| MinerU API entegrasyonu (4×50 sayfa) | ✅ | — |
| TableContextAssembler geliştirme | ✅ | — |
| Multi-Vector ChromaDB indeksleme | ✅ | — |
| HyDE retrieval | ✅ | — |
| Cross-encoder reranker | ✅ | — |
| 30 soruluk eval scripti | ✅ | — |
| Gradio arayüzü (Audit + Index) | ✅ | — |
| Planlanan GPU fine-tuning | — | ❌ Gerekmedi* |

*Groq API + RAG kombinasyonu hedef metriklere ulaştırdı; fine-tuning'e gerek kalmadı.

### Finale Kadar Yapılacaklar

| Görev | Kendi Bilgisayarım | İşbirliği Firması |
|---|---|---|
| Noise table filtresi (RECORD OF CHANGES vb.) | ⏳ | — |
| Hazard Div. kısaltma sorunu çözümü | ⏳ | — |
| Tam belge text chunk kapsamı (tüm Ch.) | ⏳ | — |
| Çoklu belge desteği (diğer NATO std.) | ⏳ | Değerlendirilecek |
| Gerçek denetim ortamı entegrasyonu | — | ⏳ |

**Görsel:** Tablo (iki bölümlü: tamamlananlar + yapılacaklar); sütunlar: Görev, Kendi PC, Firma

---

## Slayt 9 — Özet & Final'e Köprü

### Phase 2'de Tamamlananlar ✅
- Tam AASTP-1 belgesi işlendi (207 sayfa, 4 API çağrısı)
- 98 döküman ChromaDB (43 tablo + 55 text chunk)
- TableContextAssembler · Multi-Vector · HyDE · Cross-Encoder
- Uçtan uca Gradio pipeline: **PDF yükle → indeksle → sorgu → karar**
- Hit Rate@3 = **0.867** · MRR = **0.817** — her iki hedef **aşıldı**

### Final Sunumu İçin Kalan
- 🔧 Noise table filtresi
- 🔧 Hazard Division retrieval iyileştirmesi
- 🔧 Tam belge text chunk kapsamı
- 🔧 Çoklu belge & gerçek ortam entegrasyonu

### Temel Çıkarım
> Tablo yapısını bozmadan işleme (MinerU VLM) + bağlam bütünlüğü (TableContextAssembler) + iki aşamalı retrieval (Semantic → Cross-Encoder) kombinasyonu, fine-tuning olmadan hedef metrikleri aşmaya yetti.

**Görsel:** Sol — tamamlananlar listesi (yeşil checkmark). Sağ — finale kalan liste (turuncu saat ikonu). Alt — temel çıkarım kutusu.
