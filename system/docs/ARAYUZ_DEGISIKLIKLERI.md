# Arayüz Değişiklikleri Günlüğü (ComplAI)

> Arayüz (`templates/index.html` + `server.py` HTML fragmentleri) üzerindeki tüm
> düzenlemeler buraya tarih + gerekçeyle kaydedilir. En yeni en üstte.

---

## 2026-06-14 (13) — Ölü kod temizliği (tablo kanıt/önizleme)

(11)'de kanıt sunumu kaldırıldıktan sonra geriye kalan kullanılmayan tablo-önizleme
altyapısı söküldü:
- **`server.py`:** `_table_btn` üreticisi + `/table-img/{kb}/{file}` endpoint'i (`table_image`)
  kaldırıldı; artık kullanılmayan `base64` ve `FileResponse` import'ları çıkarıldı.
- **`templates/index.html`:** `#table-modal` dialog'u + `openTableModal()` JS fonksiyonu +
  modal click handler'ı kaldırıldı. (Geriye log-modal ve KB-silme modalı kaldı.)

Davranış değişmedi; yalnız ölü kod azaldı. Render + tag-denge doğrulandı.

---

## 2026-06-14 (12) — İşlem günlüğü son-kullanıcıya göre sadeleştirildi

Kullanıcı: "loglar daha profesyonel ve son kullanıcıya göre olsun; teknik şeylere
veya tablo isimlerine girilmesin." Hem KB kurulumu hem denetim günlüğü baştan yazıldı.

- **Teknik terimler ve tablo ismi dökümü kaldırıldı:** `[24/31] TABLE 3A - Q-D TABLE
  FOR HAZARD DIVISION 1.3` gibi satırlar, ayrıca `MinerU / chunk / embedding / vektör
  veritabanı / koleksiyon / döküman / parça / retrieval / LLM / Model: ...(provider)`
  jargonu ve ham süre kırılımları temizlendi.
- **Belge okuma fazı (mineru_batch):** başta `PDF'iniz 207 sayfa — 5 bölüm halinde
  okunacak...`; her bölüm **numaralı** (`Bölüm 1 sunucuya yükleniyor...` → `Bölüm 1
  okunuyor...` → `✅ Bölüm 1 tamamlandı.`) → eşzamanlı bölümler ayırt edilir, tek bölüm
  içinde tekrar yok. **Parantez içi süreler ("(6s geçti)") kaldırıldı**; periyodik
  liveness logu söküldü (canlılığı ilerleme çubuğu `Belge okunuyor (3/5)` gösteriyor).
  Kaldırılmış "Gelişmiş Seçenekler" menüsüne atıf yapan hata mesajı da düzeltildi.
- **KB kurulum fazı (kb_builder):** "Tablolar ve çizelgeler taranıyor", "Belge metni
  hazırlanıyor", "🌐 Belge dili: İngilizce", "Arama dizini hazırlanıyor", "✅ Bilgi
  tabanı hazır: 31 tablo, 248 metin bölümü". Süre satırı jargonsuz toplam saniye.
- **Denetim fazı (auditor):** `Model: ...` satırı yerine `10 madde denetlenecek.`;
  `retrieval hatası` → `ilgili içerik getirilemedi`; süre satırı sade `⏱ 2.3 saniye`.

**Dokunulan dosyalar:** `scripts/mineru_batch.py`, `pipeline/kb_builder.py`,
`pipeline/auditor.py`. (TIMING_LOGS açık; benchmark araçları etkilenmedi.)

---

## 2026-06-14 (11) — Denetim sekmesi yeniden düzenlendi (sol log / sağ özet, kanıt kaldırıldı)

- **Sol panel sadeleştirildi:** "Denetimi Başlat" altındaki özet kart kaldırıldı; orada
  artık yalnız **İşlem Günlüğü** (terminal) duruyor, tamamlanınca son log donmuş halde
  (%100 + süre) kalıyor. Panel scroll yok, log kendi içinde kayıyor.
- **Süre + sonuçlar sağ panelin tepesine taşındı:** zengin özet kart (emerald onay
  ikonu, "Denetim Tamamlandı · ⏱ süre", büyük rakamlı Uygun/Uygun Değil/Değerlendirilemedi
  hücreleri, üç-renkli uygunluk çubuğu, JSON İndir) sade "Genel Uygunluk" bloğunun yerine
  geçti (`render_results` artık yalnız madde kartı üretiyor; özet `_audit_summary_card`).
- **Kanıt sunumu tamamen kaldırıldı:** `render_verdict_card`'tan "Gerekçe & Kaynaklar"
  açılır bölümü + TABLO/METİN kaynak çipleri silindi; her kart artık **madde metni +
  verdict rozeti + gerekçe** (her zaman açık, kompakt). (`_table_btn` / tablo-görsel
  modalı artık ölü kod — zararsız, ayrı turda sökülebilir.)
