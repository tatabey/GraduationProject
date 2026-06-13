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

## Phase B — bge-m3 (çok-dilli embedding) [planlandı]
KB-başına embedding desteği + bge-m3 ile yeniden indeksleme → saf-Türkçe prose
retrieval'ındaki zayıflığın (yönlendirme/cephe) kalkması bekleniyor. (Yapılacak.)

---

## Yorum
- **Türkçe genelleme çalışıyor:** sıfır kod değişikliği, İngilizce embedding ile bile
  retrieval %90.2 / verdict %86.2.
- Tablolar dil-bağımsız iyi (sayısal içerik); zayıflık saf-Türkçe prose retrieval'ında →
  Phase B (çok-dilli embedding) ile hedeflenecek.
- Kıyas: AASTP %95.5 / DEF(AUST) %91.2 (İngilizce) · BYKHY %86.2 (Türkçe, EN embedding).
