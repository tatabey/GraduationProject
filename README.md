# ComplAI — Multimodal RAG for Regulatory Compliance Auditing

ComplAI (*comply* + *AI*) is a **domain- and language-independent, retrieval-augmented
generation (RAG)** system that automates **compliance auditing** over regulatory standards.
A standard PDF is parsed once into a searchable knowledge base; each item of an uploaded audit
report is then matched against that base and bound to a binary verdict —
**COMPLIANT** or **NON-COMPLIANT** — with a grounded rationale.

The system was developed and stress-tested on the NATO **AASTP-1** explosives-storage standard
and validated, **with zero code changes**, on three further standards in two languages
(US **UFC 4-010-01**, Australian **DEF(AUST) 9022**, and the Turkish **BYKHY** fire-protection
regulation).

---

## Why it is hard

Compliance rules live in dense PDFs and depend on three things that classical keyword search
cannot handle:

- **Spatial reasoning** — a decision is hidden in the cell at a row/column intersection of a table.
- **Indirect references** — a cell points to a footnote, which points to another rule.
- **Multimodality** — critical information is split across prose, tables and images.

A standard LLM applied directly hallucinates rules; in a safety-critical setting a wrong
"compliant" verdict is worse than no verdict. ComplAI grounds every decision in the retrieved
evidence.

---

## Key contributions

1. **Generic table serialization** — detects a table's structural type (binary matrix, value
   matrix, key-value) from purely structural signals and renders it into context-preserving
   prose, with **no domain-specific constants**. Merged-header alignment and math-formula
   preservation are handled explicitly.
2. **Modality-decoupled two-channel retrieval** — tables and text are retrieved in separate
   channels and combined as **3 tables + 3 text passages with no statistical fusion**. Every
   cross-modality fusion attempt was shown to regress one side; structural separation plus a
   strong cross-encoder reranker wins on both.
3. **Domain & language independence** — a single pipeline audits four standards in two languages
   with zero code changes.
4. **Provider-agnostic, cost-aware verdict generation** — the verdict LLM is swappable with a
   one-line config change; the production model is chosen by an explicit accuracy/cost trade-off.

---

## Results (summary)

| Standard | Lang | Retrieval HR@3 | Verdict accuracy |
|---|---|---|---|
| AASTP-1 (primary) | EN | 99.3% (tables) · 84.5% (text) | 95.5% |
| DEF(AUST) 9022 | EN | 97.5% | 91.2% |
| BYKHY | TR | 92.7% | 87.8% |

Verdict model in production: **Mistral Small 24B**. Retrieval: **bge-large** embeddings +
**bge-reranker** cross-encoder (local GPU). See `system/docs/TEST_RAPORU.md` for the full
ablation history and per-decision rationale.

---

## Architecture

```
Offline indexing                         Online auditing
  PDF standard                             Audit item
      |                                        |
  MinerU parsing                       Two-channel retrieval (table + text)
      |                                        |
  Semantic units                         Reranking (bge-reranker)
  (table serialization + text chunks)          |
      |                                    3 + 3 context
  Indexing (ChromaDB)  ───────────────►  Verdict (LLM)
                                               |
                                       COMPLIANT / NON-COMPLIANT
```

---

## Repository structure

```
system/
├── config.py            # all settings/flags in one place
├── server.py            # FastAPI + htmx web interface (ComplAI)
├── pipeline/
│   ├── kb_builder.py        # PDF → knowledge base orchestration
│   ├── table_serializer.py  # generic table → prose
│   ├── retriever.py         # two-channel 3+3 retrieval
│   ├── lexical.py           # BM25 candidate channel
│   ├── auditor.py           # provider-agnostic verdict LLM
│   └── report_parser.py
├── scripts/             # mineru_batch, table_assembler, text_chunker
├── tools/               # eval_all, eval_retrieval, benchmark_local, reindex_kb, ...
├── data/test_scenarios*.json   # evaluation scenario sets (included)
└── docs/                # technical documentation (TEST_RAPORU.md, ...)
```

> **Not included in the repository** (excluded via `.gitignore`): local model weights
> (`system/models/`), generated knowledge bases (`system/data/kbs/`), benchmark snapshots
> (`system/data/benchmark/`), and the standard PDFs. These are regenerated or downloaded
> locally (see Setup).

---

## Setup

```bash
# 1. Python dependencies
pip install -r requirements.txt

# 2. API keys — copy the template and fill in your own keys
cp system/.env.example system/.env      # then edit system/.env

# 3. Retrieval models — download the local models into system/models/
python3 system/tools/download_models.py
#    Downloads:
#      - BAAI/bge-reranker-base                                   (cross-encoder reranker — required)
#      - sentence-transformers/paraphrase-multilingual-mpnet-...  (multilingual embedding)
#    The English embedding (BAAI/bge-large-en-v1.5) is fetched automatically by
#    sentence-transformers on first use; add --with-bge-large to pre-download it too.
```

A CUDA GPU is recommended for the embedding/reranking models (developed on an RTX 3050 Ti,
4 GB, fp16); CPU-only also works (slower).

---

## Usage

```bash
# Launch the web interface
python3 system/server.py        # → http://127.0.0.1:8000
```

In the interface: (1) create a knowledge base from a standard PDF, (2) upload an audit report
and run the audit, (3) read the per-item COMPLIANT / NON-COMPLIANT verdicts with rationales.

> **First run:** a fresh clone ships **no knowledge bases** (`system/data/kbs/` is gitignored).
> Build one first via the interface — upload a standard PDF and index it. The evaluation
> scenario sets under `system/data/*.json` are included, but the commands below need a
> matching KB to exist (e.g. index a KB named `aastp_test` before running them).

```bash
# Verdict benchmark (requires a KB named 'aastp_test' to be built first)
python3 system/tools/benchmark_local.py --models mistral-small-latest \
  --kb aastp_test --scenarios system/data/test_scenarios.json --tag run1

# Retrieval evaluation (guardrail). The --baseline snapshot is generated on your
# first run; omit it the first time, then reuse it to catch regressions.
python3 system/tools/eval_retrieval.py --kb aastp_test \
  --scenarios system/data/test_scenarios.json --tag run1
```

---

## Tech stack

Python · FastAPI · htmx · Tailwind CSS · ChromaDB · sentence-transformers · MinerU (parsing) ·
Mistral / Cerebras / Groq / Ollama (provider-agnostic verdict client).

---

## Author

**Taha Alparslan Atabey** — Gebze Technical University, Department of Computer Engineering.
Supervisor: Asst. Prof. Dr. Salih Sarp.
