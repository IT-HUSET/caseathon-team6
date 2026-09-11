# PRD — Policy Insight: turning If Industrial's document archive into a queryable knowledge source

| | |
|---|---|
| Status | Draft v6 — 2026-09-11 (merged through `0ea7ce9`: aggregate limit captured end to end; schema migrations verified against a pre-migration database) |
| Owner | Mathias Rönnblom (solo/pair build) |
| Time box | 6 hours to a live demo + runnable repo |
| Scope | Use case Q1 only (excess auto liability, US) on the 19 example policies |
| Companions | [decisions.md](decisions.md) — architecture decisions and rationale (`D1`…`D28`) · [../plan.md](../plan.md) — iteration plan with checks · [demo-runbook.md](demo-runbook.md) — the demo as actually performed |

**How these three documents divide the work.** This PRD states **what** must be true and how it
is accepted. [decisions.md](decisions.md) states **why** the design is what it is, including the
alternatives rejected — architecture rationale lives there and nowhere else, referenced from here
as `(D7)`. [../plan.md](../plan.md) states **in what order** it gets built and **how each step is
verified**. If you are about to add a paragraph of rationale below, it belongs in decisions.md.

---

## 1. Problem

If Industrial holds ~200 million documents (policies, wordings, schedules, correspondence) in many formats and languages. Valuable facts — cover types, geography, attachment points, limits, layer structures — are locked inside free text — most often in text-based PDFs, with a long tail of scanned documents that have no text layer at all. Existing metadata is not sufficient to answer portfolio questions such as *"which of our liability policies carry excess auto cover in the US, and at what attachment point and limit?"* Today that question means an underwriter opening documents one by one.

The caseathon asks for a working prototype that shows how such an archive becomes an **active, trustworthy knowledge source**: natural-language search over content, analysis/aggregation, format-agnostic handling, and results whose sources are explicit — designed so that the approach plausibly scales to 200M documents, not just a demo set.

## 2. Goals and non-goals

### Goals (must be true at the end of the 6 hours)

1. **G1 — Answer Q1 correctly on the example set.** For the 19 example policies, list every policy with excess auto liability cover in the United States, with attachment point (excess point) and limit, currency, and the page + quoted text each value came from. "Correctly" is measured against ground truth labelled blind from document content, not against the folder a document sits in (§9, F9).
2. **G2 — Natural-language in, table out.** An underwriter types a question in plain English (or Swedish); the system returns a result table, not prose, with follow-up chat over that result set.
3. **G3 — Trust by construction, not by assertion.** Every extracted value is traceable to a page image and a quoted snippet; **each quote is verified against a stored transcript of the page it cites** (FR-2), so "every number has a page" is a checked property rather than the model's word for it. Values carry a confidence level, and low-confidence or unverifiable values are visibly flagged for review.
4. **G4 — Scale story backed by measurement.** The architecture is *extract-once, query-many*; a dashboard shows measured per-document time and token cost from this run and extrapolates to 200M documents under stated assumptions — **with the model behind each figure named, and the repricing from the measured model to the extrapolated one shown as an explicit step** (FR-8, **D22**).
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

The findings are observations about the corpus and the machine; the consequences are what we decided
in response, argued in full in [decisions.md](decisions.md).

