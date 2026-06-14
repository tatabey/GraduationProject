# Arayüz Değişiklikleri Günlüğü (ComplAI)

> Arayüz (`templates/index.html` + `server.py` HTML fragmentleri) üzerindeki tüm
> düzenlemeler buraya tarih + gerekçeyle kaydedilir. En yeni en üstte.

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
