"""
AASTP-1 Retrieval Evaluation — Hit Rate@3 & MRR
================================================
Groq kullanmaz (hiç token harcanmaz). Sadece ChromaDB semantic search.
Çalıştır:
    python3 Ikinci_Donem/pipeline/eval.py
"""

import sys
from pathlib import Path

PIPELINE_DIR = Path(__file__).parent
sys.path.insert(0, str(PIPELINE_DIR))
sys.path.insert(0, str(PIPELINE_DIR / "scripts"))

from hyde_retriever import retrieve, format_context_for_llm

# ---------------------------------------------------------------------------
# Test seti — (query, expected_table_substring, category)
# expected_table_substring: retrieved doc'un table_name alanında bulunması gereken metin
# ---------------------------------------------------------------------------
TEST_SET = [
    # ── TABLE 6: Explosive Articles Compatibility Mixing ──────────────────
    ("Can Group B articles be stored together with Group D?",            "Table 6", "matrix"),
    ("Is mixing Compatibility Group F with Group B permitted?",          "Table 6", "matrix"),
    ("Group N articles stored with Group S — is this allowed?",          "Table 6", "matrix"),
    ("What are the storage rules for Compatibility Group L articles?",    "Table 6", "matrix"),
    ("Group H articles in the same magazine as Group J articles",        "Table 6", "matrix"),
    ("Compatibility Group C mixed with Group S articles",                "Table 6", "matrix"),
    ("Can Group A be stored with Group B?",                              "Table 6", "matrix"),
    ("Mixing Group D with Group E — what does AASTP-1 say?",            "Table 6", "matrix"),
    ("Group K articles stored with Group S without separation",          "Table 6", "matrix"),
    ("Storage rules for Compatibility Group G",                          "Table 6", "matrix"),

    # ── TABLE 5: Explosive Substances Compatibility ───────────────────────
    ("Rules for mixing explosive substances Compatibility Group B with D","Table 5", "matrix"),
    ("Can Group C explosive substances be mixed with Group S?",          "Table 5", "matrix"),
    ("Aboveground storage of explosive substances Group F",              "Table 5", "matrix"),

    # ── TABLE T.1: Chemical Hazard Symbols ───────────────────────────────
    ("What protective clothing is required for White Phosphorous (WP)?", "Table T.1", "chemical"),
    ("Can water be used to suppress a Calcium Phosphide fire?",          "Table T.1", "chemical"),
    ("What are the PPE requirements for Toxic Agents storage?",          "Table T.1", "chemical"),
    ("Napalm stored near water suppression system — is it safe?",        "Table T.1", "chemical"),
    ("What breathing apparatus is required for Smoke HC?",               "Table T.1", "chemical"),
    ("Full protective clothing requirements for chemical ammunition",     "Table T.1", "chemical"),
    ("Compatibility group for White Phosphorous ammunition",             "Table T.1", "chemical"),
    ("Which chemical substances require Set 1 full protective clothing?","Table T.1", "chemical"),

    # ── TABLE T.2: Emergency Withdrawal Distances ─────────────────────────
    ("Emergency withdrawal distances for nonessential personnel",        "Table T.2", "emergency"),
    ("How far should nonessential personnel withdraw during an emergency?","Table T.2", "emergency"),
    ("Minimum withdrawal distance for chemical ammunition incident",     "Table T.2", "emergency"),

    # ── TABLE 4: Hazard Division Storage / Aggregation Rules ─────────────
    ("Mixing rules for Hazard Division 1.1 and 1.2",                    "Table 4", "hazard_div"),
    ("Can HD 1.3 be stored in the same magazine as HD 1.4?",            "Table 4", "hazard_div"),
    ("Aggregation rules for Hazard Division 1.1",                       "Table 4", "hazard_div"),
    ("What are the aboveground storage rules for HD 1.2?",              "Table 4", "hazard_div"),

    # ── TEXT CHUNKS: General Chapter Content ─────────────────────────────
    ("What is the classification system for explosives compatibility groups?",
                                                                         "chunk",   "text"),
    ("How is NEQ calculated for mixed storage?",                         "chunk",   "text"),
]

