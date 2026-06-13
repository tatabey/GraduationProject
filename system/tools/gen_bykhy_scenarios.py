#!/usr/bin/env python3
"""
gen_bykhy_scenarios.py
======================
BYKHY (Binaların Yangından Korunması Yönetmeliği) KB'si için TÜRKÇE senaryo üretir.
Tablo senaryoları hücre değerlerinden DETERMİNİSTİK üretilir (ground-truth garantili,
eşik metinde AÇIK EDİLMEZ). Her tabloda doğru ≥/≤ yönü elle kodlandı.
Çıktı: data/test_scenarios_bykhy.json (AASTP şemasıyla aynı: item_no, text, expected, table/chunk_id)
"""
import json, re, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SU = json.load(open(ROOT / "data/kbs/bykhy_test/semantic_units/semantic_units.json"))
U = {u["table_name"]: u for u in (SU if isinstance(SU, list) else SU)}
random.seed(7)


def grid(prefix):
    key = [k for k in U if k.startswith(prefix)]
    if not key:
        raise KeyError(prefix)
    name = key[0]
    out = []
    for r in re.split(r"</tr>", U[name]["html"]):
        cells = [re.sub("<[^>]+>", " ", c).strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.DOTALL)]
        cells = [re.sub(r"\s+", " ", c) for c in cells]
        if any(cells):
            out.append(cells)
    return name, out


def _one(tok):
    """Türkçe sayı: ',' ondalık; '.' eğer tam 3 hane izliyorsa binlik, değilse ondalık.
    '45.000'→45000, '1.000'→1000, '115.001'→115001, '0.5'→0.5, '10.1'→10.1, '51,50'→51.5"""
    tok = tok.strip()
    if "," in tok:                       # virgül = ondalık, nokta = binlik
        return float(tok.replace(".", "").replace(",", "."))
    if "." in tok:
        intp, frac = tok.rsplit(".", 1)
        if len(frac) == 3 and frac.isdigit():   # .XXX → binlik ayraç
            return float(tok.replace(".", ""))
        return float(tok)                        # .X / .XX → ondalık
    return float(tok)


def nums(s):
    return [_one(x) for x in re.findall(r"\d[\d.,]*", s)]


def rng(s):
    """ '3.1- 10' / '1001–3000' / '0.5’den az' / '600.1- 1200' → (lo, hi) """
    s = s.replace("–", "-").replace("’", "'")
    if "az" in s:  # "0.5'den az"
        n = nums(s); return (0.0, n[0]) if n else (0.0, 0.0)
    n = nums(s)
    if len(n) >= 2:
        return (n[0], n[1])
    return (n[0], n[0]) if n else (0.0, 0.0)


def pick_in(lo, hi):
    if hi <= lo:
        return round(lo + 0.5, 1)
    return round((lo + hi) / 2, 1)


# ── 1) Ek-6 Koltuk (MAX): sıra genişliği → bir sıradaki en çok koltuk ──────
def gen_ek6(n):
    name, g = grid("Ek-6")
    rows = [r for r in g if re.match(r"^\d", r[0]) or "-" in r[0]]
    out = []
    for r in g:
        if len(r) < 3 or not nums(r[0]):
            continue
        w = r[0]
        for side, mx_s in [("çıkış yolu yalnız bir yanda", r[1]), ("çıkış yolu iki yanında", r[2])]:
            mx = nums(mx_s)
            if not mx:
                continue
            mx = int(mx[0])
            # UYGUN: koltuk ≤ mx
            out.append((f"Bir toplanma salonunda sıra genişliği {w} mm olan koltuk sıralarında, "
                        f"{side}, her sırada {max(1,mx-2)} koltuk bulunmaktadır.", "UYGUN"))
            # UYGUN DEĞİL: koltuk > mx
            out.append((f"Bir sinema salonunda sıra genişliği {w} mm olan sıralarda, {side}, "
                        f"her sırada {mx+3} koltuk yerleştirilmiştir.", "UYGUN DEĞİL"))
    return _balance(out, name, n)


