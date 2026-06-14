# Arayüz Değişiklikleri Günlüğü (ComplAI)

> Arayüz (`templates/index.html` + `server.py` HTML fragmentleri) üzerindeki tüm
> düzenlemeler buraya tarih + gerekçeyle kaydedilir. En yeni en üstte.

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
