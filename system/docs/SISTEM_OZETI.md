# Sistem Özeti — Pipeline, Kararlar, Faydalar

> Tek bakışta: PDF → MinerU → tablo+text indeksleme → 2-kanallı 3+3 retrieval → LLM verdict.
> Domain-bağımsız (NATO AASTP-1 ile geliştirildi, UFC 4-010-01 ile sıfır kod değişikliğiyle doğrulandı).

---

## 1. Pipeline (nerede ne kullanılıyor)

| # | Aşama | Dosya | Ne yapar / Ne kullanır |
|---|---|---|---|
| 1 | **PDF parse** | `scripts/mineru_batch.py` | PDF 50 sayfalık parçalara bölünür, catbox'a yüklenir, **MinerU cloud API** ile tablo+text çıkarılır. Parçalar **tam paralel** işlenir. |
| 2 | **Tablo birleştirme** | `scripts/table_assembler.py` + `pipeline/table_serializer.py` | Parçaların `content_list`'leri deterministik birleşir; her tablo **jenerik serializer** ile prose'a çevrilir (hard-code yok, yapısal tespit). Dipnot/legend tabloya iliştirilir. |
| 3 | **Text chunking** | `scripts/text_chunker.py` | Metin bloklara bölünür; `chunk_id = chunk_p{page}_idx{N}` (blok-indeksine bağlı, stabil). Uzun chunk'lar pencerelenir. |
| 4 | **İndeksleme** | `pipeline/kb_builder.py` | **bge-large-en-v1.5** ile embed (GPU), **ChromaDB**'ye toplu (`batch=128`) yazılır. KB = 31 tablo + 248 chunk → 336 doküman. |
| 5 | **Retrieval** | `pipeline/retriever.py` | 2 kanal: tablo (tümü aday) + text (160-derinlik havuz + **BM25** `lexical.py`). Her kanal **bge-reranker-base** (fp16, GPU) ile yeniden sıralanır → **3 tablo + 3 text** (SPLIT, füzyon yok). |
| 6 | **Verdict** | `pipeline/auditor.py` | Her madde için bağlam **gpt-oss-120B @ Cerebras**'a gönderilir → UYGUN / UYGUN DEĞİL. Retrieval prefetch + kayar-pencere tempo. |
| 7 | **Arayüz** | `server.py` + `templates/` | FastAPI + HTMX + Tailwind; canlı günlük, KB yönetimi, denetim raporu görünümü. |

Tüm ayarlar tek yerde: **`config.py`** (her özellik bir bayrakla aç/kapa).

---

## 2. Tasarım Kararları ve Faydaları

