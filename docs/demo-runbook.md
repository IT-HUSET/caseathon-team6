# Demo runbook — Policy Insight (≈5 min)

Every answer below was produced by the app against the real index on 2026-09-11. If the app shows
something different, the index has changed — re-run `uv run --native-tls python eval/run_eval.py` before presenting.

## Before you start

```bash
uv run --native-tls streamlit run app.py
```

- Open the **Evidence** tab once and select `LP0000043203-21` so its page image is cached.
- The first translation of a new question takes ~20–25 s (`claude -p` process start). The questions below
  are pre-warmed in the translation cache and return instantly; anything improvised will show the spinner.
- Have `docs/examples/excess auto liability/temp.lh.policy.2025.12.12.pdf` open in a PDF viewer at page 5.

## 1. The problem (30 s)

Show page 5 of the PDF in the viewer: a scan, no text layer, the auto clause buried under a sub-heading on
page 5 of 8. Say: *200 million of these; most are text PDFs, but a long tail are scans like this one — 17 of our
19 examples have no text layer at all — and nobody can answer a portfolio question without opening them one by
one. The pipeline has to cope with the worst case, so the prototype reads every page as an image.*

## 2. Ask (60 s) — tab **Ask**

Question (pre-filled):

> Find all liability policies with excess auto cover in the United States. Show attachment point and limit.

Expected table — 4 rows, one flagged ⚠️ (LP0000036557-30, see step 3):

| Policy | Period | Attachment | Limit per occurrence | Limit aggregate |
|---|---|---|---|---|
| LP0000017479-37 | 2023-07-01 → 2024-06-30 | USD 10,000,000 | USD 50,000,000 | — (none stated) |
| LP0000028602-58 | 2025-10-01 → 2026-09-30 | USD 2,000,000 | USD 50,000,000 | — (none stated) |
| LP0000036557-30 | 2021-06-01 → 2022-05-31 | USD 1,000,000 | SEK 360,000,000 | SEK 360,000,000 |
| LP0000043203-21 | 2025-12-01 → 2026-11-30 | USD 5,000,000 | USD 10,000,000 | USD 20,000,000 |

The empty aggregates are correct, not misses: on those two schedules the General Liability row has a blank
aggregate cell (only Products Liability carries 50M/50M) and the extractor was told not to borrow it.

Point at: policyholder is empty because it is *redacted in the scans*, not missed. Expand
**Query (validated JSON → SQL)**: the model never writes SQL — it fills a whitelisted filter and the app
builds the SQL. Say: *that is why an answer costs cents regardless of corpus size.*

## 3. Trust (60 s) — select the LP0000043203-21 row → tab **Evidence**

Four evidenced values, each with page, confidence, verbatim quote and the page image:

- Excess auto: attachment point **USD 5,000,000 — p. 5** — quote *"…that part of the loss that exceeds USD 5 000 000 in the USA…"*
- Excess auto: limit **USD 10,000,000 per occurrence / USD 20,000,000 aggregate — p. 3** — quote *"TOTAL Sum Insured USD 10,000,000 20,000,000"*
- Cover applies in the US: Yes — p. 5; Has excess auto liability: Yes — p. 5

Say: *every number has a page. The limit comes from the sum-insured table because the auto extension has no
sublimit of its own — the app says so rather than guessing.*

Then pick `LP0000036557-30` — the ⚠️ row. It is flagged **Needs review** with the reason *"US excess auto cover is
restricted: No excess auto cover in USA is given, except for people travelling from abroad…"* (p. 8). The system
lists it *with* the restriction, and puts it on the review list instead of either dropping it or presenting the
USD 1,000,000 attachment as a clean fact — an underwriter decides.

Flagged example: in the Evidence document picker choose `LP0000068085-1` (a transport policy). It is a
correct negative but flagged **Needs review** because the model gave no quote for the absence — the flag is
conservative by design.

## 4. Analyse (45 s) — back to **Ask**, follow-up chat box

> Sum the limits by currency.

Expected: **USD 110,000,000** (LP0000017479-37 p. 3 50M + LP0000028602-58 p. 5 50M + LP0000043203-21 p. 3 10M)
and **SEK 360,000,000** (LP0000036557-30 p. 4). Each figure cited with policy number and page.

> Which of these has the highest attachment point?

Expected: **LP0000017479-37, USD 10,000,000 (p. 4)**, with the other three listed for comparison.

Optional, if there is time (chat answers take ~25–30 s, uncached by design):

> Which of these have a limit above EUR 10M?

Expected: it says there is no exchange rate in the data, lists all four limits with citations, names the three
that are clearly above (USD 50M, USD 50M, SEK 360M) and flags **LP0000043203-21 (USD 10M)** as borderline and
unconfirmable without a rate. Say: *it tells you what it doesn't know instead of inventing a conversion.*
Ask this in the **chat box**, not the Ask box — as a table query it filters literally on `currency = EUR` and
returns nothing.

Swedish, as a new question in the Ask box:

> Hur många policyer har excess auto-täckning i USA?

Expected: **4**, explanation in Swedish.

Optional — show the refusal path:

> Who is the broker on each policy?

Expected: *"Can't answer that from the index: The index has no broker field"* plus the list of fields it can answer.

## 5. Scale (60 s) — tab **Scale**

Read the measured numbers first (they come from `ingest_metrics`, not from a slide): 19 documents, 226 pages,
p50 27 s/doc, ≈ $0.18/doc API-equivalent through the CLI. Then the extrapolation rows:

- Measured path × 200 M docs ≈ $17.9 M — *honest, but an upper bound: every page read as an image because the
  examples are 17/19 scans, plus Claude Code's prompt overhead.*
- Prototype path (every page as an image) via the API ≈ $4.0 M.
- Production path ≈ $2.3 M: text PDFs give up their text layer for free, only the scanned 20 % is OCR'd
  (≈ $0.7 M), then text-only extraction (≈ $1.6 M) — *and text + layout gives exact highlight boxes.*

Drag **Share of archive that is scanned** to 1.0 to show the old assumption: OCR alone becomes ≈ $3.6 M. Then
move **Share passing Stage 0 triage** to 0.2: everything divides by five. Say: *the archive is read once; queries
never re-read it. Throughput is a batch/parallelism question, not an architecture question.*

Close with the eval line: **precision 1.00, recall 1.00, attachment 4/4, limit 4/4, aggregate 4/4** against a labelled
ground truth (`eval/ground_truth.csv`), reproducible with one command.

## 6. What's next (20 s)

Q2 (offshore) and Q3 (layers) are new fields in the same extraction schema — `offshore_indicators` and
`layer` are already reserved. The 85-page layered property policy and the five offshore project policies are
already in the index as negatives, waiting for those fields.

## If something goes wrong

- Translation spinner > 30 s: Pro-plan rate limit. Re-ask one of the cached questions above.
- Table empty: check the **Index** tab shows 19 documents; if not, `uv run --native-tls python -m ingest`.
- Page image missing: `data/pages/<doc_id>/` was cleaned — `python -m ingest --dry-run --force --only <date>` re-renders without Claude.
