#!/usr/bin/env python3
"""
gen_defaust_scenarios.py
========================
DEF(AUST) 9022 KB'si için 160 senaryo üretir (120 tablo + 40 text).
Matris tabloları (MEA97 Avionics/Mechanical) HÜCRELERDEN deterministik üretilir
→ ground-truth garantili (hücre değeri = doğru cevap), cevap metinde AÇIK EDİLMEZ.
Küçük tablolar ve text elle hazırlanmış satırlardan üretilir.

Çıktı: data/test_scenarios_defaust.json  (AASTP şemasıyla birebir)
"""
import json, re, random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SU = json.load(open(ROOT / "data/kbs/defaust_test/semantic_units/semantic_units.json"))
UNITS = {u["table_name"]: u for u in (SU if isinstance(SU, list) else SU.get("units", SU))}
random.seed(42)

AV_NAME = "MEA 97 version 3/4 Avionics qualification and allied single trade groups"
ME_NAME = "MEA 97 version 3/4 Mechanical and Structures qualifications and allied single trade groups"


def grid(name):
    html = UNITS[name]["html"]
    out = []
    for r in re.split(r"</tr>", html):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.DOTALL)
        cells = [re.sub("<[^>]+>", " ", c).strip() for c in cells]
        if any(cells):
            out.append(cells)
    return out


def matrix_cells(name):
    """[(unit, trade_group, value), ...] yalnız temiz hücreler (Qualified/Partially/boş)."""
    g = grid(name)
    hdr = g[0]
    cols = hdr[1:]
    cells = []
    for row in g[1:]:
        unit = row[0].strip()
        if not re.match(r"^\d", unit):     # yalnız sayısal yetkinlik ünitesi satırları
            continue
        for j, col in enumerate(cols):
            v = row[j + 1].strip() if j + 1 < len(row) else ""
            if v.startswith("Note"):       # koşullu → atla
                continue
            cells.append((unit, col, v))
    return cells


# Durum/iddia şablonları — cevabı (Qualified/Partially) METİNDE AÇIK ETMEZ.
# "full" iddia = bağımsız/tam yetkili; "partial" iddia = denetim altında/kısmi;
# "none" iddia = hiç nitelikli değil / köprü eğitimi gerekiyor.
T_FULL = [
    "A {tg} technician is signed off as fully qualified to independently perform MEA97 competency unit {u} maintenance tasks without supervision.",
    "An approved maintenance organisation authorises {tg} personnel to certify MEA97 competency unit {u} work as fully qualified.",
    "A civilian holding the {tg} qualification is rated as fully competent and unrestricted for MEA97 unit {u} tasks.",
]
T_PARTIAL = [
    "A {tg} technician is assessed as only partially qualified for MEA97 competency unit {u} and is restricted to supervised tasks pending bridging training.",
    "A {tg} maintainer performs MEA97 unit {u} work only under supervision, being treated as partially qualified for that unit.",
]
T_NONE = [
    "A {tg} technician is treated as qualified to perform MEA97 competency unit {u} tasks without any additional training.",
    "An organisation assigns MEA97 competency unit {u} work to {tg} personnel and certifies them as competent for it.",
]