# ── 2) Ek-10 Dökme LPG (MIN mesafe): su hacmi → asgari emniyet uzaklığı ────
def gen_ek10(n):
    name, g = grid("Ek-10")
    out = []
    for r in g:
        if len(r) < 3 or not nums(r[0]) and "az" not in r[0]:
            continue
        lo, hi = rng(r[0]); v = pick_in(lo, hi)
        for kind, col in [("yeraltı", 1), ("yerüstü", 2)]:
            if col >= len(r):
                continue
            mn = nums(r[col])
            if not mn:
                continue
            mn = mn[0]
            out.append((f"Su hacmi {v} m³ olan bir dökme LPG {kind} tankı, en yakın bina ve "
                        f"tesise {round(mn*1.5+3,1)} m emniyet uzaklığında yerleştirilmiştir.", "UYGUN"))
            if mn > 1:
                out.append((f"Su hacmi {v} m³ olan dökme LPG {kind} tankı, en yakın binaya "
                            f"yalnızca {round(mn*0.5,1)} m mesafede konumlandırılmıştır.", "UYGUN DEĞİL"))
    return _balance(out, name, n)


# ── 3) Ek-12/C Yerüstü tank (MIN mesafe): hacim(L) → komşu sınır mesafesi ──
def gen_ek12c(n):
    name, g = grid("Ek-12/C")
    out = []
    for r in g:
        if len(r) < 2 or not nums(r[0]):
            continue
        lo, hi = rng(r[0]); v = int(pick_in(lo, hi))
        mn = nums(r[1])
        if not mn:
            continue
        mn = mn[0]
        out.append((f"Açıkta kurulu, hacmi {v} litre olan yerüstü yanıcı sıvı tankı, komşu arsa "
                    f"sınırına {round(mn*1.5+3,1)} m mesafede yerleştirilmiştir.", "UYGUN"))
        out.append((f"Hacmi {v} litre olan yerüstü yanıcı sıvı tankı, komşu arsa sınırına "
                    f"yalnızca {round(max(0.3,mn*0.5),1)} m mesafede konumlandırılmıştır.", "UYGUN DEĞİL"))
    return _balance(out, name, n)


# ── 4) Ek-4 Kompartıman (MAX alan): kullanım → en fazla alan ──────────────
def gen_ek4(n):
    name, g = grid("Ek-4 Binalarda")
    out = []
    for r in g:
        cells = [c for c in r if c]
        area = None; usage = None
        for c in cells:
            if nums(c) and ("m²" not in c) and float(nums(c)[0]) >= 1000:
                area = int(nums(c)[0])
            elif not nums(c) and len(c) > 4 and "sınıf" not in c.lower():
                usage = c
        if area and usage:
            out.append((f"Bir {usage.lower()} binasında tek bir yangın kompartımanının alanı "
                        f"{int(area*0.7)} m² olarak düzenlenmiştir.", "UYGUN"))
            out.append((f"Bir {usage.lower()} binasında bir yangın kompartımanı {int(area*1.4)} m² "
                        f"büyüklüğünde tek parça olarak düzenlenmiştir.", "UYGUN DEĞİL"))
    return _balance(out, name, n)


# ── 5) Ek-5/A Kullanıcı yükü (LOOKUP değer): kullanım → m²/kişi katsayısı ──
def gen_ek5a(n):
    name, g = grid("Ek-5/A")
    out = []
    coeffs = [1.5, 1.0, 0.5, 3.0, 5.0, 10.0, 20.0, 30.0]
    for r in g:
        usage = None; coeff = None
        for c in r:
            if nums(c) and len(c) <= 6 and float(nums(c)[0]) <= 40:
                coeff = nums(c)[0]
            elif not nums(c) and len(c) > 8:
                usage = c
        if usage and coeff:
            out.append((f"Kullanıcı yükü hesabında, '{usage[:45]}' için {coeff} m²/kişi "
                        f"katsayısı esas alınmıştır.", "UYGUN"))
            wrong = random.choice([x for x in coeffs if abs(x - coeff) > 0.6] or [coeff*2])
            out.append((f"Kullanıcı yükü hesabında, '{usage[:45]}' için {wrong} m²/kişi "
                        f"katsayısı kullanılmıştır.", "UYGUN DEĞİL"))
    return _balance(out, name, n)


