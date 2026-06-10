# Test Raporu — AASTP-1 RAG Denetim Sistemi

> Bu belge, sistemin geliştirilmesi sırasında yapılan tüm testleri, çıkan sonuçları,
> alınan kararların gerekçelerini ve gelinen durumu kronolojik olarak belgeler.
> Tüm sayılar `system/data/benchmark/` ve `system/data/benchmark/retrieval_eval.txt`
> çıktılarından alınmıştır.

---

## 1. Proje Özeti

NATO **AASTP-1** (patlayıcı madde depolama kuralları) standardını kapsayan, **RAG
(Retrieval-Augmented Generation) tabanlı bir uygunluk denetim sistemi**.

- Kullanıcı bir **denetim raporu** (numaralı maddeler içeren PDF) yükler.
- Sistem her maddeyi, indekslenmiş **doğru standart materyale** (ChromaDB bilgi tabanı)
  karşı sorgular.
- Bir LLM, ilgili standart bağlamını okuyup her madde için karar verir: **UYGUN /
  UYGUN DEĞİL**.

İki bağımsız doğruluk ekseni vardır ve ayrı ayrı ölçülmüştür:
1. **Retrieval doğruluğu** — doğru tablo/bölüm getirilebiliyor mu? (LLM'den bağımsız)
2. **Verdict doğruluğu** — getirilen bağlamla LLM doğru kararı veriyor mu?

---

## 2. Faz A — Retrieval Problemi ve Çözümü

### Sorun
Bilgi tabanı **karışık modaliteli**: 31 tablo + 457 text chunk = 488 döküman. İki yapısal
sorun retrieval'ı bozuyordu:

1. **Tablolar metin havuzunda boğuluyordu.** 457 chunk'a karşı 31 tablo olduğundan,
   semantic arama aday havuzunu metinle dolduruyor, tablolar listeye giremiyordu.
2. **Cross-encoder modalite yanlılığı.** Kullanılan `ms-marco-MiniLM-L-6-v2` reranker
   tabloları sistematik olarak metinden ~10 puan daha düşük skorluyordu (tablo skorları
   ~−9, metin ~−0.7). Yani doğru tablo bulunsa bile rerank sonrası eleniyordu.

### Çözüm (domain-agnostik)
Hiçbir AASTP-1'e özel sabit kullanmadan, herhangi bir PDF standardı için çalışacak
şekilde tasarlandı:

| Teknik | Ne yapar |
|---|---|
| **Çift-sorgu** | Genel semantic sorguya ek olarak, tüm tablo adaylarını ayrı bir sorguyla havuza zorlar (tablolar boğulmaz). |
| **Modalite-içi z-normalizasyon** | Cross-encoder skorlarını `type` grubuna göre (tablo / metin) ayrı ayrı z-normalize eder → ms-marco'nun mutlak modalite farkını sıfırlar. |
| **Jenerik kod-token bonusu** | Sorgu↔doküman arasında kod benzeri token (HD 1.1, Group K, Q-D, Table 4 vb.) örtüşmesine küçük normalize bonus ekler. HD'ye özel `_HD_RE` kaldırıldı, yerine jenerik `_CODE_RE` geldi. |
| **Yumuşak tablo tabanı** | En iyi tablo adayı medyan üstü skordaysa 1 slot rezerve eder (zorlamaz → eski TABLE_QUOTA regresyonunu önler). |

Ayrıca `table_serializer.py`'den domain'e özel `_PAGE_CANONICAL` sabiti kaldırıldı.

### Sonuç (200 sorgu, 5 kritik tablo)

| Metrik | Değer | Hedef |
|---|---|---|
| HR@1 | %83.5 | — |
| **HR@3** | **%98.5** | ≥ %90 ✅ |
| HR@5 | %99.5 | — |
| MRR | 0.908 | — |

**Tablo bazında HR@3:**

| Tablo | HR@1 | HR@3 | HR@5 | MRR |
|---|---|---|---|---|
| Table 4 | %75.0 | %95.0 | %97.5 | 0.848 |
| Table 5 | %95.0 | %100 | %100 | 0.975 |
| Table 6 | %82.5 | %100 | %100 | 0.904 |
| Table T.2 | %85.0 | %100 | %100 | 0.925 |
| Table 133 | %80.0 | %97.5 | %100 | 0.890 |

### Önemli kapsam sınırı
Bu ölçüm yalnız **5 kritik tablo** (Table 4/5/6/T.2/133) içindir — bunlar AASTP-1'in en
önemli uygunluk tablolarıydı. KB'de **31 tablo** var; diğer 26 tablo test edilmedi.
HR@1'in %83.5'te kalması, tablonun bazen 1. değil 2.-3. sıraya düşmesinden kaynaklanır
(bu yüzden `top_k=3` kullanılır).

---

## 3. Faz B — Verdict Doğruluğu Teşhisi ve Taksonomi Kararları

Retrieval çözülünce darboğaz **verdict üretimine** kaydı. Başlangıçta 4 sınıf vardı:
UYGUN / UYGUN DEĞİL / BELİRSİZ / BİLGİ. Küçük (3B) modellerle doğruluk %34–49'da takılıydı.

### Teşhis (confusion matrix)
- **BİLGİ kategorisi öğrenilemez:** 3 farklı 3B modelde de 15 BİLGİ senaryosunda **0**
  doğru. Etiketi yalnız ifade biçimiyle ayrışıyordu ("belgeler diyor ki" = BİLGİ vs
  "tesis uyguluyor" = UYGUN) — model için anlamsız bir meta-ayrım.
- **BELİRSİZ çok zayıf:** recall ~%13. Model "bilmiyorum" diyemiyor, her şeyi
  UYGUN/UYGUN DEĞİL'e çöküyordu.

### Karar 1 — BİLGİ kaldırıldı (4 → 3 sınıf)
15 BİLGİ senaryosu BELİRSİZ'e yeniden etiketlendi. Yeni dağılım: 75 UYGUN / 63 DEĞİL /
62 BELİRSİZ = 200.

### Karar 2 — BELİRSİZ kaldırıldı (3 → 2 sınıf, binary)
Sistemin asıl amacı ikili: "kurala uyuyor mu, uymuyor mu". BELİRSİZ hem öğrenilemiyor
hem ürün mantığına aykırıydı. 62 BELİRSİZ senaryo test setinden tamamen çıkarıldı.

**Test seti evrimi:** 200 → **138** (75 UYGUN + 63 UYGUN DEĞİL).

### `DEĞERLENDİRİLEMEDİ` durumu
Binary'ye geçerken, gerçek teknik aksaklıklar (retrieval boş, API hatası, parse hatası)
için ayrı bir durum tanımlandı. Bu **bir verdict değildir** — `VERDICTS` listesinde yok,
doğruluk metriğine girmez. Böylece binary taksonomi temiz kalır, sistem kullanıcıya
"karar veremedim" diyebilir.

### Kanıt — binary basitleştirmenin etkisi
**qwen2.5:3b** aynı modelle:

| Kurulum | Doğruluk |
|---|---|
| 3 sınıf (BELİRSİZ dahil) | %46.0 |
| 2 sınıf (binary) | **%65.9** |

**+20 puan.** Öğrenilemeyen BELİRSİZ sınıfı modeli yanıltmayı bıraktı; özellikle
UYGUN DEĞİL recall %54 → %70'e çıktı.

---

## 4. Faz C — Model-Boyutu Merdiveni (Ana Sonuç)

Aynı binary kurulumla (138 senaryo, aynı prompt, aynı bağlam, temperature=0) farklı
parametre boyutlarında modeller ölçüldü.

### Sonuç Tablosu

| Model | Params | Sağlayıcı | **Doğruluk** | UYGUN recall | DEĞİL recall |
|---|---|---|---|---|---|
| qwen2.5:3b | 3B | ollama | **%65.9** | %62.7 | %69.8 |
| llama-4-scout | 17B | groq | **%80.4** | %64.0 | %100 |
| gpt-oss-120b | 120B | cerebras | **%89.1** | %81.3 | %98.4 |

**Monoton ölçeklenme: 3B → 17B → 120B arttıkça doğruluk +14.5 → +8.7 puan.**
Hipotez doğrulandı: verdict darboğazı **model kapasitesiydi**, retrieval değil.

### Tablo Bazında Doğruluk (%)

| Tablo | 3B | 17B | 120B |
|---|---|---|---|
| Table 4 | 53.6 | 82.1 | 85.7 |
| Table 5 | 63.0 | 74.1 | 85.2 |
| Table 6 | 70.4 | 77.8 | 88.9 |
| Table T.2 | 75.0 | 71.4 | 85.7 |
| Table 133 | 67.9 | 96.4 | 100 |

### Kalibrasyon Yorumu
- **3B:** dengeli ama zayıf (66 UYGUN / 72 DEĞİL tahmin). Her iki sınıfta da orta.
- **17B:** ihlal-yakalama mükemmel (**%100 DEĞİL recall**) ama **aşırı temkinli** —
  90 kez "ihlal" diyor (gerçek 63), UYGUN'ları da ihlal sanıyor (%64). Denetim için
  güvenli yön ama kalibrasyonsuz.
- **120B:** hem yüksek hem **dengeli** (62 UYGUN / 76 DEĞİL ≈ gerçek 75/63). İki sınıfta
  da güçlü; en zayıf tablo bile (eski sorun T.2) %85.7.

### Metodoloji (tekrarlanabilirlik)
- Aynı binary system prompt (tüm modeller).
- Bağlam üst sınırı 6000 karakter (tüm cloud sağlayıcılarda eşit).
- temperature = 0.0.
- SHA256 + **prompt-hash'li cache**: prompt değişince eski sonuçlar otomatik geçersiz;
  aynı koşu tekrarı 0 token ve birebir aynı sonuç.

---

## 5. Faz D — Altyapı ve Rate-Limit Bulguları

Modelleri ölçerken sağlayıcı limitleri kritik bir kısıt çıktı. **Bağlayıcı kısıt = TPM
(dakikalık token)**, çünkü her denetim çağrısı ~1900 token.

### Groq per-model limitleri

| Model | TPM | Toplu koşuda durum |
|---|---|---|
| llama-3.1-8b | 6.000 | ⛔ ~3 çağrı/dk → boğuldu, DEĞERLENDİRİLEMEDİ |
| llama-4-scout-17b | 30.000 | ✅ temiz, hızlı |
| llama-3.3-70b | 12.000 | orta |
| gpt-oss-120b | 8.000 | dar |

**Bulgu:** Groq free tier'da ~8B İngilizce chat modeli yok ki limiti rahat olsun; 8B
sınıfı 6.000 TPM'e sıkışmış. Scout-17B'nin sorunsuz koşması 30.000 TPM sayesinde.

### Cerebras
8B alternatifi ararken denendi. Bu hesapta yalnız `gpt-oss-120b` ve `zai-glm-4.7` erişilebilir
(Llama-8B **yok** → 404). Limitleri:

| Pencere | İstek | Token |
|---|---|---|
| Dakika | **5** | 30.000 |
| Saat | 150 | 1.000.000 |
| Gün | 2.400 | 1.000.000 |

Yani Cerebras'ta **token bol, istek darlığı var (5 RPM)**. Toplu benchmark'ta cache
tekrar koşuları kurtarıyor; tek tek/interaktif kullanımda 5 RPM yeterli.

### Bulunan ve Düzeltilen Hata (önemli)
İlk 120B koşusunda 13 madde DEĞERLENDİRİLEMEDİ çıktı. Sebep rate-limit **değildi**:
reasoning modeli (gpt-oss) zor maddelerde 512 token'ı **düşünmeye** harcayıp
`content=None` döndürüyor, kod da `_parse_verdict(None)` ile `.strip()`'te çöküyordu.

**Düzeltme:**
1. `content or ""` ile None koruması (boş içerik → DEĞERLENDİRİLEMEDİ, çökme yok).
2. `LLM_MAX_TOKENS` 512 → **2000** (reasoning + VERDICT için alan).

Etki: 120B tekrar koşuda **138/138 temiz**, en zor tablo **T.2 %53.6 → %85.7** sıçradı
(o 13 hata T.2'de yığılmıştı).

---

## 6. Faz E — Üretim Entegrasyonu

### auditor.py sağlayıcı-bağımsız yapıldı
Önceden `from groq import Groq` ile Groq Llama-3.3-70B'ye **kilitliydi** — ve bu model
binary'de hiç ölçülmemişti (rapor ile demo uyuşmazlığı). Yeni hali:

- `make_client(provider)` ile OpenAI-uyumlu istemci: **cerebras / groq / ollama**.
- Varsayılan: **Cerebras gpt-oss-120B** (ölçülen en iyi, %89.1). `config.py`'de
  `AUDIT_PROVIDER` + `AUDIT_MODEL` tek satırla değiştirilebilir.
- **429 exponential backoff** (5 → 10 → 20s): Cerebras 5 RPM'e dayanıklılık.
- None-content koruması üretim yoluna da taşındı.

### Arayüz binary'ye temizlendi
- `server.py` ve `templates/index.html`'den BELİRSİZ + BİLGİ kaldırıldı (4 → 2 kart).
- Özet ızgarası `grid-cols-4 → grid-cols-3` (2 verdict + teknik durum).
- Uygunluk yüzdesi yalnız değerlendirilen maddeler üzerinden (teknik hata yüzdeyi bozmaz).
- Sol panel scroll'suz tam ekrana sığacak şekilde düzenlendi.

### Çelişki çözüldü
Artık **rapordaki %89.1 = demodaki model.** Uçtan-uca duman testi doğrulandı:
gpt-oss-120B gerçek tablo/bölüm numaralarını alıntılayarak grounded karar üretiyor.

---

## 7. Gelinen Durum

| Eksen | Durum | Değer |
|---|---|---|
| Retrieval | ✅ Çözüldü | HR@3 %98.5 (5 tablo) |
| Verdict taksonomisi | ✅ Binary | UYGUN / UYGUN DEĞİL |
| En iyi model | ✅ Ölçüldü + bağlandı | gpt-oss-120B %89.1 |
| Üretim yolu | ✅ Sağlayıcı-bağımsız + backoff | Cerebras varsayılan |
| Arayüz | ✅ Binary'ye temizlendi | — |

**Açık konular ve sıradaki adımlar** için bkz. `GELISTIRME_PLANI.md`.

---

## 8. Text Retrieval İyileştirme Fazları (2026-06-11)

Hedef: text HR@3 %54.5 → ≥%75, tablolar ≥ baseline (sert guardrail).
Tüm fazlar config bayraklı, her faz `tools/eval_all.py --baseline` kapısından geçer.
Snapshot'lar: `data/benchmark/eval_all_<faz>.json`.

| Faz | Değişiklik | set1/2/3 HR@3 | text HR@3 (chunk/page) | Kabul |
|---|---|---|---|---|
| 0 (baseline) | — | 98.7 / 98.7 / 92.0 | 54.5 / 54.5 | — |
| 1+2 | section_path embed + boilerplate satır filtresi + sahte-başlık bastırma (457→248 chunk) + uzun chunk'a multi-vector pencereleme | 98.7 / 98.7 / 92.0 | 56.0 / 56.5 | ✅ |

Faz 1+2 notları:
- "NATO/PFP UNCLASSIFIED" 212 kez sahte heading olarak bölüm parçalıyordu;
  bastırılınca bölümler sayfa aşımlarında birleşti (104 çöp-başlıklı chunk yok oldu).
- chunk_id'ler blok indeksine bağlı olduğundan değişmedi; birleşme nedeniyle
  5 gold etiket (60 senaryo) içerik-doğrulamalı remap edildi
  (`tools/remap_gold_ids.py`, yedek: `test_scenarios_text.json.bak_pre_remap`).
- Uzun chunk'lar `CHUNK_EMBED_MAX_CHARS=2000` pencereleriyle çoklu vektör
  olarak indekslenir (aynı chunk_id metadata'sı; retriever dedupe tekilleştirir).
- Grup kırılımı karışık: NEQ +16, Inter_Magazine +12, Underground +8;
  Compatibility −12, IBD −8. Asıl kaldıraç Faz 3 (havuz) + Faz 4 (BM25).