def gen_matrix(name, gold_label, n):
    cells = matrix_cells(name)
    q  = [c for c in cells if c[2] == "Qualified"]
    pq = [c for c in cells if c[2] == "Partially Qualified"]
    nq = [c for c in cells if c[2] == ""]
    random.shuffle(q); random.shuffle(pq); random.shuffle(nq)
    out = []
    # Dengeli karışım: yarısı UYGUN, yarısı UYGUN DEĞİL
    half = n // 2
    # UYGUN: Qualified+full(iddia doğru) , Partially+partial(iddia doğru)
    uygun_pool = (
        [("full", c, "UYGUN") for c in q] +
        [("partial", c, "UYGUN") for c in pq]
    )
    # UYGUN DEĞİL: Partially+full(kısmi'yi tam saymak) , boş+none(nitelik yokken qualified saymak).
    # NOT: Qualified hücreden "refused authorisation" UYGUN DEĞİL kaldırıldı — ground-truth
    # tartışmalıydı (standart asgari gereksinim koyar; fazladan ihtiyat ihlal değil),
    # model hücreyi doğru okuyup makul şekilde UYGUN diyordu → hatalı test maddesi.
    degil_pool = (
        [("full", c, "UYGUN DEĞİL") for c in pq] +
        [("none", c, "UYGUN DEĞİL") for c in nq]
    )
    random.shuffle(uygun_pool); random.shuffle(degil_pool)
    chosen = uygun_pool[:half] + degil_pool[:n - half]
    random.shuffle(chosen)
    for claim, (u, tg, v), exp in chosen:
        if claim == "full":
            txt = random.choice(T_FULL).format(tg=tg, u=u)
        elif claim == "partial":
            txt = random.choice(T_PARTIAL).format(tg=tg, u=u)
        else:
            # "none" iddiası yalnız boş hücreler için: nitelik yokken qualified sayma
            txt = random.choice(T_NONE).format(tg=tg, u=u)
        out.append({"text": txt, "expected": exp, "table": gold_label})
    return out


# ── Eşleme tabloları (Trade Group ↔ rejim trade'leri) ──────────────────────
REGIMES = ["civilian", "RAAF", "Army", "RAN"]
NIL = {"", "nil", "various see 5.1", "various see 6.1", "various see 7.1"}


def _mapping_rows(name):
    """[(trade_group, {regime: trade}), ...] — Nil/boş atlanır."""
    g = grid(name)
    rows = []
    for r in g[1:]:
        tg = r[0].strip()
        if not tg:
            continue
        regs = {}
        for i, reg in enumerate(REGIMES):
            v = r[i + 1].strip() if i + 1 < len(r) else ""
            v = re.sub(r"\s+", " ", v).split("&#")[0].strip()
            if v and v.lower() not in NIL and "nil" not in v.lower()[:4]:
                regs[reg] = v
        if len(regs) >= 1:
            rows.append((tg, regs))
    return rows


def gen_mapping(name, gold, n):
    rows = _mapping_rows(name)
    out, seen = [], set()
    # UYGUN: aynı satırdan iki rejim (gerçek eşdeğerlik)
    uygun = []
    for tg, regs in rows:
        items = list(regs.items())
        for a in range(len(items)):
            for b in range(a + 1, len(items)):
                (ra, ta), (rb, tb) = items[a], items[b]
                uygun.append((f"A person holding the {ra} qualification '{ta}' is recognised as "
                              f"equivalent to the {rb} trade '{tb}' for {tg} trade group work.", "UYGUN"))
    # UYGUN DEĞİL: farklı trade group'lardan çapraz (yanlış eşdeğerlik)
    degil = []
    for i in range(len(rows)):
        for j in range(len(rows)):
            if i == j:
                continue
            tgA, regsA = rows[i]; tgB, regsB = rows[j]
            ra, ta = list(regsA.items())[0]
            rb, tb = list(regsB.items())[0]
            degil.append((f"A person holding the {ra} qualification '{ta}' (for the {tgA} trade group) "
                          f"is recognised as equivalent to the {rb} trade '{tb}' which belongs to the "
                          f"{tgB} trade group.", "UYGUN DEĞİL"))
    random.shuffle(uygun); random.shuffle(degil)
    half = n // 2
    for txt, exp in uygun[:half] + degil[:n - half]:
        if txt in seen:
            continue
        seen.add(txt)
        out.append({"text": txt, "expected": exp, "table": gold})
    random.shuffle(out)
    return out[:n]


