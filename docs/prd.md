# PRD — Policy Insight: turning If Industrial's document archive into a queryable knowledge source

| | |
|---|---|
| Status | Draft v1 — 2026-09-11 |
| Owner | Mathias Rönnblom (solo/pair build) |
| Time box | 6 hours to a live demo + runnable repo |
| Scope | Use case Q1 only (excess auto liability, US) on the 19 example policies |

---

## 1. Problem

If Industrial holds ~200 million documents (policies, wordings, schedules, correspondence) in many formats and languages. Valuable facts — cover types, geography, attachment points, limits, layer structures — are locked inside free text, often in scanned PDFs with no text layer. Existing metadata is not sufficient to answer portfolio questions such as *"which of our liability policies carry excess auto cover in the US, and at what attachment point and limit?"* Today that question means an underwriter opening documents one by one.

The caseathon asks for a working prototype that shows how such an archive becomes an **active, trustworthy knowledge source**: natural-language search over content, analysis/aggregation, format-agnostic handling, and results whose sources are explicit — designed so that the approach plausibly scales to 200M documents, not just a demo set.

## 2. Goals and non-goals

### Goals (must be true at the end of the 6 hours)

1. **G1 — Answer Q1 correctly on the example set.** For the 19 example policies, list every policy with excess auto liability cover in the United States, with attachment point (excess point) and limit, currency, and the page + quoted text each value came from.
2. **G2 — Natural-language in, table out.** An underwriter types a question in plain English (or Swedish); the system returns a result table, not prose, with follow-up chat over that result set.
3. **G3 — Trust by construction.** Every extracted value is traceable to a page image and a quoted snippet, carries a confidence level, and low-confidence values are visibly flagged for review.
4. **G4 — Scale story backed by measurement.** The architecture is *extract-once, query-many*; a dashboard shows measured per-document time and token cost from this run and extrapolates to 200M documents under stated assumptions.
5. **G5 — Runnable by someone else.** `README` + one command to ingest, one command to launch the UI.

### Non-goals (explicitly out of scope for this prototype)

- Use cases Q2 (offshore) and Q3 (layer grouping). The extraction schema leaves room for them (§7) but nothing is built or demoed.
- Any corpus beyond the 19 example PDFs. No synthetic scale-up.
- Authentication, multi-user, deployment, persistence beyond local files/SQLite.
- Export to Excel/CSV, review/verify workflow, live ingestion during the demo (all considered; deprioritised by the owner).
- Pixel-accurate highlight boxes on page images (stretch only, see FR-6).
- Production-grade LLM access. The prototype drives the Claude Code CLI headlessly (§4); production would use the Anthropic API / Batch API.

## 3. Users and primary scenario

**Primary user:** underwriter / portfolio analyst at If Industrial. Domain expert, comfortable with tables and filters, does not want to read prose answers and does not trust a number without seeing where it came from.

**Primary scenario (the demo):**

1. Analyst opens the app and types: *"Find all liability policies with excess auto cover in the United States. Show attachment point and limit."*
2. Within a few seconds a table appears: one row per matching policy — policy no., policyholder (if legible), period, attachment point, limit, currency, confidence, page reference.
3. Analyst clicks a row → sees the rendered page image and the exact quoted sentence(s) the values were extracted from.
4. Analyst asks a follow-up in the chat: *"Which of these have a limit above EUR 10M?"* / *"Sum the limits by currency."* → answered from the result set, still with citations.
5. Analyst opens the **Scale** tab: measured pages/doc, seconds/doc, tokens/doc, cost/doc from this ingestion run, extrapolated to 200M documents; and the pipeline diagram explaining why query cost does not grow with corpus size.

## 4. Facts established during discovery (constraints the design must respect)