| # | Finding | Consequence |
|---|---|---|
| F1 | **17 of the 19 example PDFs have no text layer** (scans); only the two 2022-06-08 Danfoss files are text PDFs. **The example set is assumed *not* representative**: the real archive is taken to be mostly text-based PDFs, working assumption ~20 % scans (**D28**). | The prototype reads page images for every document, because scans are the path that has to work. At scale the text layer is the cheap default and OCR is paid only on the scanned share (**D21**, **D22**). |
| F2 | Documents are 2–85 pages (median 8; 226 pages in total); mixed languages (EN, DA, FI, SV observed); personal/company identifiers partly redacted (black boxes). | Chunked page processing; extraction must tolerate `null` policyholder. |
| F3 | Semi-structured header on page 1 (Policy no. `LP…`, Client no. `LC…`, period, print date) followed by free-text cover descriptions. | Header fields are reliable anchors; cover facts need reading, not regex. |
| F4 | No Anthropic API key or `ant` CLI on the build machine; only the `claude` CLI under a Claude Code Pro subscription (OAuth login). `ANTHROPIC_BASE_URL` is set but points at the default `https://api.anthropic.com` — no proxy, so the measured timings in F6 are representative and Pro-plan rate limits are the only throttle. | LLM calls go through `claude -p` (headless). Zero marginal cost, but rate-limited and not a production pattern. |
| F5 | `claude -p` cannot read PDFs directly on this machine (needs poppler). It reads **PNG page images** fine. | Rasterise PDFs in Python (`pypdfium2` + `pillow`), pass page PNGs to Claude. Page images are also needed by the UI (G3), so this is not extra work. |
| F6 | Measured: 3-page scan → correct structured JSON with page-level evidence quote in ~18 s, ~$0.03 API-equivalent — **model unrecorded for this early measurement**, i.e. ~$0.01/page. Note the *ingestion* path runs on **Sonnet 5** (`config.MODEL`, passed via `--model`) — established only after a bug that recorded the auxiliary Haiku call for every run was fixed (**D27**). | 19 docs ≈ 226 pages ≈ 20–25 min sequential ingestion; still inside the time box with 3 workers. The extrapolation in **D22** reprices this to Sonnet/Haiku and must say so explicitly. |
| F7 | `uv` works only with `--native-tls` on this network; project `settings.json` denies `pip install`, `uv add`, `uv pip`. | Dependencies declared once in `pyproject.toml`; run everything via `uv run --native-tls`. |
| F8 | Ground truth for Q1 does not exist. | Manual labelling of the 19 docs (positives + attachment/limit) is a task inside the 6 hours (§9). |
| F9 | **The folder names are not an answer key.** The use-case brief asks contributors for “15–20 documents per use case” as documents *to search through*; a folder records which use case a document was contributed **for**, not a verified per-question label. `Layers/` is the likeliest source of further Q1 positives — a layer is literally “X in excess of Y”, the same structure as an excess auto attachment point. | Ground truth must be labelled **blind** from document content, folder names ignored (§9). A correct extraction in `Layers/` must not be scored as a false positive. |
| F10 | One document (`Layers/temp.lh.policy.2019.01.21.pdf`, 85 pages) is **38 % of all corpus pages**. | It alone is ~6 chunks and dominates wall-clock and rate-limit budget. Cap it with `--max-pages` from the very first run, not as a fallback. |
| F11 | The two text PDFs (`excess auto liability/temp.lh.policy.2022.06.08.pdf` and `_2.pdf`) extract 7,945 vs 7,941 characters over 9 pages each — near-identical, and both sit in the Q1 folder. **Resolved by labelling: they are a duplicate/variant print of the same policy** (`LP0000045733-23`, same period), not two layers of one programme. | File-hash idempotency will not dedupe them. Group as a duplicate, not as "related layers" (FR-3, **D16**). |
| F12 | **Blind labelling of all 19 documents (`eval/ground_truth.csv`) found 4 positives, not 6.** The two documents in F11 are labelled `?`: two independent reads (text layer *and* page images) found no explicit excess auto cover in either, despite both sitting in the `excess auto liability/` folder. | The folder over-states the positive set. Had the folder been used as the answer key, §9's thresholds would have demanded recall on two documents that appear to carry no excess auto cover at all — an unreachable target, chased for hours. This is **D20** earning its keep, in the opposite direction from the one predicted. |
| F13 | The limit for excess auto cover frequently has **no separate sublimit**, in which case it is the policy's overall/total sum insured — printed in a sum-insured table on a **different page** from the attachment point. | One evidence page per excess-auto entry is not enough: the limit needs its own page + quote (`limit_evidence`) and a `limit_source` marker. Reflected in §7.1. |
| F14 | Of the 19 ground-truth rows, **15 are marked `claude-assisted (batch read, unverified)`**; 2 are `human` and 2 are eye-checked. | An eval labelled by the same model family that does the extracting measures self-consistency, not correctness on those rows. The checked rows are the positives; the 15 negatives are not. Cheapest fix in the time box: eye-check only the negatives the system disagrees with. |
| F14b | **The README and the CSV disagree on provenance.** `README.md` reports "2 verified by an underwriter, 3 with the decisive page checked by eye, 14 negatives from a model-assisted read"; the `labelled_by` column in `eval/ground_truth.csv` reads 2 `human`, 2 eye-checked, 15 unverified. | One row's provenance is claimed but not recorded. Reconcile before quoting either figure to a jury — a provenance claim that its own data does not support is worse than a lower number. |
| F15 | **The pipeline ran end to end on 2026-09-11** (`148f78b`): 19 documents, 226 pages ingested. Eval: **precision 1.00, recall 1.00** (tp 4, fp 0, fn 0, tn 13), attachment point 4/4, limit 4/4, 6 of 17 scored rows flagged *Needs review*. | G1 is met on the labelled set. Note the two `?` rows are scored "either answer accepted", so they cannot contribute a miss — the headline 1.00/1.00 rests on 4 positives and 13 negatives, of which 13 are model-labelled (F14). State it that way rather than as a bare 100 %. |
| F16 | Measured ingestion cost is **≈$0.18/doc API-equivalent through the CLI**, against **≈$0.02/doc** estimated for the same work on the API — a ~9× gap attributable to Claude Code's per-call prompt overhead. | The CLI measurement **bounds API cost from above; it is not a proxy for it**. Any extrapolation that starts from $0.18 is measuring the harness, not the workload. This is **D22**'s labelling rule earning its keep a second time; see the reconciliation there. |
| F18 | **`LP0000036557-30` carries US excess auto cover that is restricted** — "No excess auto cover in USA is given, except for people travelling from abroad" (p. 8). The cover exists, the attachment point is real, and presenting it as a clean fact would mislead. | A boolean cannot express this. `ea_us_restriction` stores the restriction **verbatim** and puts the row on the review list (**D11**, revised). Flagged rows moved 6/17 → 7/17. |
| F19 | The production cost path is published with **two different headline figures**: §10 says ≈$1.7 M, `docs/demo-runbook.md` says ≈$2.3 M. | Both are arithmetically correct — §10 uses the 8.0 pages/doc config default, the runbook reflects the Scale tab seeded with the measured 11.9 (F17). Pick one and state its pages/doc, or a jury comparing the two documents finds an inconsistency nobody intended. |
| F21 | **Sum-insured rows carry two figures.** `LP0000043203-21`'s limit evidence reads *"TOTAL Sum Insured USD 10,000,000 20,000,000"* — per occurrence **and** aggregate on one row. With a single limit field the second figure was silently dropped. | `ea_limit_aggregate_amount` captures it (**D10**, revised). Re-run: aggregate exact-match **4/4**. |
| F22 | On two of the four positives the General Liability row has an **empty** aggregate cell while Products Liability alongside it shows `50,000,000/50,000,000`. | The tempting wrong answer sits on the same page. `null` is the correct label, and the extraction prompt names both failure modes explicitly: do not copy the per-occurrence figure, and do not borrow the aggregate from another row. The README states these blanks are correct rather than leaving a jury to read them as misses. |
| F23 | `MIGRATIONS` **verified empirically**: a database created before either new column was opened with the current code — `ea_us_restriction` and `ea_limit_aggregate_amount` were both added in sequence and the existing row survived intact. | Schema evolution no longer costs a re-ingest, which is what makes the outstanding **D26** work affordable. |
| F20 | `index/db.py` now carries a `MIGRATIONS` list applied on `connect()`. | Schema evolution no longer means re-ingesting: a new column lands on existing databases automatically. Makes the outstanding schema work (**D26**) materially cheaper than when it was assessed. |
| F17 | Measured **mean 11.9 pages/doc** (median 8), p50 27 s/doc, over 226 pages. | Supersedes the 8 pages/doc the cost model assumed. The Scale tab already seeds its pages/doc input from this measurement (`app.py:164`), which is why its totals are higher than earlier drafts of §10. |