# ── Köprü tablosu (p36): görev → orijinal nitelik → Aeroskills bridging ────
def gen_bridging(gold, n):
    g = grid("Table_page36")
    rows = []
    for r in g[1:]:
        task = r[0].strip()
        qual = (r[1].strip() if len(r) > 1 else "")
        brid = (r[2].strip() if len(r) > 2 else "")
        if task and qual and brid:
            rows.append((task, re.sub(r"\s+", " ", qual)[:70], task))
    out = []
    uygun, degil = [], []
    for task, qual, _ in rows:
        uygun.append((f"A maintainer performing {task} tasks holds the original qualification "
                      f"'{qual}...' and has completed the prescribed Aeroskills bridging units for that task.", "UYGUN"))
        degil.append((f"A maintainer performing {task} tasks holds '{qual}...' but is authorised "
                      f"WITHOUT completing any Aeroskills bridging units.", "UYGUN DEĞİL"))
    # çapraz yanlış nitelik
    for i in range(len(rows)):
        j = (i + 3) % len(rows)
        if rows[i][0] != rows[j][0]:
            degil.append((f"A maintainer performing {rows[i][0]} tasks is authorised solely on the basis of "
                          f"'{rows[j][1]}...', the original qualification prescribed for {rows[j][0]} tasks.",
                          "UYGUN DEĞİL"))
    random.shuffle(uygun); random.shuffle(degil)
    half = n // 2
    for txt, exp in uygun[:half] + degil[:n - half]:
        out.append({"text": txt, "expected": exp, "table": gold})
    random.shuffle(out)
    return out[:n]