- **Sağ panel kompakt + iç scroll, sayfa scroll yok:** `overflow-hidden flex flex-col`;
  başlık sabit, `#audit-results` kalan alanı doldurup kendi içinde kayıyor. OOB swap
  outerHTML olduğu için scroll sınıfları hem template'e hem server çıktısına kondu.

**Dokunulan dosyalar:** `server.py` (`render_verdict_card`, `render_results`,
`audit_poll`, `_audit_summary_card`), `templates/index.html` (tab-audit sağ panel).

---

## 2026-06-14 (10) — Bilgi tabanı listesi: 3 görünür + iç scroll + sade tarih

- **Sayfa scroll'u kaldırıldı, scroll yalnız listede:** Bilgi Tabanı sekmesi sağ paneli
  `overflow-hidden flex flex-col min-h-0`; "İşlem Durumu" sabit, "Mevcut Bilgi Tabanları"
  kalan alanı dolduruyor, `#kb-list` `flex-1 min-h-0 max-h-[290px]` ile ~3 kart gösterip
  kendi içinde kayıyor. Sayfanın tamamı asla scroll olmuyor.
- **Kart alt-satırı sadeleştirildi:** PDF adı + ham tarih yerine tek satır
  `Oluşturulma Zamanı: 12:24 - 14/06/2026` (SAAT - GG/AA/YYYY). `_fmt_created()` helper'ı.