# ── 6) Ek-5/B Kaçış uzaklığı (MAX, matris): kullanım × yön/yağmurlama ──────
def gen_ek5b(n):
    name, g = grid("Table_page95")
    # veri satırları: [kullanım, tekyön-yok, tekyön-var, ikiyön-yok, ikiyön-var, ...]
    cols = [("tek yönlü kaçış imkânı olan", "yağmurlama sistemi bulunmayan", 1),
            ("tek yönlü kaçış imkânı olan", "yağmurlama sistemli", 2),
            ("iki yönlü kaçış imkânı olan", "yağmurlama sistemi bulunmayan", 3),
            ("iki yönlü kaçış imkânı olan", "yağmurlama sistemli", 4)]
    out = []
    for r in g:
        if not r[0] or nums(r[0]) or "Kullanım" in r[0] or "Yağmurlama" in r[0] or "kapı" in r[0].lower():
            continue
        usage = r[0]
        for yon, yag, ci in cols:
            if ci >= len(r) or not nums(r[ci]):
                continue
            mx = nums(r[ci])[0]
            out.append((f"{usage} bir yapıda, {yag} bir mekânda en uzun kaçış uzaklığı "
                        f"{int(mx*0.6)} m olarak ölçülmüştür ({yon} mekân).", "UYGUN"))
            out.append((f"{usage} bir yapıda, {yag} bir mekânda en uzun kaçış uzaklığı "
                        f"{int(mx*1.7+5)} m'dir ({yon} mekân).", "UYGUN DEĞİL"))
    return _balance(out, name, n)


# ── 7) Ek-7 Algılama (eşik): bina → üstünde algılama gereken yükseklik ─────
def gen_ek7(n):
    name, g = grid("Ek-7")
    out = []
    for r in g:
        if len(r) < 2 or not r[0] or "(*)" in r[0]:
            continue
        h = nums(r[1])
        if not h or ">" not in r[1] and "&gt;" not in r[1]:
            continue
        h = h[0]; usage = re.sub(r"^\d+\.\s*", "", r[0])
        # eşiğin ÜSTÜ + algılama yok = UYGUN DEĞİL; eşiğin ÜSTÜ + algılama var = UYGUN
        out.append((f"{usage} sınıfı, yapı yüksekliği {round(h+5,1)} m olan bir binada "
                    f"otomatik yangın algılama sistemi tesis edilmiştir.", "UYGUN"))
        out.append((f"{usage} sınıfı, yapı yüksekliği {round(h+5,1)} m olan bir binada "
                    f"otomatik yangın algılama sistemi bulunmamaktadır.", "UYGUN DEĞİL"))
    return _balance(out, name, n)


def _balance(pool, gold, n):
    u = [p for p in pool if p[1] == "UYGUN"]
    d = [p for p in pool if p[1] == "UYGUN DEĞİL"]
    random.shuffle(u); random.shuffle(d)
    half = n // 2
    chosen = u[:half] + d[:n - half]
    random.shuffle(chosen)
    return [{"text": t, "expected": e, "table": gold} for t, e in chosen[:n]]