## 5. Solution overview

The shape of the system. The reasoning behind it — extract-once/query-many (**D1**), page images as the universal input (**D2**), `claude -p` as transport (**D5**), SQLite (**D6**), Streamlit (**D7**) — is in [decisions.md](decisions.md).

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
| `ingest/` | Walk `docs/examples/**/*.pdf`, rasterise pages, call Claude per page-chunk, merge, validate, **verify every evidence quote against the page transcript**, write to SQLite + `data/pages/<doc_id>/p<N>.png`; record timings/tokens. | `pypdfium2`, `pillow`, `subprocess` → `claude -p --output-format json` |
| `index` | `data/index.sqlite` — documents, extracted fields, evidence, **page transcripts**, ingestion metrics. | `sqlite3` (stdlib) |
| `query/` | Translate a question into a validated JSON query (filters, columns, aggregation) over the known schema; execute; produce a one-line explanation. Follow-up chat over the current result set. | `claude -p` with a strict system prompt and JSON output |
| `app.py` | Streamlit UI: Ask, Results, Evidence, Scale tabs. | `streamlit` |

## 6. Functional requirements

Each requirement has acceptance criteria (AC). "Must" = required for the demo; "Should" = do if time permits; "Stretch" = only if everything else is green.

### FR-1 Ingestion of heterogeneous PDFs — Must
- Ingests every PDF under a configurable root. Scans go through the page-image path.
- **One path in the prototype:** text PDFs and scans both go through the page-image path. The example set is 17/19 scans, so that is the path that must work; the text-layer fast path is a production optimisation, not a prototype shortcut (**D3**, revised; **D21** Stage 1).
- Pages rasterised at a scale that keeps small print legible. Start at 1.5× (~1,200 px wide) and **validate legibility at 2× on the smallest-print page before locking the setting** (**D2**; plan.md check C1.4).
- Documents longer than 15 pages are processed in chunks of ≤15 pages. Merge rules (**D4**):
  - header fields (`policy_no`, `client_no`, period, language, …): first non-null wins;
  - `excess_auto[]` entries: concatenate across chunks, then dedupe on (attachment amount, attachment currency, limit amount, limit currency, basis); differing entries are **kept, not reconciled**, and the document is flagged for review;
  - `field_evidence`: keep the highest-confidence entry per field, retaining the others in the `evidence` table.