**Dokunulan dosyalar:** `server.py` (`render_kb_list`, `_fmt_created`),
`templates/index.html` (tab-kb sağ panel + #kb-list).

---

## 2026-06-14 (9) — KB adı doğrulama + htmx hedef-id koruması (buton bug'ı)

- **KB adı guard'ı (`_validate_kb_name`):** ChromaDB koleksiyon kuralları KB kurulumu
  başlamadan kontrol ediliyor (3-63 karakter, harf/rakam/`_`/`-`, baş/son alfanümerik,
  IPv4 değil). Geçersizse anlaşılır Türkçe uyarı; ham Chroma hatası + yarıda kalan iş yok.
  (Önceden "AA" gibi 2-karakterli adlar tüm pipeline'ı koşturup son adımda çöküyordu.)
- **KÖK BUG — htmx hedef-id kayboluyordu:** `_error_html` id'siz bir div döndürüyordu;
  `outerHTML` swap `#index-result`/`#audit-result`'ı DOM'dan siliyor, sonraki form
  gönderimi hedefi bulamayıp **sessizce çalışmıyordu** (sayfa yenilenene dek). Düzeltme:
  `_error_html(msg, target_id)` çıktıyı doğru id'li div'le sarıyor; KB hataları
  `index-result`, denetim hataları `audit-result` hedefini koruyor.

**Dokunulan dosyalar:** `server.py` (`_validate_kb_name`, `_error_html` + tüm çağrılar).

---

## 2026-06-14 (8) — Denetim özet kartı yeniden tasarım + sayaç flicker düzeltmesi

- **Özet kartı (`server.py` `_audit_summary_card`) profesyonelleştirildi:** emoji yerine
  inline **SVG ikonlar** (check / x / dosya / KB); başarı başlığı emerald onay ikonu +
  "Denetim Tamamlandı · ⏱ {süre}". Yeni **Uygunluk Oranı çubuğu** (yeşil uygun · kırmızı
  ihlal · gri değerlendirilemedi, gerçek orana göre genişlik) + %oran rozeti. İstatistik
  hücreleri büyük rakam (`text-3xl`) + sade etiket. **"JSON İndir"** butonu başlık satırına
  taşındı (indigo). Kart `rounded-2xl` beyaz zemin.
- **Sayaç flicker düzeltmesi:** `_log_box` geçen-süreyi artık ilk render'da sunucu tarafında
  güncel değerle basıyor (önce `0:00` basıp JS'in ilk tik'ine kadar titriyordu). JS tarafında
  `tickTimers()` fonksiyona alındı ve `htmx:afterSwap`'ta hemen çağrılıyor → swap sonrası
  anında güncel.

**Dokunulan dosyalar:** `server.py` (`_audit_summary_card`, `_log_box`), `templates/index.html`
(timer JS + afterSwap). server.py syntax doğrulandı.

---

## 2026-06-14 (7) — Genel Bakış paleti profesyonelleştirildi (mor azaltıldı)

Kullanıcı: "mor çok baskın". Palet tek-aksan sisteme çekildi:
- İçerik artık **indigo (birincil) + slate (nötr) + emerald (başarı)**.
- İki modül kartı: violet/indigo zıtlığı → ikisi de **nötr slate-50** kart; ikon tile'lar
  ADIM 1 indigo-600 (birincil), ADIM 2 slate-800 (ikincil). ADIM etiketleri indigo/slate.
- Sağ kart aksan çubuğu violet-500 → indigo-500. Hero ikonu gradyanı indigo→violet → indigo→indigo.
- Marka wordmark ("AI") gradyanı imza olarak korundu (sidebar ile tutarlı).

**Dokunulan:** `templates/index.html` (tab-home renkleri).

---

## 2026-06-14 (6) — KÖK BUG: `* { font-size:16px }` iç öğeleri eziyordu

**Belirti:** marka büyütülünce "yazı alanı büyüyor ama yazı büyümüyor" (büyük kutu,
küçük yazı). İsmin bunca turdur küçük görünmesinin asıl sebebi buydu.

**Kök neden:** stil bloğundaki `*, body { font-size:16px }` — evrensel `*` seçici
**her öğeye** 16px dayatıyordu. `.brand` div'i `text-[3.5rem]` ile 56px'lik satır
kutusu oluştursa da, içindeki `<span>`'ler `*` kuralıyla doğrudan 16px'e eziliyordu
(font-size normalde miras alınır; `*` bu mirası override ediyordu).

**Çözüm:** `font-size` `*` kuralından çıkarıldı, yalnız `body { font-size:16px }`'e
taşındı. Artık iç öğeler ata öğenin boyut sınıfını (text-[..], text-xl…) miras alıyor.
Diğer öğeler zaten Tailwind boyut sınıfı kullandığından etkilenmez.

---

## 2026-06-14 (5) — PDF "yüklendi" durumu + logo yan yana

Kullanıcı geri bildirimi:
- **PDF yükleme geri bildirimi profesyonelleşti:** eski küçük `📎 dosyaadı` satırı yerine,
  dropzone'un içinde **"Yüklendi" kartı** (yeşil dosya ikonu + dosya adı truncate +
  ✓ Yüklendi · boyut + **Kaldır (✕)** butonu). Dropzone kenarı yeşil-dolu (`.drop-active`).
  Hem KB (`kf`) hem Denetim (`af`) formunda. `showFile()` zenginleştirildi (prompt gizle /
  sel göster), `clearFile()` + `fmtSize()` eklendi; eski span'ler kaldırıldı.
  Kart/dropzone tıklayınca dosya değiştirilebilir; ✕ event.preventDefault ile sadece temizler.
- **Logo + isim yan yana ve aynı boyutta:** dikey düzenden **yatay**a dönüldü. İsmin
  yatay sığması için sidebar `16rem → 18rem` genişletildi. İkon `w-14` + marka `text-[2.5rem]`
  (≈40px, ikonla dengeli) yan yana, ortalı. Menü butonu logo header'ında **ayrı üst satırda**
  (`flex justify-end`) → satır genişliğini yemiyor, mini modda görünür kalıyor.

**Dokunulan dosyalar:** `templates/index.html` (logo header, iki dropzone, JS, .drop-active CSS,
sidebar genişliği). Render + tag-denge doğrulandı.

---

## 2026-06-14 (4) — Genel Bakış yeniden tasarım + logo dikey/büyük

Kullanıcı geri bildirimi:
- **Genel Bakış içeriği profesyonelce yeniden kuruldu:** slim hero + iki sütun:
  - SOL "Nasıl Kullanılır" — 2 modül kartı (Bilgi Tabanı / Denetim), her biri ikon +
    ADIM rozet + açıklama, altında ipucu satırı.
  - SAĞ "Sistem Hakkında" — tanım paragrafı + mini pipeline şeridi + 3 özellik +
    metrik rozetleri (HR@3 ~%97 / 4 standart / 2 dil).
  - `grid lg:grid-cols-2`, `flex-1 min-h-0`, kartlar `flex-col` → tek ekrana sığar, scrollsuz.
- **Logo + isim büyütüldü ve dikey ortalı yapıldı:** isim yatay düzende sidebar'a
  sığmadığından (text-4xl "ComplAI" ~138px) düzen **dikey ortalı**ya çevrildi:
  ikon `w-16` üstte ortada, marka `text-4xl` altında ortada (logoyla aynı görsel ağırlık).
  Menü (hamburger) butonu header'da **absolute top-right**'a alındı (satır genişliğini yemiyor).
  Mini (daraltılmış) modda ikon+isim gizlenir, köşedeki menü görünür kalır.

**Dokunulan dosyalar:** `templates/index.html` (logo header + tab-home).
Render + tag-denge doğrulandı.

---

## 2026-06-14 (3) — Genel Bakış modülü + form sadeleştirme + logo büyütme

Kullanıcı geri bildirimleri (4 madde):
1. **Sol form paneli boş beyazı sonlandırıldı:** panel artık `self-start max-h-full`
   (içeriğe göre yükseklik) + `border-b rounded-br-3xl shadow-sm` → beyaz, butonun
   hemen altında sağ-alt yuvarlak köşeyle bitiyor; altı sayfa zemini (slate-100).
2. **Logo + isim büyütüldü:** ikon `w-12→w-14` (svg `w-7→w-8`), marka `text-2xl→text-3xl`.
3. **"Gelişmiş Seçenekler" kaldırıldı:** `<details>` bloğu (skip_mineru + existing_json)
   tamamen silindi. Backend güvenli — `kb_index` bu alanları `Form(False)/File(None)`
   varsayılanıyla okuyor, UI'dan gelmese de normal MinerU akışı çalışır.
4. **Yeni "Genel Bakış" modülü (giriş ekranı, scrollsuz):** sidebar'a 3. modül eklendi
   ve **varsayılan aktif** yapıldı. İçerik: hero (ComplAI + tanım), "Nasıl Çalışır"
   pipeline şeridi, "Kullanım Kılavuzu" (2 adım), "Öne Çıkanlar" (4 madde).
   `tab-home` = `h-full overflow-hidden`, flex-col + max-w-5xl → tek ekrana sığar.
   JS: `TABS.home`, `switchTab(['home','kb','audit'])`, top-bar varsayılan başlık home.

**Dokunulan dosyalar:** `templates/index.html` (nav, top-bar, tab-home paneli, sol panel,
logo, JS). Standalone Jinja render + tag-denge doğrulandı.

---

## 2026-06-14 (2) — Sidebar logo sadeleştirme + KB listesi iç scroll

Kullanıcı geri bildirimi üzerine:
- **Logo/marka daha dikkat çekici:** ikon gradyan (`from-indigo-500 to-violet-600`,
  ring + gölge); marka `text-2xl font-extrabold`, "AI" gradyan metin
  (`indigo-400→violet-400`, bg-clip-text).
- **Alt başlık kaldırıldı:** "RAG Tabanlı Uygunluk Denetimi" 3 satıra kayıyordu →
  tamamen kaldırıldı, artık sade **LOGO + ComplAI** (kullanıcı tercihi).
- **Mevcut Bilgi Tabanları iç scroll:** `#kb-list` artık `max-h-[290px] overflow-y-auto`
  → ~3 KB kartı gösterip kendi içinde kayıyor; sayfanın tamamı scroll olmuyor.
  (Scroll sınıfları htmx hedefi olan `#kb-list`'in kendisinde → innerHTML swap'ta korunur.)

**Dokunulan dosyalar:** `templates/index.html` (logo bloğu + #kb-list).

---

## 2026-06-14 — Proje adı: ComplAI + profesyonel tipografi

**Proje adı belirlendi: ComplAI** (*comply + AI*; iki kelimeden kaynaşan tek kelime).
Mevzuat/standart belgelerini RAG ile denetleyip "uygun / uygun değil" kararı veren
sistemin kimliği. Alt başlık: "Mevzuat Uygunluk Denetimi / RAG Tabanlı".

İsim güncellenen yerler:
- `index.html` `<title>` → "ComplAI — Mevzuat Uygunluk Denetimi"
- `index.html` sidebar logo → `Compl` (beyaz) + `AI` (indigo-400 vurgu), display font
- `index.html` logo alt başlık → "RAG Tabanlı Uygunluk Denetimi"
- `server.py` modül docstring + `FastAPI(title="ComplAI")`

**Tipografi yenilendi (eski: tek font Inter — "sönük" geri bildirimi).**
Çift-font sistemi kuruldu (Google Fonts):
- **Space Grotesk** → marka + başlıklar (`h1/h2/h3`, `.brand`, `.font-display`);
  karakterli, modern, tech-güveni veren display font. `letter-spacing:-.015em`.
- **Plus Jakarta Sans** → gövde/UI metni; Inter'den daha sıcak ve profesyonel.
- CSS değişkenleri: `--font-body`, `--font-display` (`:root`).
- Render keskinliği: `-webkit-font-smoothing:antialiased`,
  `-moz-osx-font-smoothing:grayscale`, `text-rendering:optimizeLegibility`
  (sönüklüğün bir kısmı render yumuşaklığındandı).

**Dokunulan dosyalar:** `templates/index.html` (head/style + logo), `server.py` (title/docstring).
**Sonraki adım:** arayüz düzenlemelerine devam (kullanıcı talebi).