# ── TEXT senaryoları (Türkçe gövde kuralları — elle, ground-truth doğrulanmış) ──
TEXT = [
 # MADDE 25 — yangın duvarı en az 90 dk; delik/boşluk bulunamaz (chunk_p14_idx103)
 ("chunk_p14_idx103","UYGUN","Bitişik nizam iki yapıyı birbirinden ayıran yangın duvarı, yangına 120 dakika dayanıklı olarak projelendirilmiştir."),
 ("chunk_p14_idx103","UYGUN DEĞİL","Bitişik nizam yapıları ayıran yangın duvarı yangına yalnızca 60 dakika dayanıklı olarak projelendirilmiştir."),
 ("chunk_p14_idx103","UYGUN DEĞİL","Bir yangın duvarı üzerine, gerekli koruma sağlanmadan havalandırma için açık boşluklar bırakılmıştır."),
 ("chunk_p14_idx103","UYGUN","Bitişik nizam yapıları ayıran yangın duvarı yangına 90 dakika dayanıklı olarak inşa edilmiştir."),
 # MADDE 39 — en az 2 çıkış; 50 kişi aşılan her mekânda 2; 25 kişi aşılan yüksek tehlikede 2 (chunk_p21_idx201)
 ("chunk_p21_idx201","UYGUN","70 kişinin bulunduğu bir toplantı salonunda korunmuş en az 2 çıkış tesis edilmiştir."),
 ("chunk_p21_idx201","UYGUN DEĞİL","60 kişinin bulunabildiği bir yeme-içme mekânında yalnızca tek bir çıkış bulunmaktadır."),
 ("chunk_p21_idx201","UYGUN DEĞİL","30 kişinin çalıştığı yüksek tehlikeli bir imalat mekânında tek çıkış bulunmaktadır."),
 ("chunk_p21_idx201","UYGUN","Düşük tehlikeli, en çok 20 kişinin bulunduğu küçük bir ofiste tek çıkış bulunmaktadır."),
 ("chunk_p21_idx201","UYGUN DEĞİL","Bir binada yalnızca 1 adet çıkış tesis edilmiş ve aksini gerektiren bir istisna belirtilmemiştir."),
 # MADDE 15 — toplanma amaçlı bina = 50 veya daha fazla kişi (chunk_p9_idx63)
 ("chunk_p9_idx63","UYGUN","80 kişinin bir araya gelebildiği bir düğün salonu, toplanma amaçlı bina sınıfında değerlendirilmiştir."),
 ("chunk_p9_idx63","UYGUN DEĞİL","120 kişinin bir araya geldiği bir tören salonu, toplanma amaçlı bina sayılmamış ve bu sınıfın gerekleri uygulanmamıştır."),
 ("chunk_p9_idx63","UYGUN","En çok 30 kişinin kullandığı küçük bir çay ocağı, toplanma amaçlı bina sınıfı dışında değerlendirilmiştir."),
 # MADDE 27 — bina >28.50 m zor yanıcı cephe; iki kat boşlukları arası en az 100 cm dolu yüzey (chunk_p15_idx111)
 ("chunk_p15_idx111","UYGUN","Yapı yüksekliği 35 m olan bir binanın dış cephesi zor yanıcı malzemeden yapılmıştır."),
 ("chunk_p15_idx111","UYGUN DEĞİL","Yapı yüksekliği 40 m olan bir binanın dış cephesinde kolay alevlenici malzeme kullanılmıştır."),
 ("chunk_p15_idx111","UYGUN DEĞİL","İki katın korumasız pencere boşlukları arasında düşeyde yalnızca 60 cm yüksekliğinde dolu yüzey bırakılmıştır."),
 ("chunk_p15_idx111","UYGUN","İki katın pencere boşlukları arasında düşeyde 120 cm yüksekliğinde yangına dayanıklı dolu cephe yüzeyi oluşturulmuştur."),
 # MADDE 24 — kazan dairesi/otopark/trafo gibi yüksek tehlikeli kapalı alanlar kompartıman duvarı niteliğinde ayrılır (chunk_p13_idx99)
 ("chunk_p13_idx99","UYGUN","Bir binanın kazan dairesi ve jeneratör odası, kompartıman niteliğindeki duvar ve döşemelerle ayrılmıştır."),
 ("chunk_p13_idx99","UYGUN DEĞİL","Bir binadaki ana elektrik dağıtım odası, çevresinden kompartıman niteliğinde duvar ve döşeme ile ayrılmamıştır."),
 # MADDE 73 — acil yönlendirme normal aydınlatma kesilince en az 60 dk; kullanıcı >200 ise en az 120 dk; işaret yüksekliği ≥15 cm; 200-240 cm (chunk_p37_idx374)
 ("chunk_p37_idx374","UYGUN","Acil durum yönlendirmesi, normal aydınlatmanın kesilmesi hâlinde 90 dakika süreyle çalışacak şekilde tasarlanmıştır (kullanıcı yükü 150)."),
 ("chunk_p37_idx374","UYGUN DEĞİL","Acil durum yönlendirmesinin, normal aydınlatma kesildiğinde yalnızca 30 dakika süreyle çalışması öngörülmüştür."),
 ("chunk_p37_idx374","UYGUN DEĞİL","Kullanıcı yükü 350 olan bir mekânda acil durum yönlendirmesi 60 dakika süreyle çalışacak şekilde tasarlanmıştır."),
 ("chunk_p37_idx374","UYGUN","Kullanıcı yükü 400 olan bir terminalde acil durum yönlendirmesi 120 dakika süreyle çalışacak şekilde tasarlanmıştır."),
 ("chunk_p37_idx374","UYGUN DEĞİL","Yönlendirme işaretlerinin işaret yüksekliği 8 cm olarak belirlenmiştir."),
 ("chunk_p37_idx374","UYGUN","Yönlendirme işaretleri yerden 220 cm yüksekliğe yerleştirilmiştir."),
 # MADDE 75 — yangın uyarı butonları yatay erişim ≤60 m; yerden 110-130 cm; konutlar hariç 400 m²'den fazla 2-4 katlı binada mecburi (chunk_p38_idx382)
 ("chunk_p38_idx382","UYGUN","Yangın uyarı butonları, kaçış yollarında herhangi bir noktadan yatay erişim uzaklığı 50 m olacak şekilde yerleştirilmiştir."),
 ("chunk_p38_idx382","UYGUN DEĞİL","Yangın uyarı butonları, kaçış yolu üzerinde yatay erişim uzaklığı 80 m olacak şekilde seyrek yerleştirilmiştir."),
 ("chunk_p38_idx382","UYGUN","Yangın uyarı butonları yerden 120 cm yüksekliğe monte edilmiştir."),
 ("chunk_p38_idx382","UYGUN DEĞİL","Yangın uyarı butonları yerden 160 cm yüksekliğe monte edilmiştir."),
 ("chunk_p38_idx382","UYGUN DEĞİL","Konut dışı, kat alanı 600 m² olan üç katlı bir binada yangın uyarı butonu tesis edilmemiştir."),
 # MADDE 72 — acil aydınlatma (chunk_p36_idx359) — kaçış yolu aydınlatması en az 60 dk, ≥1 lux
 ("chunk_p36_idx359","UYGUN","Kaçış yollarındaki acil durum aydınlatması, dış elektrik beslemesinin kesilmesi hâlinde en az 60 dakika çalışacak şekilde tasarlanmıştır."),
 ("chunk_p36_idx359","UYGUN DEĞİL","Kaçış yollarındaki acil durum aydınlatmasının, besleme kesildiğinde yalnızca 20 dakika çalışması öngörülmüştür."),
]