| # | Finding | Consequence |
|---|---|---|
| F1 | **17 of the 19 example PDFs have no text layer** (scans). Only the two 2022-06-08 Danfoss files are text PDFs. | OCR/vision is mandatory on the main path, not a fallback. |
| F2 | Documents are 2–85 pages (median ~6); mixed languages (EN, DA, FI, SV observed); personal/company identifiers partly redacted (black boxes). | Chunked page processing; extraction must tolerate `null` policyholder. |
| F3 | Semi-structured header on page 1 (Policy no. `LP…`, Client no. `LC…`, period, print date) followed by free-text cover descriptions. | Header fields are reliable anchors; cover facts need reading, not regex. |
| F4 | No Anthropic API key or `ant` CLI on the build machine; only the `claude` CLI under a Claude Code Pro subscription. `ANTHROPIC_BASE_URL` is set in the environment. | LLM calls go through `claude -p` (headless). Zero marginal cost, but rate-limited and not a production pattern. |
| F5 | `claude -p` cannot read PDFs directly on this machine (needs poppler). It reads **PNG page images** fine. | Rasterise PDFs in Python (`pypdfium2` + `pillow`), pass page PNGs to Claude. Page images are also needed by the UI (G3), so this is not extra work. |
| F6 | Measured: 3-page scan → correct structured JSON with page-level evidence quote in ~18 s, ~$0.03 API-equivalent. | 19 docs ≈ 220 pages ≈ 10–15 min sequential ingestion; comfortably inside the time box. |
| F7 | `uv` works only with `--native-tls` on this network; project `settings.json` denies `pip install`, `uv add`, `uv pip`. | Dependencies declared once in `pyproject.toml`; run everything via `uv run --native-tls`. |
| F8 | Ground truth for Q1 does not exist. | Manual labelling of the 19 docs (positives + attachment/limit) is a task inside the 6 hours (§9). |

## 5. Solution overview

**Principle: extract once, query many.** LLM reading cost is paid per document at ingestion and produces a structured, evidenced record. Questions are answered against that index; the LLM at query time only translates the question and reasons over a handful of rows. This is what makes the same design plausible at 200M documents (§10).

```
                 INGESTION (once per document)                          QUERY (per question)
┌───────────┐   ┌──────────────┐   ┌────────────────────┐   ┌────────┐   ┌──────────────┐   ┌────────────┐
│ PDF file  │──▶│ Rasterise    │──▶│ Claude reads pages │──▶│ SQLite │◀──│ NL question →│◀──│ Streamlit  │
│ (any fmt) │   │ pypdfium2    │   │ (claude -p, JSON)  │   │ index  │   │ filter/agg   │   │ UI         │
└───────────┘   │ → PNG/page   │   │ schema + evidence  │   │ + page │──▶│ (Claude)     │──▶│ table,     │
                └──────────────┘   │ + confidence       │   │ images │   └──────────────┘   │ evidence,  │
                                   └────────────────────┘   └────────┘   ┌──────────────┐   │ chat,      │
                                        ▲ chunked ≤15 pages/call         │ follow-up    │   │ scale tab  │
                                        └ merged per document            │ chat on rows │──▶│            │
                                                                         └──────────────┘   └────────────┘
```

Components (all Python, single repo):

| Component | Responsibility | Tech |
|---|---|---|
| `ingest/` | Walk `docs/examples/**/*.pdf`, rasterise pages, call Claude per page-chunk, merge, validate, write to SQLite + `data/pages/<doc_id>/p<N>.png`; record timings/tokens. | `pypdfium2`, `pillow`, `subprocess` → `claude -p --output-format json` |
| `index` | `data/index.sqlite` — documents, extracted fields, evidence, ingestion metrics. | `sqlite3` (stdlib) |
| `query/` | Translate a question into a validated JSON query (filters, columns, aggregation) over the known schema; execute; produce a one-line explanation. Follow-up chat over the current result set. | `claude -p` with a strict system prompt and JSON output |
| `app.py` | Streamlit UI: Ask, Results, Evidence, Scale tabs. | `streamlit` |

## 6. Functional requirements

Each requirement has acceptance criteria (AC). "Must" = required for the demo; "Should" = do if time permits; "Stretch" = only if everything else is green.

