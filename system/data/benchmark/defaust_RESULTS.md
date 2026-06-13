# DEF(AUST) 9022 — Genelleme Testi Sonuçları

**Belge:** DEF(AUST) 9022 — *Requirements for Civilian Personnel Maintaining State
Aircraft and Aeronautical Product* (Avustralya Savunma havacılık **bakım personeli
yeterlilik** standardı, 46 sayfa). AASTP-1'den tamamen farklı domain.
**Sıfır kod değişikliği** ile indekslendi ve test edildi (2026-06-13).

KB: `defaust_test` = **8 tablo + 55 chunk = 85 doküman** (MinerU, ~20 sn).
Test seti: `data/test_scenarios_defaust.json` = **160 senaryo** (120 tablo + 40 text),
denge **80 UYGUN / 80 UYGUN DEĞİL**. Matris senaryoları hücrelerden deterministik
üretildi (ground-truth garantili, cevap metinde gizli); küçük tablo/text elle.

---

## 1. RETRIEVAL — HR@3 **%97.5** ✅ (bge embed + bge-reranker, modelden bağımsız)

| Metrik | Değer |
|---|---|
| HR@1 | 83.8% |
| **HR@3** | **97.5%** |
| HR@5 | 98.1% |
| MRR | 0.907 |

- 5 tablo + çoğu text grubu **%100 HR@3**.
- Zayıf: **5. MAINTENANCE %40** (n=5), 10. Mandatory Training %80 (n=5) — genel
  "yetkisiz çalışamaz" kuralı §7/§9/§10 ile **semantik örtüşüyor** (gerçek bulgu).
- Avionics matrisi HR@1 45.7 / HR@3 100 — iki MEA matrisi adı benzer (ilk sırada
  karışıyor, top-3'te düzeliyor).
- Rapor: `defaust_retrieval_eval.txt`.

## 2. VERDICT — Mistral Small 24B (ayarlı prompt): **%91.2 (146/160)**

| Grup | Doğruluk |
|---|---|
| Köprü (p36) / Trade eşleme (p34) | 100% |
| Trade eşleme (p26) | 94% |
| Tüm text kuralları (NDT, Surface, Electroplater, Maintenance, Training, Scope, Out-of-trade, ALS…) | ~100% |
| MEA97 **Mekanik** matrisi | 89% (31/35) |
| MEA97 **Avionics** matrisi | 80% (28/35) |

- Hata dengesi: **14 yanlış-alarm (UYGUN→DEĞİL) / 0 ihlal-kaçırma** → denetim için en güvenli
  yön (hiçbir ihlal kaçmıyor); kalan hatalar matris Qualified↔Partially uç-durumlarında.

### Önemli düzeltme (test hijyeni — sisteme dokunulmadı)
İlk koşu **%80.6** çıkmıştı; matris %51/%71 görünüyordu. Analiz: düşüklüğün ~%80'i
üreteçteki **hatalı "refused authorisation" şablonundandı** (Qualified hücreden UYGUN DEĞİL
ürettim; ground-truth tartışmalıydı — standart asgari gereksinim koyar, fazladan ihtiyat
ihlal değil; model hücreyi DOĞRU okuyup makul şekilde UYGUN diyordu). 18 madde/16 yanlış.
Şablon kaldırılıp UYGUN DEĞİL yalnız Partially/boş hücrelerden üretilince:
**genel 80.6→91.2, Avionics 51→80, Mekanik 71→89.** Serializer'a/sisteme **hiç dokunulmadı**.

- Bulgu: yoğun MEA97 matrisleri için **serileştirme iyileştirmesi gerekmedi** — retrieval %100,
  gerçek hücre okuması %80-89. Sorun test maddelerindeydi.
- Dosyalar: `defaust_mistral_mistral-small-latest_eval.json` (+ `_results.json`, `_comparison.txt`).

---

## 3. Yorum
- **Genelleme kanıtlandı:** apayrı domain, sıfır kod değişikliği → retrieval %97.5, verdict %91.2.
- Tüm tablo/text grupları %80-100; sistem yeni domaine sağlam oturuyor. Kalan hatalar
  matris uç-durumlarında ve hepsi güvenli yönde (ihlal kaçırma 0).
- 120B (Cerebras) ile aynı testi koşmak günlük token bütçesi açılınca yapılabilir.

**Kıyas (AASTP, Mistral ayarlı):** set1 88.0 / set2 98.0 / set3 98.7 / text 97.0 → genel 95.5.
DEF(AUST) **%91.2** — apayrı domainde AASTP'ye yakın, güçlü bir genelleme sonucu.