if __name__ == "__main__":
    from collections import Counter
    # Ek-4 (iç içe kompartıman yapısı) güvenilir hücre-eşlemesi zor → çıkarıldı.
    groups = [
        ("Ek-5/B kaçış", gen_ek5b(22)),
        ("Ek-5/A yük", gen_ek5a(16)),
        ("Ek-6 koltuk", gen_ek6(14)),
        ("Ek-10 LPG", gen_ek10(16)),
        ("Ek-12/C tank", gen_ek12c(14)),
        ("Ek-7 algılama", gen_ek7(10)),
    ]
    tbl = []
    for nm, gg in groups:
        print(f"  {nm:18s}: {len(gg):2d}  {dict(Counter(s['expected'] for s in gg))}")
        tbl += gg
    print("TABLO TOPLAM:", len(tbl), dict(Counter(s["expected"] for s in tbl)))

    # Text: chunk_id doğrula + section türet
    ch = json.load(open(ROOT / "data/kbs/bykhy_test/text_chunks/text_chunks.json"))
    chunks = {c["chunk_id"]: c for c in (ch if isinstance(ch, list) else ch.get("chunks", ch))}
    txt = []
    for cid, exp, text in TEXT:
        assert cid in chunks, f"BİLİNMEYEN chunk_id: {cid}"
        sp = chunks[cid].get("section_path") or []
        section = (sp[-1] if sp else "gövde")[:40]
        txt.append({"section": section, "chunk_id": cid, "expected": exp, "text": text})
    print("TEXT TOPLAM:", len(txt), dict(Counter(s["expected"] for s in txt)))

    allscn = tbl + txt
    for i, s in enumerate(allscn, 1):
        allscn[i - 1] = {"item_no": i, **s}
    out_path = ROOT / "data/test_scenarios_bykhy.json"
    json.dump(allscn, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"\n✅ GENEL: {len(allscn)} senaryo ({len(tbl)} tablo + {len(txt)} text), "
          f"denge {dict(Counter(s['expected'] for s in allscn))}")
    print(f"→ {out_path}")
