# Policy Insight

Turns a folder of insurance policy PDFs (text-based or scanned) into a queryable, evidenced index and answers
underwriter questions such as *"Which liability policies carry excess auto cover in the US, and at what
attachment point and limit?"* — as a table, with a page image and verbatim quote behind every value.

Caseathon prototype for If Industrial. Scope: use case Q1 on the 19 example policies. The design argument
(extract once, query many) and the full requirements are in [docs/prd.md](docs/prd.md).

## Prerequisites

- Python 3.13 and [`uv`](https://docs.astral.sh/uv/) (on this network `uv` needs `--native-tls`)
- The `claude` CLI (Claude Code), logged in. All LLM calls go through `claude -p` headlessly — no API key needed.
  In production the same prompts run on the Anthropic API / Batch API unchanged.

## Run it

```bash
uv sync --native-tls
```

Ingest the example corpus (rasterise → Claude reads page images → SQLite index; ≈10–15 min for 19 docs):

```bash
uv run --native-tls python -m ingest
```

Launch the UI:

```bash
uv run --native-tls streamlit run app.py
```

Compare the index with the manual ground truth:

```bash
uv run --native-tls python eval/run_eval.py
```

Useful ingest switches: `--force` (re-ingest), `--limit 2` (smoke test), `--only 2025.12.12` (path filter), `--max-pages 5`, `--concurrency 1`,
`--dry-run` (rasterise only, no Claude), `--reparse` (re-merge from stored JSON after a merge/validator change, no Claude), `--model claude-opus-5`. Re-running skips documents whose file hash is
already indexed.

## Layout

```
app.py                 Streamlit UI: Ask / Evidence / Scale / Index tabs
config.py              paths, chunk size, concurrency, model, scale-tab defaults (env overrides PI_*)
ingest/
  __main__.py          CLI entry point (python -m ingest)
  pipeline.py          per-document orchestration: hash → rasterise → chunks → merge → SQLite
  rasterise.py         PDF → data/pages/<doc_id>/p<N>.png (pypdfium2, 2× scale ≈ 1,200 px wide)
  claude_cli.py        `claude -p --output-format json` wrapper: JSON parsing, retries, metrics
  extract.py           per-chunk extraction (≤15 pages/call), schema validation, one retry
  merge.py             merge chunks per document, compute "needs review" flags
  prompts/extraction.md
index/
  db.py                SQLite schema + access (documents, policy_facts, evidence, ingest_metrics, raw_extractions)
  schema.py            the published query schema (field/op whitelist) and the extraction JSON shape
query/
  translate.py         NL question → JSON query via claude -p, validated against the whitelist
  execute.py           JSON query → parametrised SQL (the model never writes SQL)
  chat.py              follow-up chat over the current result rows, with citations
  prompts/translate.md, chat.md
ui/
  evidence.py          page image + verbatim quote + confidence panel
  scale.py             measured per-doc metrics and 200M-document extrapolation
eval/
  ground_truth.csv     manual labels for the 19 documents
  run_eval.py          precision/recall + exact-match report
tests/                 unit tests for everything that does not need Claude (uv run --native-tls pytest)
data/                  generated: index.sqlite, pages/, query_log.jsonl (gitignored)
docs/                  PRD, use cases, example PDFs
```

## Adding documents

Drop PDFs anywhere under `docs/examples/` (or point `--root` elsewhere) and run the ingest command again.
Text PDFs and scans take the same path (page images) in the prototype, so nothing else changes. The example set
is 17/19 scans, which is why that path is the one built; the real archive is assumed to be mostly text PDFs, and
the Scale tab prices the production path accordingly (text layer for free, OCR only on the scanned share).

## How it works

1. **Ingest (once per document).** Pages are rendered to PNG. Claude reads ≤15 pages per call and returns one
   JSON object per chunk: header fields, cover facts, and for every non-null cover fact an `evidence_page`,
   a verbatim `evidence_quote` and a `confidence`. Chunks are merged per document; every CLI call's duration,
   tokens and API-equivalent cost are stored in `ingest_metrics`.
2. **Query (per question).** Claude translates the question into a JSON query over a fixed, published schema
   (`index/schema.py`). The app validates it against the whitelist and runs it in SQLite. Unmappable questions
   get an explicit "not indexed" answer listing what the index can answer.
3. **Trust.** Every row links to the page image and quote its values came from. A row is flagged *Needs review*
   when any value is low-confidence, a value has no quote, a chunk failed extraction, or the US excess auto
   cover is scope-restricted (e.g. "no cover in USA except for travellers from abroad") — the restriction is
   stored verbatim in `ea_us_restriction` and shown as the review reason.
4. **Scale.** The Scale tab shows measured seconds/tokens/cost per document from the actual run and extrapolates
   to 200M documents under editable assumptions — including the share of the archive that is scanned (default
   20 %), since only those documents need OCR; text PDFs are extracted from their text layer.

## Results on the example corpus (2026-09-11)

`eval/run_eval.py` against `eval/ground_truth.csv`, after ingesting all 19 documents (226 pages, 17 of them scans):

| Metric | Result |
|---|---|
| US excess auto cover — precision / recall | **1.00 / 1.00** (tp 4, fp 0, fn 0, tn 13) |
| Attachment point exact match (true positives) | **4 / 4** |
| Limit exact match (true positives) | **4 / 4** |
| Rows flagged *Needs review* | 7 / 17 — six negatives with low confidence on *absence* or a missing quote, plus one positive (LP0000036557-30) whose US excess auto cover is scope-restricted |
| Documents labelled `?` (either answer accepted) | 2 — both prints of LP0000045733-23, whose schedule has no explicit excess-auto clause |

Ground-truth provenance is recorded per row in the `labelled_by` column: 2 rows verified by an underwriter,
3 with the decisive page checked by eye, 14 negatives from a model-assisted read. Treat the negatives as
"reviewed, not audited"; the positives are the ones that were actually checked against the page.

Measured ingestion cost (Scale tab): median 8 pages/doc, p50 27 s/doc, ≈ $0.18/doc API-equivalent via the CLI
(inflated by Claude Code prompt overhead; the API path is estimated at ≈ $0.02/doc for page images). The production
path priced on the Scale tab — text layer for text PDFs, OCR only on the ~20 % scanned share, text-only extraction
with Sonnet 5 via the Batch API — comes to ≈ $0.008/doc blended, ≈ $1.7 M for 200 M documents before triage.

## Known limitations

- Prototype drives the Claude Code CLI under a subscription: rate-limited, and `total_cost_usd` is an
  API-equivalent figure, not a bill.
- Only Q1 fields are extracted; `offshore_indicators` and `layer` are reserved in the schema for Q2/Q3.
- Page images and prompt text are sent to Anthropic via the CLI; everything else stays local
  (`data/index.sqlite`, `data/pages/`).
- No highlight boxes on page images (stretch goal FR-6); the quote is the source of truth.
- Streamlit's row selection requires a recent Streamlit (≥1.35).
- On some Windows machines pytest cannot create its default temp dir; run
  `uv run --native-tls pytest -p no:cacheprovider --basetemp=<writable folder>`.