| Karar | Neden / Fayda |
|---|---|
| **3+3 SPLIT (modalite-ayrık, füzyon yok)** | Her istatistiksel füzyon (RRF, geniş havuz, z-norm) bir modaliteyi geriletti. Yapısal ayrıştırma kalıcı çözüm. → **text HR@3 54.5 → 84.5**, tablolar 99.3/99.3/98.0. |
| **bge-reranker-base (yerel, GPU)** | Asıl kalite kaldıracı; güçlü reranker olmadan füzyonsuz split de yetersizdi. |
| **Jenerik tablo serializer** | Hard-code yok → **domain-bağımsızlık** (UFC sıfır kod değişikliğiyle çalıştı). |
| **Dipnot/legend iliştirme** | Tablodaki kritik dipnotlar ayrık sistemde kaybolmasın diye doküman metnine bağlanır. |
| **CONTEXT_CHAR_CAP = 24000** | Eski 6000 sınırı text bloklarını tamamen kesiyordu → verdict düşüyordu. Düşürülmemeli. |
| **MinerU tam paralel** | Süre = parça toplamı yerine **en yavaş parça**; çıktı bayt-aynı. → MinerU ~10 dk → ~2-2.5 dk. |
| **Reranker fp16 + batch64** | Kalite **birebir korundu**, retrieval **4.76 → 1.33 sn/sorgu (3.6x)**. (`max_length=320` kapıdan döndü → 512'de kaldı.) |
| **Toplu ChromaDB add + retriever cache + tek sorgu embed** | İndeksleme ~30 sn → ~5-8 sn; gereksiz tekrar embed/client kalktı. |
| **Denetim prefetch + kayar-pencere tempo** | N+1 retrieval'ı N'in LLM çağrısıyla paralel; Cerebras 5 istek/dk limitine **proaktif** uyum (429 körlüğü ve DEĞERLENDİRİLEMEDİ düşmeleri bitti). |
| **Sunucu açılış ısınması** | İlk sorguda model yükleme gecikmesi olmaz. |
| **API key'ler config.py'de** | Bilinen teknik borç (.env'e taşınacak). |

---

## 3. Güncel Metrikler

### 3a. Retrieval (eval_all_faz7_generic_serializer, top_k=5)

| Set | n | HR@1 | HR@3 | HR@5 | MRR |
|---|---|---|---|---|---|
| set1 (tablo) | 150 | 92.0 | **99.3** | 99.3 | 95.7 |
| set2 (tablo) | 150 | 94.0 | **99.3** | 100.0 | 96.6 |
| set3 (tablo) | 150 | 86.7 | **98.0** | 100.0 | 91.9 |
| text (chunk) | 200 | 68.5 | **84.5** | 88.0 | 76.6 |
| text (sayfa) | 200 | 71.0 | **85.0** | 90.0 | 78.5 |

> text baseline HR@3 = 54.5'ti → 3+3 split + bge-reranker ile **84.5**.

### 3b. Verdict — gpt-oss-120B @ Cerebras (en güncel, 3+3 / 6-doküman bağlam, `split6doc`, 150 senaryo)

**Genel: 94.7% (142/150)** — tüm 150 madde değerlendirildi, DEĞERLENDİRİLEMEDİ yok. Serializer iki-kusur düzeltmesi sonrası (2026-06-13; öncesi 88.7%, bkz. TEST_RAPORU §10).

| Tablo | Doğruluk |
|---|---|
| Table 4 | 96.7 (29/30) |
| Table 133 | 96.7 (29/30) |
| Table 5 | 93.3 (28/30) |
| Table 6 | 93.3 (28/30) |
| Table T.2 | 93.3 (28/30) |

> Sınıf bazında: UYGUN 75/81 doğru · UYGUN DEĞİL 67/69 doğru (ihlalleri çok güvenilir yakalıyor).
> T.2 70→93.3, Table 5 86.7→93.3 sıçradı (LaTeX formül + X-matris hizası düzeltmesiyle).

### 3c. Daha önce lokalde/bulutta denenen LLM'ler (model merdiveni, eski 3-doküman bağlam)

| Model | Params | Sağlayıcı | Doğruluk |
|---|---|---|---|
| **gpt-oss-120b** (seçildi) | 120B | Cerebras | **89.1%** (123/138) |
| llama-4-scout-17b | 17B | Groq | 80.4% (111/138) |
| llama-3.3-70b-versatile | 70B | Groq | (eksik koşu, limit) |
| qwen2.5-3b | 3B | Ollama (yerel) | 65.9% (91/138) |
| llama-3.1-8b-instant | 8B | Groq | 48.5% (97/200) |

> Sonuç: 120B açık ara en iyi; küçük modeller (≤8B) ikili kararı güvenilir veremiyor. gpt-oss-120B üretim modeli seçildi.

**Sıfırdan-sona (AASTP, 207 sayfa + 20 maddelik denetim):** ~15 dk → **~7 dk**.

---

## 4. Disiplin

- Sıralamayı etkileyen her değişiklik → `tools/eval_all.py --tolerance 0.02` kapısı.
- LLM girdisini değiştiren → verdict benchmark.
- Kabul → commit + `TEST_RAPORU.md`'ye ablation satırı.
- Tüm kararların ölçümlü gerekçesi ve reddedilen alternatifler: **`docs/TEST_RAPORU.md`** (bölüm 8-9).

---

## 5. Test Tablolarının AASTP-1'deki Konumu

Verdict setindeki 5 tablo (`page_idx` = MinerU 0-tabanlı PDF indeksi → PDF sayfası = idx+1):

| Tablo | Tam adı | PDF sayfası |
|---|---|---|
| Table 4 | Aboveground Storage, Mixing and Aggregation Rules for HD | 28 |
| Table 5 | Aboveground Storage of Explosive Substances – Rules | 29 |
| Table 6 | Aboveground Storage of Explosive Articles – Rules | 30 |
| Table T.2 | Emergency Withdrawal Distances for Nonessential Personnel | 149 |
| "Table 133" | Hazard Division / Fire Division eşleme tablosu (formal adı yok; test setinde sayfasına göre etiketli) | 134 |

> Resmî baskıdaki yazılı sayfa no, ön-sayfa (kapak/içindekiler) ofseti kadar farklı olabilir; yukarıdaki PDF sayfası dosyada doğrudan o tabloya gider.
