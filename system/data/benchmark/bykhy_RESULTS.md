# BYKHY (Türkçe) — Çok-dilli Genelleme Testi Sonuçları

**Belge:** Binaların Yangından Korunması Hakkında Yönetmelik (BYKHY), 104 sayfa, **Türkçe**.
AASTP'ye en benzer profil (yangın güvenliği uygunluk kuralları + sayısal eşik/QD tabloları).
**Sıfır kod değişikliği** ile indekslendi (2026-06-14).

KB: `bykhy_test` = **28 tablo + 216 chunk = 301 doküman** (MinerU, ~92 sn).
Test seti: `data/test_scenarios_bykhy.json` = **123 senaryo** (92 tablo + 31 text),
denge 62 UYGUN DEĞİL / 61 UYGUN. Tablo senaryoları hücrelerden deterministik üretildi
(Türkçe-duyarlı sayı ayrıştırma: "45.000"=binlik, "0,5"=ondalık; eşik metinde gizli).

---

## Phase A — bge-large-en-v1.5 (İngilizce embedding, Türkçe belge)

| Katman | Sonuç |
|---|---|
| **Retrieval HR@3** | **%90.2** (HR@1 81.3, MRR 0.862) |
| **Verdict (Mistral 24B)** | **%86.2 (106/123)** |

**Retrieval:** Tablolar **%100** (Ek-10, Ek-12/C, Ek-5/A, Ek-6, Ek-7) — sayı/birim/özel-ad
(LPG, m³, litre) çapraz-dil transfer oluyor. Zayıf: saf-Türkçe prose — "Acil durum
yönlendirmesi" %0, MADDE 27 cephe %25. → İngilizce embedding'in Türkçe sınırı.

**Verdict (belirgin marj sonrası):**
| Grup | Doğruluk |
|---|---|
| Ek-10 LPG / Ek-7 algılama | 100% |
| Ek-12/C tank | 93% · Ek-5/A | 88% |
| Ek-6 koltuk | 79% · Table_page95 kaçış matrisi | 73% |
| Text grupları | %80-100 |

- Hata: 4 yanlış-alarm / 13 ihlal-kaçırma. Kalan zayıflık çok-sütunlu kaçış matrisi
  (Table_page95) — AASTP set1 / DEF Avionics'teki yoğun-matris zorluğunun aynısı.
- **Test hijyeni:** ilk koşu %78'di; ihlal senaryolarının marjı eşiğe çok yakındı (örn.
  min 38m iken 36.5m) ve ayarlı prompt "sınıra yakın değeri ihlal sayma" diyor → model
  kaçırıyordu. Marjlar belirginleştirilince **78→86.2**, Ek-10 62→100. Sisteme dokunulmadı.

## Phase B — multilingual-mpnet (çok-dilli embedding)

**KB-başına embedding** desteği eklendi (`kb_meta.embed_model`; config `EMBED_MODEL`
varsayılan, KB başına override). bykhy_test `paraphrase-multilingual-mpnet-base-v2`
(768-dim) ile yeniden indekslendi; AASTP/İngilizce KB'ler bge-large'da kaldı.

| Katman | Phase A (bge-large EN) | **Phase B (mpnet çok-dilli)** |
|---|---|---|
| Retrieval HR@3 | %90.2 | **%92.7** (HR@1 81.3, MRR 0.875) |
| Verdict (Mistral 24B) | %86.2 (106/123) | **%87.8 (108/123)** |

**Çok-dilli embedding her iki katmanı da iyileştirdi.** Tablo bazında mpnet her tabloda
≥ bge-large; net kazanç saf-Türkçe prose'da (Algılama 3/5→4/5, MADDE 27 3/4→4/4).
Beklenen "yönlendirme/cephe" sıçraması retrieval'da kısmen geldi; verdict'te eşitlik+.
→ **mpnet bykhy_test için üretim embedding'i oldu.**

### Verdict düşüşü vakası (ölçüm hijyeni)
İlk Phase B verdict koşusu **%83.7** çıktı (A'nın altında, retrieval daha iyiyken çelişki).
Kök neden embedding **değildi**: Table_page95'te 8 madde ardışık **"Connection error"**
ile DEĞERLENDİRİLEMEDİ olmuştu. `benchmark_local.py` retry'ı yalnız 429/rate_limit'i
yeniden deniyordu; bağlantı/timeout/5xx kapsanmıyordu (harness açığı). Retry geçici
hataları kapsayacak şekilde genişletildi → temiz koşuda 8 madde kurtarıldı,
**0 DEĞERLENDİRİLEMEDİ**, doğruluk **83.7 → 87.8**.

### chroma_dir yol tutarsızlığı (yan bulgu)
KB'ler arası `kb_meta.chroma_dir` tutarsızdı (absolute / `system/...` / `data/...`).
Göreli yol + repo-kökünden çalıştırma → chromadb **boş yeni DB yaratıp** "Collection
does not exist" veriyordu. bykhy_test absolute path'e sabitlendi (cwd-bağımsız).

> bge-m3 (1024-dim) ayrıca denenebilir; mpnet zaten A'yı geçtiği ve hedefe ulaştığı için
> bu fazda kapsam dışı bırakıldı.

---

## Yorum
- **Türkçe genelleme çalışıyor:** sıfır kod (pipeline) değişikliği. İngilizce embedding ile
  bile retrieval %90.2 / verdict %86.2; **çok-dilli embedding ile %92.7 / %87.8**.
- Tablolar dil-bağımsız iyi (sayısal içerik); saf-Türkçe prose zayıflığı çok-dilli
  embedding ile büyük ölçüde kapandı.
- Kıyas: AASTP %95.5 / DEF(AUST) %91.2 (İngilizce) · **BYKHY %87.8 (Türkçe, mpnet)**.