### FR-1 Ingestion of heterogeneous PDFs — Must
- Ingests every PDF under a configurable root; text PDFs and scans go through the **same** page-image path (no branching logic to maintain).
- Pages rasterised at a scale that keeps small print legible (start at 1.5×; ~1,200 px wide) and saved for the UI.
- Documents longer than 15 pages are processed in chunks of ≤15 pages; chunk results are merged per document (first non-null wins for header fields; cover facts union with their evidence).
- Idempotent: re-running skips documents whose file hash is already indexed; `--force` re-ingests.
- Concurrency configurable (default 3 parallel `claude -p` processes) with retry on transient CLI failure.
- **AC:** `uv run --native-tls python -m ingest` indexes all 19 documents with zero unhandled exceptions; each document has ≥1 page image and one `documents` row; a rerun completes in <5 s.

### FR-2 Structured extraction with evidence — Must
- Claude returns a JSON object per chunk conforming to the schema in §7. Every non-null cover fact carries `evidence_page` (1-based, absolute page number within the document) and `evidence_quote` (verbatim text as read from the page), plus `confidence ∈ {high, medium, low}`.
- Output is parsed defensively (strip code fences, validate types); a chunk that fails validation is retried once, then recorded as `extraction_failed` for that chunk — never silently dropped.
- The prompt instructs: do not infer; if the document does not state a value, return `null`; quote in the document's original language; report monetary values with currency and the exact figure as written.
- **AC:** For the 6 documents in `excess auto liability/`, `has_excess_auto_liability` and `geography_us` are set correctly and attachment/limit match the manual ground truth (§9). For the 13 others, `has_excess_auto_liability` is false or null with no US excess-auto figures fabricated.