# ── TEXT senaryoları (gövde kuralları — elle, ground-truth doğrulanmış) ────
# (chunk_id, expected, text)
TEXT = [
 # 5.1 Regulatory requirement (chunk_p14_idx117)
 ("chunk_p14_idx117","UYGUN","A Technical Trainee performs a maintenance task on aeronautical product while being directly supervised by a task-authorised tradesperson, who is responsible for the task and certifies the completed work."),
 ("chunk_p14_idx117","UYGUN DEĞİL","A newly hired worker with no trade qualification, part qualification or task authorisation independently performs and certifies maintenance on an aircraft component."),
 ("chunk_p14_idx117","UYGUN","A tradesperson holding the relevant trade qualification and correctly task authorised performs maintenance on State aircraft."),
 ("chunk_p14_idx117","UYGUN DEĞİL","A tradesperson holds a relevant trade qualification but has never been granted task authorisation, yet independently performs and certifies maintenance without any supervision."),
 # 10 Mandatory training (chunk_p22_idx176)
 ("chunk_p22_idx176","UYGUN DEĞİL","A technician is authorised to perform aircraft maintenance without having completed the safety, familiarisation and application training courses."),
 ("chunk_p22_idx176","UYGUN","Before authorisation, a maintainer completes the safety, familiarisation and application training courses specified in the Statement of Work."),
 ("chunk_p22_idx176","UYGUN DEĞİL","A technician performs Explosive Ordnance aircraft maintenance (other than egress system work) without having completed the Explosive Ordnance training course."),
 ("chunk_p22_idx176","UYGUN","A maintainer completes the mandatory Explosive Ordnance training course before being authorised to perform EO-related aircraft maintenance."),
 # NDT (chunk_p34_idx299)
 ("chunk_p34_idx299","UYGUN","An NDT technician qualified to AS3669 carries out non-destructive testing only to the inspection level and methods for which they are qualified, with current annual certification."),
 ("chunk_p34_idx299","UYGUN DEĞİL","A general engineering technician who is not qualified to AS3669 carries out non-destructive testing on an ADF aircraft component."),
 ("chunk_p34_idx299","UYGUN DEĞİL","An NDT technician qualified only in the eddy-current method performs radiographic NDT inspection because the team was short-staffed."),
 # Surface Finisher (chunk_p35_idx307)
 ("chunk_p35_idx307","UYGUN","An automotive spray painter who completed a DAIRMAINT-approved upgrade course performs aircraft surface finishing on ADF equipment."),
 ("chunk_p35_idx307","UYGUN DEĞİL","A qualified automotive spray painter with no additional aircraft surface finisher training is assigned to surface finish ADF aircraft."),
 ("chunk_p35_idx307","UYGUN","An ex-ADF Aircraft Surface Finisher carries out surface finishing of ADF aircraft."),
 # Electroplater (chunk_p35_idx311)
 ("chunk_p35_idx311","UYGUN","An ex-ADF Electroplater carries out electroplating of ADF aircraft components."),
 ("chunk_p35_idx311","UYGUN DEĞİL","A general workshop hand with no ADF electroplating background and without Certificate III in Engineering Production Systems (Electroplating) performs electroplating on ADF equipment."),
 ("chunk_p35_idx311","UYGUN","A tradesperson holding Certificate III in Engineering Production Systems (Electroplating) performs electroplating of ADF aircraft equipment."),
 # Scope (chunk_p11_idx98)
 ("chunk_p11_idx98","UYGUN","A civilian contractor organisation performing maintenance on Australian State aircraft within Australia is treated as subject to DEF(AUST) 9022."),
 ("chunk_p11_idx98","UYGUN DEĞİL","A civilian maintenance organisation maintaining State aircraft in Australia claims DEF(AUST) 9022 does not apply because its staff are contractors rather than Defence civilians."),
 # Task authorisation (chunk_p19_idx142)
 ("chunk_p19_idx142","UYGUN DEĞİL","A maintainer certifies that work was performed correctly although they have not been formally task authorised for that duty."),
 ("chunk_p19_idx142","UYGUN","The SMM ensures that only personnel who are proficient and formally task authorised certify completed maintenance work."),
 # Out-of-trade (chunk_p19_idx140)
 ("chunk_p19_idx140","UYGUN DEĞİL","An Avionics-stream tradesperson is assigned to independently perform Mechanical-stream maintenance without having completed any of the associated Mechanical competencies."),
 ("chunk_p19_idx140","UYGUN","A Mechanical-stream tradesperson completes the associated Avionics units of competency before being employed on Avionics-stream tasks."),
 ("chunk_p19_idx140","UYGUN DEĞİL","A Structures-stream inspector signs off Avionics-stream work, relying only on their Structures training without the underpinning Avionics competencies."),
 # Armament (chunk_p35_idx309)
 ("chunk_p35_idx309","UYGUN DEĞİL","A pre-1991 single-trade Armament Fitter is employed on general avionics maintenance beyond explosive-ordnance duties without obtaining the relevant avionics competencies."),
 ("chunk_p35_idx309","UYGUN","A pre-1991 Armament Fitter performs explosive-ordnance-related armament tasks for which they were trained."),
 # Aircraft Life Support (chunk_p34_idx296)
 ("chunk_p34_idx296","UYGUN","A Life Support Fitter who completed the RAAF Aircraft Life Support Fitter course maintains aircraft life support equipment, excluding oxygen systems."),
 ("chunk_p34_idx296","UYGUN DEĞİL","A general aircraft mechanic with no ALS Fitter course and no Certificate III in Public Safety (Aviation Life Support Maintenance) is employed to maintain aircraft life support equipment."),
 ("chunk_p34_idx296","UYGUN","A technician holding Certificate III in Public Safety (Aviation Life Support Maintenance) is employed as an Aircraft Life Support Fitter."),
 # Intro / TAR (chunk_p10_idx87)
 ("chunk_p10_idx87","UYGUN","State aircraft are maintained by competent and authorised individuals working within an approved organisation, with their work certified as correct."),
 ("chunk_p10_idx87","UYGUN DEĞİL","An individual maintains State aircraft outside of any approved organisation, with no certification of the work performed."),
 # Metal Machinist (chunk_p35_idx313)
 ("chunk_p35_idx313","UYGUN","An ex-ADF METMACH carries out metal machinist specialist trade work on ADF aircraft."),
 ("chunk_p35_idx313","UYGUN DEĞİL","A person trained by a registered training organisation that has not been approved by DAIRMAINT, DGTA-ADF is employed as a metal machinist on ADF aircraft."),
 # ek denge maddeleri
 ("chunk_p34_idx299","UYGUN","NDT certification of a technician is renewed annually in accordance with the process specified by AS3669."),
 ("chunk_p35_idx307","UYGUN DEĞİL","Aircraft surface finishing of ADF equipment is performed by a tradesperson whose upgrade course was never approved by DAIRMAINT, DGTA-ADF."),
 ("chunk_p14_idx117","UYGUN","A Technical Trainee gains experience towards competency assessment by performing tasks under the direct supervision of task-authorised personnel."),
 ("chunk_p22_idx176","UYGUN DEĞİL","A maintainer is authorised for a specific activity without completing the relevant ADF-approved off-the-job training specified in the MMP."),
 ("chunk_p19_idx140","UYGUN","An Avionics tradesperson, before moving to Structures-stream tasks, first completes the associated Structures units of competency."),
 ("chunk_p34_idx296","UYGUN DEĞİL","A Life Support Fitter performs maintenance on aircraft oxygen systems, treating them as ordinary life support equipment within their ALS scope."),
 ("chunk_p35_idx313","UYGUN","A metal machinist trained by a registered training organisation approved by DAIRMAINT, DGTA-ADF carries out specialist machining work on ADF aircraft."),
]