- `--max-pages` is set from the first run, not kept as a fallback (F10).
- Idempotent: re-running skips documents whose file hash is already indexed; `--force` re-ingests; raw model responses retained for replay without re-reading pages (**D12**). File-hash identity does **not** catch the near-duplicate pair in F11 — see FR-3.
- Concurrency configurable (default 3 parallel `claude -p` processes) with retry on transient CLI failure.
- **AC:** `uv run --native-tls python -m ingest` indexes all 19 documents with zero unhandled exceptions; each document has ≥1 page image and one `documents` row; a rerun completes in <5 s.

### FR-2 Structured extraction with evidence — Must
- Claude returns a JSON object per chunk conforming to the schema in §7. Every non-null cover fact carries `evidence_page` (1-based, absolute page number within the document) and `evidence_quote` (verbatim text as read from the page), plus `confidence ∈ {high, medium, low}`.
- **Each chunk also returns a plain-text transcript per page** (`page_text[]`). Every `evidence_quote` is fuzzy-matched against the transcript of its claimed page at ingestion; a mismatch sets `quote_unverified` (FR-7). This is what makes G3 a checked property rather than a claim — rationale and consequences: **D18**.
- Output is parsed defensively (strip code fences, validate types); a chunk that fails validation is retried once, then recorded as `extraction_failed` for that chunk — never silently dropped.
- The prompt instructs: do not infer *unstated* facts; if the document does not state a value, return `null`; quote in the document's original language; report monetary values with currency and the exact figure as written, and also verbatim in `limit_raw` / `attachment_raw`.
- **Geographical scope is the one permitted derivation**, expressed as an explicit prompt rule: a stated worldwide scope includes the US (`geography_us: true`) *unless* the wording excludes it. `"worldwide excluding USA/Canada"` and variants are supplied to the model as a named negative example. `geography_us` carries an evidence quote either way.
- **A restriction is not an exclusion.** Where US excess auto cover exists but is narrower than the general cover, `has_excess_auto_liability` stays `true`, the US attachment point is still reported, and the restriction goes **verbatim** into `us_scope_restriction` — never buried in `notes`, because that field is what puts the row on the review list (F18). Rationale: **D11**.
- **AC:** Against the blind ground truth of all 19 documents (§9), `has_excess_auto_liability`, `geography_us` and `us_scope_restriction` are correct, and attachment/limit match on true positives. No document — in any folder — carries a US excess-auto figure that is not present in its text. A document in `Layers/`, `Projects/` or `Offshore Projects/` that genuinely carries US excess auto cover counts as a **true** positive (F9).