### FR-3 Natural-language query → result table — Must
- The user types a free-text question. Claude translates it into a JSON query against a **published, fixed schema** (§7): `filters[]` (field, op, value), `columns[]`, optional `group_by`/`aggregate`. The app validates the JSON against the schema whitelist and executes it in SQLite. No free-form SQL from the model.
- The table shows the requested columns plus, always: `policy_no`, `confidence`, and a "source" link per evidenced value.
- If the question cannot be mapped to the schema, the app says so and lists what it *can* answer (the schema's fields) rather than hallucinating a table.
- Questions in Swedish and English both work.
- **AC:** The demo question in §3 returns exactly the ground-truth positive set with attachment point and limit populated. *"Hur många policyer har excess auto-täckning i USA?"* returns a count. An unmappable question (e.g. *"who is the broker?"*) yields the explicit "not indexed" response.

### FR-4 Follow-up chat over the result set — Must
- A chat box below the table. Each turn sends: the current result rows (with evidence quotes) + conversation history + the user's message. Claude answers in prose, citing `policy_no` and page for every fact, and may return an updated filter to refine the table.
- Claude is instructed to answer only from the supplied rows; if the answer is not in them, say so.
- **AC:** *"Sum the limits by currency"* and *"which of these has the highest attachment point?"* are answered correctly for the demo result set, each with citations.

### FR-5 Evidence view — Must
- Clicking a row (or a value's source link) opens the evidence panel: the page image at readable size, the verbatim `evidence_quote` displayed next to it, the field name, and confidence. Multiple evidenced fields for the same document are listed with their own page/quote.
- **AC:** For every positive Q1 row in the demo, the panel shows the page on which the attachment point actually appears and a quote that is visibly present on that page.

### FR-6 Highlight on page image — Stretch
- Ask Claude to also return a normalised bounding box (`x0,y0,x1,y1` in 0–1) for each quote; if present, draw a translucent rectangle on the page image. Boxes are advisory — the quote remains the source of truth. If not implemented, the UI simply shows quote + page (still satisfies G3).

### FR-7 Confidence and review flags — Must
- Each extracted value has a confidence level from the model. Rows are flagged **"Needs review"** when any displayed value is `low`, or when a non-null value has no evidence quote, or when the document had any `extraction_failed` chunk.
- Flagged rows are visually distinct and sort to the bottom by default; a toggle shows only flagged rows.
- **AC:** Deliberately corrupting one evidence quote in the index causes that row to be flagged.

### FR-8 Scale & cost dashboard — Must
- A **Scale** tab showing, from the actual ingestion run: documents, pages, median/mean pages per doc, seconds per doc (p50/p95), input/output tokens per doc, API-equivalent cost per doc (from `claude -p`'s `total_cost_usd`).
- Extrapolation table to 200M documents under editable assumptions (avg pages/doc, model price per 1M tokens, batch discount, share of corpus that passes a cheap pre-filter). Defaults from §10.
- A short explanation panel (3–5 bullets) of the extract-once/query-many argument and the stages of the scale-out pipeline.
- **AC:** Numbers update when assumptions change; the tab renders in <1 s from SQLite.

### FR-9 Runnable repo — Must
- `README.md`: prerequisites (Python 3.13, `uv`, `claude` CLI logged in), two commands (`ingest`, `streamlit run app.py`), directory layout, how to add documents, known limitations.
- **AC:** A second person on a clean checkout with the same prerequisites reproduces the demo.

## 7. Data model

### 7.1 Extraction schema (what Claude returns per chunk)

Designed for Q1 but shaped so Q2/Q3 fields can be added without changing the pipeline.

```json
{
  "policy_no": "LP0000045733-23",
  "client_no": "LC0021022747",
  "policyholder": null,
  "policy_period_start": "2022-01-01",
  "policy_period_end": "2022-12-31",
  "document_language": "en",
  "product_line": "liability | property | marine | other",
  "cover_summary": ["General Liability", "Product Liability", "Recall"],
  "geography_scope": "World Wide",
  "geography_us": true,
  "has_excess_auto_liability": true,
  "excess_auto": {
    "attachment_point_amount": 1000000,
    "attachment_point_currency": "USD",
    "limit_amount": 25000000,
    "limit_currency": "EUR",
    "basis": "per occurrence",
    "notes": "applies to owned/hired/non-owned autos in USA",
    "evidence_page": 8,
    "evidence_quote": "The insurance covers … in excess of USD 1,000,000 …",
    "confidence": "high"
  },
  "field_evidence": {
    "geography_us": {"evidence_page": 2, "evidence_quote": "Geographical scope: World Wide", "confidence": "high"},
    "has_excess_auto_liability": {"evidence_page": 8, "evidence_quote": "…", "confidence": "high"}
  },
  "offshore_indicators": null,
  "layer": null
}
```

`offshore_indicators` and `layer` are reserved (always `null` in this prototype) so the schema is stable when Q2/Q3 are added.

### 7.2 SQLite tables

- `documents(doc_id PK, path, file_hash, pages, ingested_at, status, error)`
- `policy_facts(doc_id FK, policy_no, client_no, policyholder, period_start, period_end, language, product_line, geography_scope, geography_us, has_excess_auto, ea_attachment_amount, ea_attachment_currency, ea_limit_amount, ea_limit_currency, ea_basis, ea_notes, needs_review)`
- `evidence(id PK, doc_id FK, field, page, quote, confidence, bbox_json NULL)`
- `ingest_metrics(doc_id FK, chunk_index, pages_in_chunk, duration_ms, input_tokens, output_tokens, cost_usd, num_turns, model)`
- `raw_extractions(doc_id FK, chunk_index, json)` — kept for debugging and re-processing without re-reading pages.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Query latency | Table answer ≤ 8 s end-to-end (one `claude -p` translation call + SQLite). Follow-up chat ≤ 15 s. |
| Ingestion throughput | ≥ 4 docs/min with 3 workers on the Pro plan; must degrade gracefully (backoff) on rate limits. |
| Determinism | Query translation runs with a fixed system prompt and schema; identical question → identical JSON query in ≥ 9/10 runs. |
| Safety of model output | Model never produces SQL; only whitelisted fields/ops. Evidence quotes are displayed as text, never rendered as HTML. |
| Data residency | Everything stays local except page images/text sent to Claude via the CLI. Documented in README. |
| Observability | Every CLI call logs duration, tokens, cost, exit status to `ingest_metrics` / a query log. |

## 9. Evaluation and acceptance

1. **Ground-truth labelling (≈30 min, inside the time box).** For each of the 19 documents record: `has_excess_auto_liability` (Y/N), `geography_us` (Y/N), attachment point, limit, currency, evidence page. Store as `eval/ground_truth.csv`. The six documents in `excess auto liability/` are expected positives; the 13 others in `Layers/`, `Offshore Projects/`, `Projects/` are the negative/distractor set.
2. **Metrics reported in README and on the Scale tab:** precision and recall for "policy has US excess auto cover"; exact-match rate for attachment point and limit among true positives; share of rows flagged "Needs review".
3. **Acceptance thresholds for the demo:** recall = 100 % on the 6 positives; zero fabricated figures on negatives (precision = 100 % or every false positive is flagged); attachment/limit exact match ≥ 5/6, with any miss flagged.
4. A tiny `eval/run_eval.py` compares index vs ground truth so the numbers are reproducible, not hand-typed.

## 10. Scaling to 200 million documents (design argument)

The prototype is deliberately built as the small end of a pipeline whose cost profile is linear in documents *once*, and near-constant per query.

**Stage 0 — Triage on existing metadata (no LLM).** Product line, document type, date, language from existing metadata and filenames route documents to the right extraction schema and exclude irrelevant ones. Even a weak pre-filter (e.g. only liability policies for Q1) cuts the LLM-read population by an order of magnitude.

**Stage 1 — OCR once, store text + layout.** At archive scale, vision-LLM reading of every page is the expensive path. Run a dedicated OCR (Azure Document Intelligence, AWS Textract, or open-source on GPU) once per page; store text with bounding boxes. This yields exact highlight coordinates (what FR-6 approximates) and makes later extraction a text task.

**Stage 2 — Schema extraction with a small model, batched.** Text-only extraction with Haiku-class models via the Batch API (50 % discount), asynchronous, resumable, keyed by document hash. Extraction prompt = the schema in §7 with evidence quotes required, exactly as in the prototype. Escalate only low-confidence documents to a larger model.

**Stage 3 — Index.** Structured facts + evidence in a columnar/OLAP store (or Postgres for 10⁸ rows); text in a search engine with vector + BM25 for the "unknown question" path. Queries hit the index; the LLM only translates and summarises.

**Stage 4 — Human feedback loop.** Flags and corrections from underwriters become regression tests and few-shot examples; re-extraction is per document, never per corpus.

**Cost envelope (illustrative — the Scale tab lets the jury change every assumption):**

| Assumption | Value |
|---|---|
| Documents / avg pages | 200 M / 8 → 1.6 B pages |
| Prototype path (vision, ~1,500 tokens per page image + ~400 output tokens/doc) | ~12.4 k tokens/doc |
| Sonnet 5 at $2 / $10 per 1M tokens, Batch −50 % | ≈ $0.014 / doc → **≈ $2.8 M** for the full corpus |
| Haiku 4.5 at $1 / $5 per 1M, Batch −50 % | ≈ $0.007 / doc → **≈ $1.4 M** |
| With Stage 0 triage keeping 20 % of corpus | **≈ $0.3–0.6 M** |
| Stage 1 OCR (≈ $1.5 per 1,000 pages) + text-only Haiku extraction (~4 k tokens/doc) | OCR ≈ $2.4 M one-off (dominant), LLM ≈ $0.4 M |

Point of the table: **the archive is read once**; a query costs cents regardless of corpus size. Throughput is a parallelism/batch question, not an architecture question. Price inputs are the September 2026 Anthropic list prices and must be re-checked before any real business case.

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pro-plan rate limits stall ingestion mid-build | Medium | Start ingestion early (hour 1), cache raw JSON, low concurrency; the UI works off the index, so a partial corpus still demos. |
| `claude -p` output not clean JSON | Medium | Fence-stripping + schema validation + one retry; `raw_extractions` kept so prompts can be fixed and re-parsed without re-reading pages. |
| Attachment point vs limit vs deductible confusion on complex wordings | Medium | Prompt with definitions and a worked example; require the quote; confidence flag; ground truth catches it. |
| Long documents (85 pages) blow time budget | Low | Chunking; `--max-pages` switch for the demo run. |
| Redactions remove policyholder → grouping impossible | Certain | Not needed for Q1; use `client_no` as the grouping key if ever needed. |
| Time: UI polish eats extraction correctness | High | Milestone order below is fixed: correctness before chrome. |
| Headless-CLI dependence questioned by jury | Medium | State it plainly: dev-time expedient; the same prompt/schema runs on the API or Batch API unchanged (Stage 2). |

## 12. Six-hour plan

| Hour | Milestone | Done when |
|---|---|---|
| 0:00–0:45 | Repo skeleton, `pyproject.toml`, rasteriser, `claude -p` wrapper with JSON parsing + metrics | One document end-to-end into SQLite |
| 0:45–1:30 | Extraction prompt + schema (§7), chunking, merge; kick off full ingestion in background | 19 docs ingesting; ground-truth labelling started in parallel |
| 1:30–2:30 | Ground truth finished; `run_eval.py`; iterate prompt on misses | Recall 6/6, no fabricated figures on negatives |
| 2:30–3:45 | Streamlit: Ask → query translation → table; evidence panel with page image + quote; review flags | Demo question answers correctly with sources |
| 3:45–4:30 | Follow-up chat over result set | Sum/compare follow-ups work with citations |
| 4:30–5:15 | Scale tab from `ingest_metrics` + assumptions panel | Extrapolation renders; numbers match §10 order of magnitude |
| 5:15–6:00 | README, demo dry-run, fix the top 2 issues | Second person can run it; demo script rehearsed once |

Cut order if behind: FR-6 (already stretch) → FR-4 follow-up chat reduced to canned refine buttons → Scale tab becomes a static markdown panel with measured numbers.

## 13. Demo script (≈5 minutes)

1. **The problem in one sentence** — 200M documents, most of them scans, and a real underwriter question nobody can answer today. Show a scanned page (redacted) to make "no text layer" concrete.
2. **Ask** — type the Q1 question in English. Table appears. Point at attachment point, limit, currency, confidence.
3. **Trust** — click a row: page image + quoted sentence. "Every number has a page." Show a flagged row and why it's flagged.
4. **Analyse** — follow-up: sum limits by currency; ask the same question in Swedish.
5. **Scale** — Scale tab: measured seconds/tokens/cost per document from *this* run → extrapolate; explain extract-once/query-many and the four stages. Show the eval numbers (precision/recall vs our ground truth).
6. **What's next** — Q2/Q3 are new fields in the same schema; OCR + batch for the real archive; underwriter corrections feeding back.

## 14. Open questions

1. Confirm whether `ANTHROPIC_BASE_URL` in the environment points `claude` at a proxy — if so, ingestion latency and limits may differ from the test run.
2. Does the jury value Swedish UI labels, or is English UI with Swedish question support enough? (Assumed: English UI.)
3. Should the `Projects/` folder be treated purely as negatives, or is there a 4th use case behind it? (Assumed: negatives.)

## 15. Glossary

- **Attachment point / excess point** — the amount above which the excess policy starts to pay (the underlying limit or self-insured retention).
- **Limit** — the maximum the policy pays above the attachment point.
- **LH policy document** — If's policy schedule document ("LH" in the use-case description), the source for Q1.
- **Layer** — one slice of a programme, expressed as "X in excess of Y" (Q3, out of scope).
