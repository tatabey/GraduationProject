# Arayüz Değişiklikleri Günlüğü (ComplAI)

> Arayüz (`templates/index.html` + `server.py` HTML fragmentleri) üzerindeki tüm
> düzenlemeler buraya tarih + gerekçeyle kaydedilir. En yeni en üstte.

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