if __name__ == "__main__":
    from collections import Counter
    av = gen_matrix(AV_NAME, AV_NAME, 35)
    me = gen_matrix(ME_NAME, ME_NAME, 35)
    m26 = gen_mapping("Table_page26", "Table_page26", 16)
    m34 = gen_mapping("Table_page34", "Table_page34", 14)
    b36 = gen_bridging("Table_page36", 20)
    groups = [("Avionics matrix", av), ("Mechanical matrix", me),
              ("p26 trade map", m26), ("p34 trade map", m34), ("p36 bridging", b36)]
    tbl = []
    for _, g in groups:
        tbl += g
    for nm, g in groups:
        print(f"  {nm:18s}: {len(g):2d}  {dict(Counter(s['expected'] for s in g))}")
    print("TABLO TOPLAM:", len(tbl), dict(Counter(s["expected"] for s in tbl)))

    # ── Text senaryoları: chunk_id doğrula + section türet ──
    ch = json.load(open(ROOT / "data/kbs/defaust_test/text_chunks/text_chunks.json"))
    chunks = {c["chunk_id"]: c for c in (ch if isinstance(ch, list) else ch.get("chunks", ch))}
    txt_scn = []
    for cid, exp, text in TEXT:
        assert cid in chunks, f"BİLİNMEYEN chunk_id: {cid}"
        sp = chunks[cid].get("section_path") or []
        section = (sp[-1] if sp else "body")[:40]
        txt_scn.append({"section": section, "chunk_id": cid, "expected": exp, "text": text})
    print("TEXT TOPLAM:", len(txt_scn), dict(Counter(s["expected"] for s in txt_scn)))

    # ── Birleştir + numara ver ──
    allscn = tbl + txt_scn
    for i, s in enumerate(allscn, 1):
        s2 = {"item_no": i}
        s2.update(s)
        allscn[i - 1] = s2
    out_path = ROOT / "data/test_scenarios_defaust.json"
    json.dump(allscn, open(out_path, "w"), ensure_ascii=False, indent=1)
    print(f"\n✅ GENEL: {len(allscn)} senaryo (120 tablo + {len(txt_scn)} text), "
          f"denge {dict(Counter(s['expected'] for s in allscn))}")
    print(f"→ {out_path}")