### FR-3 Natural-language query → result table — Must
- The user types a free-text question. Claude translates it into a JSON query against a **published, fixed schema** (§7): `filters[]` (field, op, value), `columns[]`, optional `group_by`/`aggregate`. The app validates the JSON against the schema whitelist and compiles it to SQL itself. **No model-authored SQL is ever executed** (**D13**).
- The table shows the requested columns plus, always: `policy_no`, `confidence`, and a "source" link per evidenced value.
- If the question cannot be mapped to the schema, the app says so and lists what it *can* answer (the schema's fields) rather than hallucinating a table (**D14**).
- Translations are cached by normalised question text (**D17**).
- Questions in Swedish and English both work.
- **Near-duplicate rule (F11):** rows sharing `policy_no` + period are grouped into one row with a "2 related documents" marker, expandable to both sources (**D16**).
- **AC:** The demo question in §3 returns exactly the ground-truth positive set with attachment point and limit populated. *"Hur många policyer har excess auto-täckning i USA?"* returns a count. An unmappable question (e.g. *"who is the broker?"*) yields the explicit "not indexed" response.

### FR-4 Follow-up chat over the result set — Must
- A chat box below the table. Each turn sends: the current result rows (with evidence quotes) + conversation history + the user's message. Claude answers in prose, citing `policy_no` and page for every fact, and may return an updated filter to refine the table.
- Claude is instructed to answer only from the supplied rows; if the answer is not in them, say so (**D15**). Aggregations must state which rows were skipped because only the verbatim figure exists (**D10**).
- **AC:** *"Sum the limits by currency"* and *"which of these has the highest attachment point?"* are answered correctly for the demo result set, each with citations.

### FR-5 Evidence view — Must
- Clicking a row (or a value's source link) opens the evidence panel: the page image at readable size, the verbatim `evidence_quote` displayed next to it, the field name, and confidence. Multiple evidenced fields for the same document are listed with their own page/quote.
- **AC:** For every positive Q1 row in the demo, the panel shows the page on which the attachment point actually appears and a quote that is visibly present on that page.

### FR-6 Highlight on page image — Stretch
- Ask Claude to also return a normalised bounding box (`x0,y0,x1,y1` in 0–1) for each quote; if present, draw a translucent rectangle on the page image. Boxes are advisory — the quote remains the source of truth. If not implemented, the UI simply shows quote + page (still satisfies G3).

### FR-7 Confidence and review flags — Must
- Each extracted value has a confidence level from the model. Rows are flagged **"Needs review"** when any of the following holds:
  1. any displayed value is `low` confidence;
  2. a non-null value has no evidence quote;
  3. the document had any `extraction_failed` chunk;
  4. **`quote_unverified` — the evidence quote does not fuzzy-match the transcript of the page it claims (FR-2);**
  5. chunks disagreed on an `excess_auto[]` entry (FR-1 merge rule);
  6. `ea_us_restriction` is non-null — the US cover exists but is narrower than the headline (F18).
- Trigger 4 is what makes G3 a checked property (**D18**). Nothing is silently dropped or filtered out (**D19**).
- Flagged rows are visually distinct and sort to the bottom by default; a toggle shows only flagged rows.
- **AC:** Corrupting one stored `evidence_quote` so it no longer appears in that page's transcript causes the row to be flagged `quote_unverified` on the next verification pass (plan.md check C6.2).

### FR-8 Scale & cost dashboard — Must
- A **Scale** tab showing, from the actual ingestion run: documents, pages, median/mean pages per doc, seconds per doc (p50/p95), input/output tokens per doc, API-equivalent cost per doc (from `claude -p`'s `total_cost_usd`).
- **Every cost figure on the tab is labelled with the model that produced it**, and the reprice from the measured Opus-class model to Sonnet 5 / Haiku 4.5 + Batch −50 % appears as an explicit step, not a silent substitution (**D22**).
- Extrapolation table to 200M documents under editable assumptions (avg pages/doc, model price per 1M tokens, batch discount, share of corpus that passes a cheap pre-filter). Defaults from the cost envelope in **D22**.
- A short explanation panel (3–5 bullets) of the extract-once/query-many argument (**D1**) and the four stages of the scale-out pipeline (**D21**).
- Eval numbers from §9, carrying the sample-size caveat (**D20**).
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
  "product_line": "liability",
  "cover_summary": ["General Liability", "Product Liability", "Recall"],
  "geography_scope": "World Wide",
  "geography_us": true,
  "has_excess_auto_liability": true,
  "excess_auto": [
    {
      "attachment_point_amount": 1000000,
      "attachment_point_currency": "USD",
      "attachment_raw": "USD 1,000,000",
      "limit_amount": 25000000,
      "limit_currency": "EUR",
      "limit_raw": "EUR 25,000,000 any one occurrence",
      "limit_is_unlimited": false,
      "limit_source": "auto sublimit",
      "limit_evidence": {"evidence_page": 3, "evidence_quote": "TOTAL Sum Insured …", "confidence": "high"},
      "us_scope_restriction": null,
      "basis": "per occurrence",
      "limit_aggregate_amount": 50000000,
      "notes": "applies to owned/hired/non-owned autos in USA",
      "evidence_page": 8,
      "evidence_quote": "The insurance covers … in excess of USD 1,000,000 …",
      "confidence": "high"
    }
  ],
  "field_evidence": {
    "geography_us": {"evidence_page": 2, "evidence_quote": "Geographical scope: World Wide", "confidence": "high"},
    "has_excess_auto_liability": {"evidence_page": 8, "evidence_quote": "…", "confidence": "high"}
  },
  "page_text": [
    {"page": 8, "text": "… full plain-text transcript of page 8 as read …"}
  ],
  "offshore_indicators": null,
  "layer": null
}
```

Field rules — stated in the prompt as prose, never as a placeholder pseudo-value *inside* the
JSON example (a pipe-separated `"liability | property | marine | other"` gets echoed back
verbatim often enough to matter):

- `product_line` — one of `liability`, `property`, `marine`, `other`.
- `excess_auto` is a **list**; merge and disagreement handling in FR-1. Rationale: **D9**.
- `us_scope_restriction` holds, **verbatim**, any restriction narrowing the US excess auto cover ("no cover in USA except for people travelling from abroad", "non-owned vehicles only"). `null` when unrestricted. A non-null value is a review trigger (FR-7), because cover that exists but is narrower than the headline is an underwriter call, not a fact. Stored as `ea_us_restriction`. Rationale: **D11**.
- `limit_raw` / `attachment_raw` hold the figure verbatim; `limit_is_unlimited` distinguishes "stated as unlimited" from "not stated". Rationale: **D10**.
- `limit_amount` is always the **per occurrence** figure; `limit_aggregate_amount` holds the aggregate per policy period from the same row, `null` when none is stated (F21). No separate currency — the aggregate takes the limit's. The prompt forbids copying the per-occurrence figure into it and forbids borrowing an aggregate from a different row (F22). Rationale: **D10**.
- `limit_source` is `auto sublimit` or `total sum insured`, and `limit_evidence` carries its **own** page and quote. Where the excess auto cover has no separate sublimit, the limit is the policy's overall sum insured, printed in a table on a different page from the attachment point (F13) — so a single evidence page per entry is insufficient. Rationale: **D10**.
- `page_text` is the per-page transcript required by FR-2, and the basis of quote verification. Rationale: **D18**.
- `offshore_indicators` and `layer` are reserved (always `null` here) so the schema is stable when Q2/Q3 are added. Rationale: **D8**.

### 7.2 SQLite tables

- `documents(doc_id PK, path, file_hash, pages, ingested_at, status, error, input_path_kind)` — `doc_id` is the first 16 hex chars of the SHA-256 of the file bytes (**D12**); `input_path_kind` records `text` or `image` (**D3**).
- `policy_facts(doc_id PK FK, policy_no, client_no, policyholder, period_start, period_end, language, product_line, geography_scope, geography_us, has_excess_auto, ea_us_restriction, needs_review, review_reasons_json)` — one row per document; excess-auto figures live in their own table (**D9**). New columns arrive via `MIGRATIONS` rather than a re-ingest (F20).
- `excess_auto(id PK, doc_id FK, attachment_amount, attachment_currency, attachment_raw, limit_amount, limit_aggregate_amount, limit_currency, limit_raw, limit_is_unlimited, limit_source, basis, notes, confidence, chunk_index)` — the limit's own page and quote go in `evidence` as `excess_auto.<id>.limit` (F13). New columns arrive through `MIGRATIONS` (F23).
- `evidence(id PK, doc_id FK, field, page, quote, confidence, quote_verified, bbox_json NULL)` — `field` may address an `excess_auto` row as `excess_auto.<id>.<field>`.
- `page_text(doc_id FK, page, text, PRIMARY KEY(doc_id, page))` — the per-page transcript from FR-2; the basis of quote verification (**D18**).
- `ingest_metrics(doc_id FK, chunk_index, pages_in_chunk, duration_ms, input_tokens, output_tokens, cost_usd, num_turns, model)` — `model` is recorded per call so the Scale tab can label and reprice what it measured (FR-8).
- `related_documents(doc_id FK, related_doc_id FK, reason)` — near-duplicate / same-programme grouping (F11, **D16**).
- `raw_extractions(doc_id FK, chunk_index, json)` — kept for debugging and re-processing without re-reading pages.

## 8. Non-functional requirements

| Area | Requirement |
|---|---|
| Query latency | Table answer ≤ 8 s end-to-end (one `claude -p` translation call + SQLite). Follow-up chat ≤ 15 s. |
| Ingestion throughput | Full 19-document run (226 pages, `--max-pages` applied to the 85-page outlier) completes in ≤ 25 min with 3 workers; must degrade gracefully (backoff) on rate limits. Stated as a whole-run budget, not docs/min, so that it follows from F6 rather than contradicting it. |
| Determinism | Query translation runs with a fixed system prompt and schema, and translations are **cached by normalised question text**, so a repeated question is identical by construction. Verified by one spot-check per demo question (**D17**). |
| Safety of model output | Model never produces SQL; only whitelisted fields/ops (**D13**). Evidence quotes are displayed as text, never rendered as HTML. |
| Data residency | Everything stays local except page content sent to Claude via the CLI (**D24**). Documented in README. Note the open question **D25**. |
| Observability | Every CLI call logs duration, tokens, cost, exit status to `ingest_metrics` / a query log. |

## 9. Evaluation and acceptance

1. **Blind ground-truth labelling — done.** `eval/ground_truth.csv` holds all 19 documents with `has_excess_auto_us`, attachment point/currency/page/quote, limit/currency/page/quote, notes and `labelled_by`. Outcome: **4 positives, 13 negatives, 2 unresolved (`?`)** — see F11, F12, F14.
   Remaining work on it, in priority order: (a) settle the two `?` rows, since the acceptance thresholds below cannot be computed while they are open; (b) eye-check any negative the system disagrees with, because 15 of 19 rows are unverified model output (F14).
   **Labels come from reading the document, not from the folder it sits in (F9, D20).** The folder is recorded in a separate `contributed_for` column so the two can be compared, but it is never used in scoring. The expected distribution (6 positives in the Q1 folder, 13 distractors elsewhere) is a *hypothesis to be checked* (plan.md check C3.3), not the key.
   Sample size and provenance are stated in the README and on the Scale tab: with 4 positives, 13 negatives and 2 unresolved — and 15 of 19 labels unverified (F14) — precision and recall are directional indicators, not statistically meaningful figures.
2. **Metrics reported in README and on the Scale tab:** precision and recall for "policy has US excess auto cover"; exact-match rate for attachment point and limit among true positives; share of rows flagged "Needs review".
3. **Acceptance thresholds for the demo:** recall = 100 % on the **4 labelled positives**; **at most one false positive, and it must be flagged**; zero fabricated figures (**D18**); attachment/limit exact match ≥ **3/4** of true positives, with any miss flagged. The two `?` rows are excluded from scoring and reported separately — not silently counted as negatives, which would flatter the score.

   **Achieved on 2026-09-11 (F15, updated in `b8d5173`):** precision 1.00, recall 1.00 (tp 4, fp 0, fn 0, tn 13), attachment 4/4, limit (per occurrence) 4/4, **aggregate 4/4** — two correctly `null` (F22) — **7 of 17** scored rows flagged — six negatives with low confidence on an *absence*, plus one positive whose US cover is scope-restricted (F18). Every threshold met **except** the "verifies against its page transcript" clause, which cannot yet be evaluated: quote verification (**D18**) is not implemented in the current build — see **D26**. Until it is, "zero fabricated figures" rests on the labelled comparison, not on a check that each quote appears on the page it cites.

   How to state this honestly to a jury: *four positives, thirteen negatives, two undecided; perfect agreement with the labels; thirteen of those labels are model-assisted rather than audited.* A bare "100 %" on 19 documents invites the question the caveat already answers.
4. A tiny `eval/run_eval.py` compares index vs ground truth so the numbers are reproducible, not hand-typed.

## 10. Scaling to 200 million documents

**Moved.** The design argument and the cost envelope now live in [decisions.md](decisions.md):

- **D1** — extract once, query many: why query cost does not grow with corpus size.
- **D21** — the four-stage scale-out path: metadata triage → **get text once** (text layer free, OCR only the scanned share) → small model batched → index → feedback loop.
- **D22** — the cost envelope for 200M documents, the per-page token figure, and why every dollar amount is labelled with the model that produced it.
- **D28** — the ~20 % scan-share assumption that the production path rests on: what it changes, and why it needs confirming.

Note the two published figures for the production path disagree (F19); reconcile before quoting either.

What this PRD still requires of it: FR-8 (the Scale tab renders it from measured data) and G4
(the argument is backed by this run's own measurements). The numbers the tab defaults to are
D22's table.

## 11. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Pro-plan rate limits stall ingestion mid-build | **High** | 226 page images on a Pro plan is the main threat to the build, and "start early" does not help once a 5-hour window is hit. Mitigations applied from the first run: `--max-pages` on the 85-page outlier (F10); text-layer fast path (**D3**); prompt iteration on a 9-document subset (plan.md Iteration 4); raw responses cached for replay (**D12**); low concurrency. The UI works off the index, so a partial corpus still demos. |
| `claude -p` output not clean JSON | Medium | Fence-stripping + schema validation + one retry; `raw_extractions` kept so prompts can be fixed and re-parsed without re-reading pages. |
| Attachment point vs limit vs deductible confusion on complex wordings | Medium | Prompt with definitions and a worked example; require the quote; confidence flag; ground truth catches it. |
| Long documents (85 pages) blow time budget | Low | Chunking; `--max-pages` switch for the demo run. |
| Redactions remove policyholder → grouping impossible | Certain | Not needed for Q1; use `client_no` as the grouping key if ever needed. |
| Time: UI polish eats extraction correctness | High | Gate order in [../plan.md](../plan.md) is fixed, and the cut ladder spends from the top: correctness before chrome. |
| Headless-CLI dependence questioned by jury | Medium | State it plainly: dev-time expedient with a one-module blast radius; the same prompt/schema runs on the API or Batch API unchanged (**D5**, **D21** Stage 2). |
| **Sending real policy documents through a consumer subscription** | Medium | Real, only partly redacted documents go through a personal Claude Pro subscription (F4, **D24**). Answer before the jury asks: dev-time expedient; production runs on the Anthropic API under commercial terms, archive never leaving If's control. Stated in the README, not only here. **Clearance is an open decision (D25) and a pre-flight gate (plan.md check C0.4).** |
| Near-duplicate documents read as double counting in the demo table | Medium | F11: the two text PDFs are near-identical and both are Q1 positives. Grouped into one row with a "related documents" marker (FR-3, **D16**). |
| Evaluation scores a correct extraction as wrong | Medium | F9: folder names are not labels. Blind labelling (§9.1, **D20**) plus a `contributed_for` column so any discrepancy is visible rather than silent. |

## 12. Six-hour plan

**Moved** to [../plan.md](../plan.md), which carries the milestone timeline, the five parallel
tracks, the iteration budget, per-step verification checks, the gates between iterations, and the
cut ladder. Two things worth restating here because they are scope statements rather than
scheduling:

- **The cut order is fixed: correctness before chrome.** Full ladder in plan.md.
- **Three things are never cut** — blind ground truth (§9, **D20**), extraction correctness (§G1), and quote verification (FR-7 trigger 4, **D18**). Cutting the last one would leave the UI looking identical while turning a verified claim into an unverified one.

## 13. Demo script (≈5 minutes)

**Implemented as [demo-runbook.md](demo-runbook.md)** (`148f78b`, revised in `b8d5173`), which
carries the actual tab-by-tab script, the four real positive rows with their figures, the exact
follow-up questions, the Scale-tab talking points and a "if something goes wrong" section. The
trust beat is now `LP0000036557-30` — the flagged row whose US cover is restricted to travellers
from abroad (F18), which demonstrates the system declining to present a real attachment point as
a clean fact. The beats below are the
spec it satisfies; the runbook is what you read on the day.


1. **The problem in one sentence** — 200M documents, most of them scans, and a real underwriter question nobody can answer today. Show a scanned page (redacted) to make "no text layer" concrete.
2. **Ask** — type the Q1 question in English. Table appears. Point at attachment point, limit, currency, confidence.
3. **Trust** — click a row: page image + quoted sentence. "Every number has a page." Show a flagged row and why it's flagged.
4. **Analyse** — follow-up: sum limits by currency; ask the same question in Swedish.
5. **Scale** — Scale tab: measured seconds/tokens/cost per document from *this* run → extrapolate; explain extract-once/query-many and the four stages. Show the eval numbers (precision/recall vs our ground truth).
6. **What's next** — Q2/Q3 are new fields in the same schema; OCR + batch for the real archive; underwriter corrections feeding back.

## 14. Open questions

### Pre-flight blockers — resolve before hour 0, not during the build

These are **Iteration 0** in [../plan.md](../plan.md), with the exact commands that answer them.
Summarised here because each one kills or reshapes the project if the answer is bad:

1. **Who is building this?** The header says "solo/pair build"; the repository is `caseathon-team6` with git history authored by more than one person. A five-person team running the plan sequentially wastes about half the time box (plan.md C0.3, Tracks).
2. **Is the example set cleared for transmission to a consumer Claude subscription?** Open decision **D25**, pre-flight check C0.4. If the answer is no, the fallback is chosen before ingestion starts, not after 226 pages have been sent.

### Genuine open questions

3. **Do the two `?` rows in `eval/ground_truth.csv` carry excess auto cover or not?** Two independent reads found none in either, despite both sitting in the `excess auto liability/` folder (F11, F12). Currently scored as "either answer accepted", which unblocks §9.3 but means those two documents cannot contribute a miss. An underwriter's ruling would convert the 1.00/1.00 from *four scored positives* into *six*, and is the single highest-value 10 minutes available before the demo.
4. **Should the 15 unverified ground-truth rows be eye-checked before the demo?** They are model-labelled (F14), so precision on the negative set measures self-consistency rather than correctness. With the run now green (F15) the cheapest check has changed shape: there are **no disagreements left to triage**, so pick 2–3 negatives at random and confirm them by eye — a clean sample beats an exhaustive pass nobody has time for.
5. **Reconcile the provenance counts between `README.md` and `eval/ground_truth.csv`** (F14b) before either number is quoted.
6. **Is ~20 % the right scan share for the real archive?** (**D28**, F1.) This is now the single largest lever in the cost model — it moves the production path from ≈$4.8 M to ≈$1.7–2.3 M — and it is a working assumption nobody at If has confirmed. One question to the case owner settles it; until then the Scale tab slider is the honest way to present it.
7. **Reconcile §10's ≈$1.7 M with the runbook's ≈$2.3 M** (F19) — same model, different pages/doc.
8. Does the jury value Swedish UI labels, or is English UI with Swedish question support enough? (Assumed: English UI — and the chat now detects Swedish questions and answers in Swedish, `query/chat.py`.)
9. Is the `Projects/` folder a 4th use case, or a distractor set? Note this does not gate the evaluation — under blind labelling (§9.1, F9) every document is labelled on its content regardless of folder, so a Q1 positive in `Projects/` is simply a positive. (Assumed: contributed as distractors.)

### Resolved

- **`ANTHROPIC_BASE_URL`** — checked 2026-09-11: the default `https://api.anthropic.com`, not a proxy. F6's timings are therefore representative and Pro-plan rate limits are the only throttle (F4). Plan check C0.2 is answered; C0.1 remains as a cheap smoke test rather than an open risk.
- **The two near-identical 2022-06-08 documents (F11)** — a duplicate/variant print of the same policy (`LP0000045733-23`, same period), not two layers of one programme. The FR-3 grouping marker reads "duplicate" (**D16**). Note this is a *separate* question from whether they carry excess auto cover, which is open above.
- **Does the approach work at all on this corpus?** Yes — measured, not asserted: 19 documents ingested, precision and recall 1.00 against the labelled set, attachment and limit exact on 4/4 (F15). The remaining questions above are about the strength of the *evidence for* that number, not about whether the pipeline runs.

## 15. Glossary

- **Attachment point / excess point** — the amount above which the excess policy starts to pay (the underlying limit or self-insured retention).
- **Limit** — the maximum the policy pays above the attachment point.
- **LH policy document** — If's policy schedule document ("LH" in the use-case description), the source for Q1.
- **Layer** — one slice of a programme, expressed as "X in excess of Y" (Q3, out of scope).
