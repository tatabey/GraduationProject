# Geliştirme Planı — AASTP-1 RAG Denetim Sistemi

> Projenin geri kalanı için **yalnızca teknik** geliştirme/iyileştirme/ekleme-çıkarma
> maddeleri. Öncelik sırası: **P0 (kritik) → P1 (orta) → P2 (düşük)**.
> Mevcut durum için bkz. `TEST_RAPORU.md`.

---

## P0 — Kritik / Yüksek Değer

### P0.1 — Model merdivenini tamamla (8B + 70B)
- **Neden:** Şu an eğride 3 nokta var (3B, 17B, 120B). 8B ve 70B noktaları eklenince
  parametre-doğruluk ilişkisi 5 noktayla çok daha güçlü gösterilir.
- **Engel:** 8B Groq'ta 6.000 TPM ile boğuluyor, Cerebras'ta erişilemiyor.
- **Çözüm:** 8B'yi **yerel Ollama** ile çalıştır (limit yok, ~40-60 dk). 70B'yi Groq
  (12.000 TPM) veya Cerebras üzerinden.
- **Beklenen etki:** Tam parametre-doğruluk eğrisi; "boyut arttıkça doğruluk artar"
  iddiasının sağlam veri temeli.
- **Dokunulacak:** `config.py` (MODEL_LADDER zaten hazır), çalıştırma komutu.

### P0.2 — Test seti kapsamını genişlet
- **Neden:** Hem retrieval (%98.5) hem verdict (%89.1) yalnız **5 tabloda** ölçüldü.
  KB'de 31 tablo var; sistemin genellenebilirliği kanıtlanmış değil.
- **Çözüm:** Diğer tablolar için yeni binary senaryolar üret (UYGUN/UYGUN DEĞİL),
  retrieval matcher'larını (`eval_retrieval.py` `TABLE_MATCHERS`) genişlet.
- **Beklenen etki:** Daha güvenilir, genellenebilir doğruluk iddiası.
- **Dokunulacak:** `data/test_scenarios_200.json`, `eval_retrieval.py`.

### P0.3 — Üretim sağlamlaştırma (rate-limit dayanıklılığı)
- **Neden:** Cerebras free tier **5 RPM** gerçek kullanımda dar; 20+ maddelik rapor
  yavaş. Tek sağlayıcıya bağımlılık kırılgan.
- **Çözüm:** Sağlayıcı **fallback zinciri** (Cerebras → Groq → yerel) — biri limite
  girince diğerine düş. Ya da ücretli tier değerlendirmesi.
- **Beklenen etki:** Kesintisiz denetim, demo güvenliği.
- **Dokunulacak:** `pipeline/auditor.py` (`make_client` + fallback mantığı).

---

## P1 — Orta Öncelik

### P1.1 — API anahtarı güvenliği
- **Neden:** `config.py`'de Groq, MinerU ve Cerebras anahtarları **gömülü** (hatta
  Cerebras anahtarı sohbette açığa çıktı). Repo paylaşılırsa sızar.
- **Çözüm:** Tüm anahtarları `.env` / ortam değişkenine taşı, `config.py` yalnız
  `os.getenv` ile okusun (boş varsayılan). `.gitignore`'a `.env` ekle.
- **Dokunulacak:** `config.py`, yeni `.env`, `.gitignore`.

### P1.2 — Retrieval ince ayar (HR@1)
- **Neden:** HR@3 mükemmel (%98.5) ama HR@1 yalnız %83.5 — tablo bazen 2.-3. sıraya
  düşüyor. T.2 hem retrieval (HR@1 %85) hem verdict'te görece zayıf.
- **Çözüm:** Skor birleştirme (z-norm + kod-token bonusu ağırlıkları) ince ayarı;
  tablo serileştirmede T.2 gibi karmaşık lookup tablolarının temsilini güçlendir.
- **Beklenen etki:** HR@1 yükselir → `top_k` düşürülebilir → LLM'e daha az gürültü.
- **Dokunulacak:** `pipeline/retriever.py`, `pipeline/table_serializer.py`, `config.py`.

### P1.3 — Doğruluk kaldıracı (few-shot / CoT)
- **Neden:** 120B %89.1'de; prompt mühendisliğiyle daha yukarı çıkabilir.
- **Çözüm:** System prompt'a her sınıftan 1-2 few-shot örnek veya kısa CoT yönergesi
  ekle. **Ayrı ölçüm** yap (boyut etkisiyle karışmasın).
- **Beklenen etki:** Üretim modelinde birkaç puan ek doğruluk.
- **Dokunulacak:** `pipeline/auditor.py` (`_SYSTEM_PROMPT`), `benchmark_local.py`.

---

## P2 — Düşük Öncelik / İyileştirme

### P2.1 — Gürültü tablo filtresi
- RECORD OF CHANGES, Figure B-* gibi tablolar zaten kısmen reddediliyor
  (`rejected_tables.json`). Filtreyi sağlamlaştır.
- **Dokunulacak:** `scripts/table_assembler.py`.

### P2.2 — Görsel indeksleme (opsiyonel)
- Tablolar şu an yalnız metadata (aranamaz). İstenirse tablo görselleri de aranabilir
  hale getirilebilir. Şimdilik gereksiz — karar verildi.
- **Dokunulacak:** `pipeline/kb_builder.py`, `retriever.py`.

### P2.3 — Text chunk / bölüm kapsamı
- Chunk kapsamı genişletilebilir; bölüm hiyerarşisi metadata'sı zenginleştirilebilir.
- **Dokunulacak:** `scripts/text_chunker.py`.

### P2.4 — UX / operasyon
- Sonuç JSON dışa aktarma (zaten var), PDF rapor çıktısı, madde-bazlı "yeniden sorgula"
  butonu, çoklu-KB karşılaştırmalı denetim.
- **Dokunulacak:** `server.py`, `templates/index.html`.

### P2.5 — Eski kod / tutarsızlık temizliği
- Kullanılmayan **`app.py`** (eski Gradio arayüzü) kaldır.
- **`diagnose_retrieval.py`** hâlâ 4-sınıf prompt içeriyor — binary'ye güncelle ya da sil.
- **`test_scenarios_200.json`** artık 138 madde — dosya adındaki "200" yanıltıcı,
  `test_scenarios.json`'a yeniden adlandır (referansları güncelle).
- **`SYSTEM_CONTEXT.md`** güncel değil (hâlâ 4 verdict, Groq 70B, aastp_v2 anlatıyor) —
  mevcut binary + Cerebras durumuna güncelle.
- **Dokunulacak:** `app.py` (sil), `diagnose_retrieval.py`, `eval_200.py`,
  `benchmark_local.py`, `eval_retrieval.py`, `SYSTEM_CONTEXT.md`.

---

## Önerilen Sıra

1. **P0.1** (8B + 70B) — eğriyi tamamla, en görünür tez çıktısı.
2. **P0.2** (test seti) — genellenebilirlik kanıtı.
3. **P1.1** (güvenlik) — hızlı, riski büyük.
4. **P0.3 / P1.2 / P1.3** — sağlamlaştırma ve doğruluk kaldıraçları.
5. **P2.*** — cila ve temizlik.