TOP_K = 3

# ---------------------------------------------------------------------------
# Eval çalıştır
# ---------------------------------------------------------------------------
def run_eval():
    results = []
    categories: dict[str, list] = {}

    print(f"\n{'='*70}")
    print(f"  AASTP-1 RETRIEVAL EVALUATION  |  Top-{TOP_K}  |  {len(TEST_SET)} sorgu")
    print(f"  Mode: semantic-only (no HyDE, 0 Groq token)")
    print(f"{'='*70}\n")

    for idx, (query, expected, category) in enumerate(TEST_SET):
        result = retrieve(query, groq_client=None)   # ← Groq yok
        matches = result.matches

        # expected_table_substring match → rank bul
        rank = None
        for i, m in enumerate(matches[:TOP_K]):
            name = m.get("table_name", m.get("title", ""))
            if expected.lower() in name.lower():
                rank = i + 1   # 1-indexed
                break

        hit_at_k = rank is not None
        rr = (1.0 / rank) if rank else 0.0

        top_names = [
            m.get("table_name", m.get("title", ""))[:50]
            for m in matches[:TOP_K]
        ]

        status = "✅" if hit_at_k else "❌"
        print(f"[{idx+1:02d}] {status} [{category}] {query[:65]}")
        print(f"       Expected: {expected}")
        if rank:
            print(f"       Found at rank #{rank}")
        else:
            print(f"       NOT found in top-{TOP_K}")
            for i, n in enumerate(top_names):
                print(f"         #{i+1}: {n}")
        print()

        entry = {"query": query, "expected": expected, "category": category,
                 "hit": hit_at_k, "rr": rr, "rank": rank, "top": top_names}
        results.append(entry)
        categories.setdefault(category, []).append(entry)

    # ── Metrikler ──────────────────────────────────────────────────────────
    hr_at_k = sum(r["hit"] for r in results) / len(results)
    mrr     = sum(r["rr"]  for r in results) / len(results)

    print(f"{'='*70}")
    print(f"  OVERALL RESULTS  ({len(results)} sorgu)")
    print(f"{'='*70}")
    print(f"  Hit Rate@{TOP_K}  :  {hr_at_k:.3f}  ({sum(r['hit'] for r in results)}/{len(results)})")
    print(f"  MRR         :  {mrr:.3f}")
    print()

    print(f"  {'Category':<14}  {'Queries':>7}  {'HR@3':>6}  {'MRR':>6}")
    print(f"  {'-'*40}")
    for cat, entries in sorted(categories.items()):
        cat_hr  = sum(e["hit"] for e in entries) / len(entries)
        cat_mrr = sum(e["rr"]  for e in entries) / len(entries)
        print(f"  {cat:<14}  {len(entries):>7}  {cat_hr:>6.3f}  {cat_mrr:>6.3f}")
    print()

    # ── Hedef karşılaştırma ───────────────────────────────────────────────
    TARGET_HR  = 0.85
    TARGET_MRR = 0.75
    hr_pass  = "✅" if hr_at_k >= TARGET_HR  else "❌"
    mrr_pass = "✅" if mrr     >= TARGET_MRR else "❌"
    print(f"  Targets (2nd Semester 1st Presentation):")
    print(f"  {hr_pass}  HR@{TOP_K} ≥ {TARGET_HR}  →  {hr_at_k:.3f}")
    print(f"  {mrr_pass}  MRR  ≥ {TARGET_MRR}  →  {mrr:.3f}")
    print(f"{'='*70}\n")

    return {"hr_at_k": hr_at_k, "mrr": mrr, "results": results}


if __name__ == "__main__":
    run_eval()
