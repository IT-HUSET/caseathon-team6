# Build plan — Policy Insight

Iteration plan for the 6-hour build. Companions: [docs/prd.md](docs/prd.md) says **what** to
build and how it is accepted; [docs/decisions.md](docs/decisions.md) says **why** the design is
what it is (`D1`…`D28`); this file says **in what order**, and **how we know each step worked**.

## How to use this file

- Work top to bottom. Each iteration ends in a **gate** — a small set of checks that must pass before the next iteration starts.
- Every check has an ID (`C0.1`, `C1.2`, …) and is either a command with an expected result or a specific observable. "It looks right" is not a check.
- A failed gate means **apply the cut rule for that iteration**, not "carry on and hope". The cut ladder is at the end.
- Tick boxes as you go and fill in the status log. The log is what you read from during the demo when someone asks "how do you know?".
- `uv` commands use `--system-certs`. `--native-tls` still works but is deprecated in the installed `uv` 0.12.13 and prints a warning on every call (D23).

**Timebox shape.** 6 hours to a live demo plus a runnable repo. Iterations 0–4 are the
critical path: they are the difference between a demo and a slideshow. Iterations 5–9 are all
individually cuttable, and the ladder at the end says in what order.

## Starting state (after merging through `0ea7ce9` "Also include aggregate sum")

The plan was written for an empty repository. It no longer is — **the pipeline has been built and
run end to end**, so most of this plan is now a verification checklist rather than a build order.

**The run (2026-09-11):** 19 documents, 226 pages, precision 1.00, recall 1.00 (tp 4, fp 0, fn 0,
tn 13), attachment 4/4, limit 4/4, 6 of 17 rows flagged, ≈$0.18/doc measured through the CLI,
p50 27 s/doc. `docs/demo-runbook.md` holds the performed demo.

**What that leaves.** Three things, in order of value:

1. **G3 is not yet demonstrated.** Quote verification (**D18**) is not in the build, so nothing checks that an evidence quote appears on the page it cites. A 1.00 eval score is compatible with correct numbers and invented sentences — see **D26**. This is the gap a jury will find, and `MIGRATIONS` (PRD F20) has made closing it cheaper than when it was assessed.
2. **The ~20 % scan share is unconfirmed** (**D28**) and now the largest lever in the cost model — it roughly halves the headline. Ten-minute question, six-figure consequence (C8.8).
3. **Two `?` ground-truth rows and 15 unaudited labels** (C3.6, C3.7) — the evidence *behind* the 1.00, not the 1.00 itself.
4. **Two arithmetic tidies**: the same production path is published at ≈$1.7M and ≈$2.3M (C8.9), and the measured row still carries a Batch discount (C8.7).

**No longer a problem.** The Scale tab used to show vision as cheaper than OCR; D28's scan share
fixed the ordering, so the uncorrected 1,500 tokens/page (C8.3) now understates a path we are not
recommending. Still worth correcting, no longer urgent.

Everything below is kept for traceability; ticked checks are satisfied by the build.

| Already on `main` | Effect on this plan |
|---|---|
| `ingest/` — rasteriser, `claude -p` wrapper, chunking, merge, extraction prompt, reparse | Iterations 1–2 become *adapt and verify*, not build |
| `index/db.py`, `index/schema.py` — SQLite layer + published query schema | Iteration 2's C2.1 (one schema definition) is largely satisfied — verify, don't rewrite |
| `query/` — translate, execute, chat + prompts | Iteration 5 and 7 substantially pre-built |
| `app.py`, `ui/evidence.py`, `ui/scale.py` | Iterations 5, 6, 8 have a shell to fill |
| `eval/ground_truth.csv` — all 19 documents labelled; `eval/run_eval.py` | **Iteration 3 done.** Outcome: 4 positives, 13 negatives, 2 `?` (either-accepted) |
| `tests/test_skeleton.py`, `pyproject.toml`, `uv.lock`, `README.md` with measured results | C9.1/C9.2 largely satisfied |
| `ANTHROPIC_BASE_URL` verified as the default endpoint, no proxy | **C0.2 answered** |
| `query_cache` + `normalise_question()` + `cached translation` badge (`148f78b`) | **Iteration 5's C5.5 satisfied** (**D17** implemented) |
| `detect_language()` + field glossary in chat prompts | **C5.3 / Iteration 7 satisfied** (**D15** amended) |
| `ui/evidence.py` shows the *value* each quote supports | **C6.1 strengthened** (**D19** amended) |
| `ui/scale.py` + `Scale` tab with three cost paths | **Iteration 8 built** — but see **D22**/**D27** on the figures |
| `docs/demo-runbook.md` | **Iteration 9's C9.3 has a script**; dry run still to be timed |
| `ea_us_restriction` + review trigger + prompt rule (`b8d5173`) | **D11 revised** — flagged rows 6/17 → 7/17; the trust beat is now `LP0000036557-30` |
| `index/db.py` `MIGRATIONS` (`b8d5173`) | New columns land without a re-ingest — lowers the cost of **D26** |
| `scan_share` slider + production cost path (`b8d5173`) | **D21/D22 revised**, **D28** added |
| `ea_limit_aggregate_amount` end to end (`0ea7ce9`) | **D10 revised** — aggregate exact-match 4/4, two correctly `null` |
| `MIGRATIONS` verified on a pre-migration database | **D26** is now hours, not risk (PRD F23) |
| `_dominant_model()` fix + regression test (local, uncommitted) | **D27**'s labelling mechanism works; 14 tests pass |

**The catch, and it is the first thing to settle:** the skeleton was written against the
**pre-review** PRD, so it implements the earlier schema — `excess_auto` as a single object, no
`page_text` table (so no quote verification), no `us_excluded`, three review-flag triggers
instead of five. The gap and the options are **D26**, which blocks the Iteration 2 gate. The
skeleton is also *ahead* of the PRD in one place: its extraction prompt already handles
"World Wide excluding USA/Canada" and introduced `limit_source` / `limit_evidence`, both now
merged into PRD §7.1.

## Tracks

Frozen schema (end of Iteration 2) is the only real coupling point. After that these run in
parallel. The header of the PRD says "solo/pair build" while the repository is
`caseathon-team6` — **settle this in Iteration 0** (C0.3), because a five-person team running
this sequentially wastes about half the time box.

| Track | Owns | Blocked by |
|---|---|---|
| A | Rasteriser, `claude -p` wrapper, ingestion, chunk merge | — |
| B | Blind ground truth, `eval/ground_truth.csv`, `run_eval.py` | nothing — pure document reading, starts at 0:00 |
| C | Streamlit shell, query translation, DSL validation, result table | frozen schema only (works off a fixture row until the index fills) |
| D | Evidence panel, quote verification, review flags | frozen schema + `page_text` |
| E | Scale tab, README, demo script | `ingest_metrics` shape only |

**If solo or pair:** run iterations strictly in order and expect to spend the cut ladder from
step 1 downwards. The honest solo target is Iterations 0–6 complete, 7–8 cut to static.

## Timeline

| Clock | Iteration | Milestone |
|---|---|---|
| −0:15–0:00 | 0 | Pre-flight gate — the build is viable at all |
| 0:00–0:45 | 1 | One document end-to-end into SQLite |
| 0:45–1:30 | 2 | Schema frozen; full ingestion running in background |
| 0:00–1:30 | 3 | Blind ground truth + eval harness (track B, parallel) |
| 1:30–2:30 | 4 | Extraction correct on the 9-doc iteration subset |
| 2:30–3:15 | 5 | Ask → table |
| 3:15–3:45 | 6 | Evidence panel + verification + review flags |
| 3:45–4:30 | 7 | Follow-up chat |
| 4:30–5:15 | 8 | Scale tab |
| 5:15–6:00 | 9 | README, dry run, fix top 2 issues |

---

# Iteration 0 — Pre-flight gate (−0:15 → 0:00)

**Goal.** Establish that the build is possible before spending time box on it. Every check here
kills or reshapes the project if it fails, so none of them belongs later.

**Do.** Nothing but the checks.

### Checks

- [ ] **C0.1 — `claude -p` accepts a page image and returns parseable JSON.** Now a **smoke test** rather than an open risk: C0.2 is answered and PRD F5 already establishes that page images read fine. Still run it — it costs 20 seconds and it is the one failure that would invalidate everything downstream (D2, D5).
  ```sh
  # render one page, then ask for JSON about it
  uv run --system-certs --with pypdfium2 --with pillow --no-project python -c "
  import pypdfium2 as p
  d=p.PdfDocument('docs/examples/excess auto liability/temp.lh.policy.2024.02.21.pdf')
  d[0].render(scale=1.5).to_pil().save('/tmp/p1.png'); print('rendered')"
  claude -p --output-format json 'Read /tmp/p1.png. Reply with only JSON: {"policy_no": string|null, "readable": true|false}'
  ```
  **Pass:** valid JSON comes back, `readable: true`, and `policy_no` is either a plausible `LP…` string or `null`.
- [x] **C0.2 — `ANTHROPIC_BASE_URL` is understood. ANSWERED 2026-09-11.** It is the default `https://api.anthropic.com`, not a proxy (PRD F4, **D5**). F6's timings are therefore representative and Pro-plan rate limits are the only throttle. No action — recorded here so nobody re-opens it.
- [ ] **C0.3 — Team size and track ownership settled.** Names against tracks A–E above, or an explicit "solo, sequential". **Pass:** the Tracks table has names in it.
- [ ] **C0.4 — Corpus clearance answered (D25).** Confirm the example PDFs may be sent to a personal Claude Pro subscription. **Pass:** a yes, or the redaction fallback in D25 is chosen. This is the one check whose failure changes the pipeline rather than the schedule, which is why it is not left to §14 of the PRD.
- [ ] **C0.5 — Toolchain present.** `uv --version` ≥ 0.12, `claude --version` responds, Python 3.13 resolvable (3.13.1 is present on this machine). The skeleton ships `pyproject.toml` and `uv.lock`, so this is now a check on the committed lockfile:
  ```sh
  uv run --system-certs python -c "import pypdfium2, PIL, streamlit; print('deps ok')"
  uv run --system-certs python -m pytest tests/ -q
  ```
  **Pass:** deps import and the skeleton's own tests pass before anyone changes them.
- [ ] **C0.6 — D26 decided: how to reconcile the skeleton with the revised schema.** Options and a recommendation are in **D26**. This is a team decision about someone else's hours, not an inference to make alone, and everything downstream keys off the answer. **Pass:** one of D26's three options is chosen and written into the status log.

### Gate 0

All six pass → start Iteration 1. C0.1 fails → stop and fix the transport; nothing downstream
matters. C0.4 fails → take the D25 redaction fallback before any ingestion.

---

# Iteration 1 — One document end-to-end (0:00 → 0:45)

**Goal.** The thinnest possible complete path: PDF → page PNGs → one `claude -p` call → parsed
JSON → SQLite row → readable back out. No chunking, no concurrency, no UI.

**Do.**
1. Repo skeleton, `pyproject.toml` (`requires-python = ">=3.13"`, `pypdfium2`, `pillow`, `streamlit`) — dependencies declared, never installed ad hoc (D23).
2. `ingest/raster.py` — PDF → `data/pages/<doc_id>/p<N>.png`, `doc_id` = content hash (D12).
3. `ingest/llm.py` — `claude -p --output-format json` wrapper returning `(parsed_json, metrics)`; strips code fences; records duration, tokens, cost **and model** (D22).
4. `ingest/db.py` — schema from PRD §7.2, created idempotently.
5. Run it on one 3-page scan.

### Checks

- [ ] **C1.1 — Round trip.** One document produces ≥1 page PNG, one `documents` row, one `policy_facts` row, and ≥1 `evidence` row.
  ```sh
  uv run --system-certs python -m ingest --only "temp.lh.policy.2025.10.14.pdf"
  uv run --system-certs python -c "
  import sqlite3; c=sqlite3.connect('data/index.sqlite')
  for t in ('documents','policy_facts','evidence','page_text','ingest_metrics'):
      print(t, c.execute(f'select count(*) from {t}').fetchone()[0])"
  ```
  **Pass:** every table is non-zero.
- [ ] **C1.2 — Metrics captured with the model name.** `select model, input_tokens, output_tokens, cost_usd from ingest_metrics` returns a non-null model string. Without this, the Scale tab cannot label its own numbers (D22) and Iteration 8 has nothing to build on.
- [ ] **C1.3 — Defensive parsing works.** Feed the parser a fenced-JSON string, a JSON-with-prose string, and a garbage string. **Pass:** first two parse, third raises the retry path rather than writing a partial row.
- [ ] **C1.4 — Rasterisation legibility decided, not defaulted (D2).** Render the smallest-print page at 1.5× and 2×, look at both, and record the choice in the status log. **Pass:** a scale is chosen *because you looked*. A misread digit in an attachment point is the one error that invalidates Q1, and vision tokens cap out at ~4,784/image either way, so this is a real decision with a cheap downside.
- [ ] **C1.5 — Idempotency.** Re-running the same command makes no new rows and completes in <5 s.

### Gate 1

C1.1, C1.2, C1.3, C1.5 pass. **If behind:** drop `page_text` from this iteration but not from
the build — it is needed by Iteration 6 and is explicitly not cuttable (D18).

---

# Iteration 2 — Freeze the schema, start the corpus (0:45 → 1:30)

**Goal.** Publish the extraction schema, make chunking and merge correct, and get all 19
documents ingesting in the background. **This iteration unblocks tracks C, D and E**, so the
freeze matters more than the ingestion finishing.

**Do.**
1. Extraction prompt implementing PRD §7.1 + the D11 geography rule + the `us_excluded` negative example ("worldwide excluding USA/Canada").
2. Chunking at ≤15 pages with the D4 merge rules — `excess_auto[]` concatenated and deduped, disagreements **kept and flagged**, not reconciled.
3. `--max-pages` applied from this first run (F10 — the 85-page document is 38% of all corpus pages).
4. Text-layer fast path for the two text PDFs (D3).
5. Concurrency 3, retry with backoff, then **launch the full run in the background** and move on.
6. **Announce the freeze.** Tracks C/D/E start now.

### Checks

- [ ] **C2.1 — Schema published in one place.** The field list the query translator is shown is imported from the same module the validator uses — not a second copy (D8, D13).
  ```sh
  grep -rn "SCHEMA_FIELDS\|FIELD_WHITELIST" --include=*.py . | head
  ```
  **Pass:** one definition, imported everywhere.
- [ ] **C2.2 — Merge rules exercised on the 85-page document.** Chunk it, confirm ≥2 chunks merged into one `policy_facts` row, `excess_auto` rows concatenated, and any chunk disagreement flagged rather than silently resolved.
- [ ] **C2.3 — `page_text` populated per page** for every ingested document; row count matches pages processed. This is Iteration 6's foundation (D18).
- [ ] **C2.4 — Text-layer path taken for exactly the two text PDFs** and for no others. `select path, input_path_kind from documents` — 2 rows `text`, the rest `image` (D3).
- [ ] **C2.5 — Full run launched** in the background with logging to a file, and it survives a transient CLI failure (kill one subprocess and watch the retry).
- [ ] **C2.6 — Schema freeze announced** and tracks C/D/E unblocked. **Pass:** someone other than track A has started.

### Gate 2

C2.1, C2.3, C2.6 pass and ingestion is running. **If behind:** reduce `--max-pages` further and
re-launch; a partial corpus still demos because the UI works off the index (§11). Do **not**
delay the freeze to perfect the prompt — Iteration 4 is where the prompt gets fixed.

---

# Iteration 3 — Blind ground truth + eval harness (track B, 0:00 → 1:30, parallel)

**Goal.** A ground truth that can contradict the system, produced without looking at the
system's output. Skipping it turns every later number into an assertion.

**Largely delivered by `0aa6b3b`.** `eval/ground_truth.csv` has all 19 documents with
attachment/limit amounts, currencies, pages, verbatim quotes, trap notes and a `labelled_by`
column, plus `eval/run_eval.py`. **Outcome: 4 positives, 13 negatives, 2 unresolved (`?`).**
Two things remain, and the first one blocks Gate 4.

**Do.**
1. **Settle the two `?` rows** — both 2022-06-08 documents, both inside `excess auto liability/`, both read twice (text layer *and* page images) with no excess auto cover found (PRD F11–F12). A third read by someone who has not seen the first two.
2. **Triage the 15 unverified rows** (PRD F14). Do not re-label all of them; eye-check only the negatives the system disagrees with, once Iteration 4 has run.
3. Add `us_excluded` to the CSV if D26 adopts it (**D11**).

### Checks

- [x] **C3.1 — All 19 documents labelled.** Done in `0aa6b3b`; verify with:
  ```sh
  uv run --system-certs python -c "
  import csv,collections; r=list(csv.DictReader(open('eval/ground_truth.csv')))
  print('rows',len(r)); print(collections.Counter(x['has_excess_auto_us'].strip().upper() for x in r))"
  ```
  **Pass:** 19 rows. Current state: 4 `Y`, 13 `N`, 2 `?`.
- [ ] **C3.6 — The two `?` rows are resolved** to `Y` or `N` by a third independent read. **Pass:** no `?` remains. Until then Gate 4's thresholds cannot be computed, and the rows are reported separately rather than counted as negatives — counting them as `N` would flatter precision on documents nobody has settled.
- [ ] **C3.7 — Provenance is visible in the eval output.** `run_eval.py` prints how many labels are `claude-assisted … unverified` alongside precision and recall (PRD F14). **Pass:** the count appears. An eval labelled by the same model family that extracts measures self-consistency on those rows, and the report should say so rather than implying independence.
- [ ] **C3.2 — Labels are blind.** `contributed_for` exists as its own column and is not used in any comparison in `run_eval.py`.
  ```sh
  grep -n "contributed_for" eval/run_eval.py
  ```
  **Pass:** appears only in reporting, never in a scoring expression (D20).
- [x] **C3.3 — The folder hypothesis is tested, not assumed. ANSWERED.** Positives outside `excess auto liability/`: **0**. Positives *inside* it that are not positives: **2** (the `?` rows). So the folder does not hide positives elsewhere — it over-states its own. Had it been used as the answer key, Gate 4 would have demanded recall on two documents that appear to carry no excess auto cover: an unreachable target. **D20** earned its keep in the direction nobody predicted.
- [ ] **C3.4 — `run_eval.py` runs green against a hand-made fixture** before the real index exists, so a failing score later means the *extraction* is wrong, not the harness.
- [ ] **C3.5 — Sample size stated.** The harness prints "n positives / n negatives — directional, not statistically significant" alongside precision and recall (D20).

### Gate 3

C3.1, C3.2, C3.4 pass (all satisfied by `0aa6b3b`) **and C3.6 resolves the two `?` rows**.
**Cannot be cut** — without it, G1 has no meaning and the Scale tab has no eval numbers to show.

---

# Iteration 4 — Get extraction right (1:30 → 2:30)

**Goal.** Extraction correct against the blind ground truth. This is the hour that decides
whether the demo is true.

**Iteration budget, stated because the timeline hides it.** A full 19-document re-ingest is
20–25 minutes, so this hour buys about **two full passes**. Therefore: iterate on a **9-document
subset** — the 6 in `excess auto liability/` plus the 3 hardest distractors (start with the
`Layers/` documents, per C3.3) — and re-run the full set **once**, at the end.

**Do.**
1. Run `run_eval.py`. Read the misses.
2. Fix the *prompt*, not the data. Replay from `raw_extractions` where the failure is parsing rather than reading (D12) — a 30-second fix instead of another 20 minutes of ingestion.
3. Re-run the subset. Repeat at most twice.
4. Full-corpus re-run once, at the end of the hour.

### Checks

- [x] **C4.1 — Recall 100% on the 4 labelled positives. ACHIEVED.** tp 4, fp 0, fn 0, tn 13 (PRD F15). The two `?` rows are scored either-accepted, so they cannot contribute a miss — say "four scored positives", not "all positives".
- [ ] **C4.2 — At most one false positive, and it is flagged.** The PRD's earlier wording ("precision = 100% *or* every false positive is flagged") allowed precision to fail without limit as long as rows carried a badge; the threshold is now a hard cap (§9.3).
- [ ] **C4.3 — Zero fabricated figures. NOT YET EVALUABLE.** This check requires `page_text` and the verification pass, which the build does not have (**D26**). Currently "no fabricated figures" rests on label agreement, which is a different claim: a 1.00 score is compatible with correct numbers and invented quotes. Blocked on D26 option 3.
  ```sh
  uv run --system-certs python -m eval.verify_quotes   # once page_text exists
  ```
- [ ] **C4.4 — `us_excluded` correct on every document that carries an exclusion clause.** The "worldwide excluding USA/Canada" family is the largest false-positive risk in the build (D11); getting it right is the difference between reading and skimming.
- [x] **C4.5 — Attachment/limit exact match ≥ 3/4. ACHIEVED 4/4 on attachment, per-occurrence limit and aggregate** (PRD F15, F21). Two aggregates are correctly `null` — an absent aggregate is a fact about the policy, not a gap (PRD F22). Still worth one eye-check that each limit's `limit_source` is right (PRD F13, **D10**): a correct number sourced from the wrong table passes this check while being the wrong answer.
- [ ] **C4.6 — Full-corpus re-run completed** after the last prompt change, so the index and the prompt actually correspond.

### Gate 4

C4.1, C4.2, C4.3 pass. **This gate does not get cut** — it is G1. If it fails, spend Iteration 5's
budget here and cut from the bottom of the ladder instead.

---

# Iteration 5 — Ask → table (2:30 → 3:15)

**Goal.** Type the Q1 question in English, get the result table.

**Do.**
1. Streamlit shell, tabs: Ask / Results / Evidence / Scale.
2. Question → validated JSON DSL (`filters[]`, `columns[]`, `group_by`/`aggregate`) → whitelist validation → compiled SQL (D13). **No model-authored SQL is executed.**
3. Translation cache keyed on normalised question text (D17).
4. Near-duplicate grouping by `policy_no` + period with a "2 related documents" marker (D16).
5. Off-schema questions get the refuse-and-list response (D14).

### Checks

- [ ] **C5.1 — The demo question returns exactly the ground-truth positive set**, with attachment point, limit, currency, confidence and page reference populated.
- [ ] **C5.2 — No SQL from the model.** Assert in code that the model's output is parsed as JSON and that any string containing `select`/`;`/`--` in a filter *value* position is rejected. **Pass:** a unit test feeds a SQL-injection-shaped question and the query is refused (D13).
- [x] **C5.3 — Swedish works. SATISFIED `148f78b`.** `detect_language()` covers this exact question in `tests/test_skeleton.py`, and the chat prompt is told which language to answer in rather than inferring it (D15).
- [ ] **C5.4 — Off-schema refusal.** *"Who is the broker?"* returns the "not indexed" response listing available fields — no invented column, no partial table (D14).
- [x] **C5.5 — Repeatability. SATISFIED `148f78b`.** `query_cache` keyed on `normalise_question()`; only validated translations are cached; a cached entry that no longer validates is dropped and re-translated; the UI shows a `cached translation` badge. Verify on the day by asking the demo question twice and watching for the badge (D17).
- [ ] **C5.6 — Near-duplicates grouped.** The two 2022-06-08 documents appear as one row with a related-documents marker, not two near-identical rows (D16, F11).
- [ ] **C5.7 — Latency.** Table answer ≤ 8 s end-to-end.

### Gate 5

C5.1, C5.2, C5.4 pass. **Cut rule:** if translation is fighting you, hard-code the Q1 query
behind a button and keep the DSL path for one working question. A working button beats a broken
text box, and C5.1 is what the demo needs.

---

# Iteration 6 — Evidence, verification, review flags (3:15 → 3:45)

**Goal.** Make G3 true rather than claimed. Click a row, see the page and the quote; see flags
where the system is unsure.

**Do.**
1. Evidence panel: page image at readable size, verbatim quote beside it, field name, confidence.
2. **Quote verification pass** — fuzzy-match every `evidence_quote` against `page_text` for the page it cites; set `quote_unverified` on mismatch (D18).
3. Review flags on all five triggers (FR-7): low confidence, missing quote, `extraction_failed`, `quote_unverified`, chunk disagreement.
4. Flagged rows visually distinct, sorted last, filterable *to*.

### Checks

- [ ] **C6.1 — Every positive row's panel shows the page the figure actually appears on**, with a quote visibly present on that page. Check by eye on all positives — there are only ~6.
- [ ] **C6.2 — Verification catches a corrupted quote.** Alter one stored `evidence_quote` so it no longer appears in its page transcript, re-run verification, confirm the row flags `quote_unverified`.
  ```sh
  uv run --system-certs python -c "
  import sqlite3; c=sqlite3.connect('data/index.sqlite')
  c.execute(\"update evidence set quote='NOT ON THIS PAGE AT ALL' where id=(select min(id) from evidence)\"); c.commit()"
  uv run --system-certs python -m ingest.verify_quotes
  # expect: 1 quote_unverified, and that row flagged in the UI
  ```
  **Pass:** flagged. Note this test is only meaningful *because* `page_text` exists — under the original three flag triggers it would have passed silently while testing nothing (D18).
- [x] **C6.3 — Flag count is plausible, not zero. SATISFIED.** **7 of 17** scored rows flagged: six negatives with low confidence on an *absence*, plus one positive whose US cover is scope-restricted (PRD F18, D11/D19). The added flag is a true positive that was previously presented unqualified — the best possible reason for a flag count to rise.
- [ ] **C6.4 — Nothing is silently hidden.** Flagged rows are present in the default table, sorted last — not filtered out.
- [ ] **C6.5 — The limit label derives from `ea_basis`, not a hardcoded string.** `ui/evidence.py` prints "per occurrence" as a literal (lines 52–53, 91) directly above `Basis: {ea_basis}` read from the document. All four current positives really are per-occurrence, so nothing is wrong today — but a schedule worded "any one claim" or "each and every loss" would have the panel assert one basis and display another, two lines apart, in the view whose entire job is showing what the document said. **Pass:** the label reads from `ea_basis` with a neutral fallback.

### Gate 6

C6.1, C6.2 pass. **Not cuttable** (D18): cutting verification would leave the UI looking
identical while converting a verified claim into an unverified one — the worst available cut.

---

# Iteration 7 — Follow-up chat (3:45 → 4:30)

**Goal.** Ask a second question about the rows on screen, with citations.

**Do.** Chat box below the table. Each turn sends current rows + evidence quotes + history +
message. Model answers from those rows only, cites `policy_no` and page per fact (D15).

### Checks

- [ ] **C7.1 — "Sum the limits by currency"** answers correctly for the demo set, and **says which rows it skipped** because only `limit_raw` exists (D10).
- [ ] **C7.2 — "Which of these has the highest attachment point?"** answers correctly with `policy_no` + page citation.
- [ ] **C7.3 — Out-of-scope question refused.** Ask something not in the rows ("what is the premium?") → says it is not in the result set rather than inventing (D15).
- [ ] **C7.4 — Latency** ≤ 15 s per turn.

### Gate 7

C7.1 and C7.3 pass. **Cut rule:** replace free chat with two canned refine buttons ("above EUR
10M", "sum by currency"). Keeps the analysis beat of the demo at a fraction of the risk.

---

# Iteration 8 — Scale tab (4:30 → 5:15)

**Goal.** The extract-once/query-many argument, backed by this run's own measurements.

**Do.**
1. From `ingest_metrics`: documents, pages, median/mean pages per doc, seconds per doc (p50/p95), tokens per doc, cost per doc.
2. **Label the measured model** and show the reprice to Sonnet 5 / Haiku 4.5 + Batch −50% as an explicit step (D22).
3. Extrapolation to 200M documents with editable assumptions; defaults from D22's envelope.
4. Eval numbers from Iteration 3, with the sample-size caveat (C3.5).
5. 3–5 bullets on the four stages (D21).

### Checks

- [x] **C8.1 — Every cost figure names its path. SATISFIED.** The tab shows three separately labelled rows: CLI-measured, vision-via-API, OCR+text (**D27**). Model prices come from `config.MODEL_PRICES_PER_MTOK`.
- [ ] **C8.2 — The reprice is visible as a step**, not a silent substitution. Unlabelled, measured and extrapolated sit ~4× apart, on the one slide whose purpose is trustworthy arithmetic.
- [ ] **C8.3 — Page-token figure re-baselined. OPEN, downgraded.** `tokens_per_page_image` is still `1_500`; the rasteriser emits 1224×1584 px, so `(w×h)/750` gives **~2,585**. It no longer changes the recommendation — D28's scan share makes the production path cheaper at any of these figures — so this is accuracy, not architecture. Settle it with one `count_tokens` call on a real page image; `ingest_metrics.input_tokens` cannot (5,747/page, carrying multi-turn overhead, PRD F16).
- [ ] **C8.8 — Confirm the ~20 % scan share with the case owner (D28).** The single largest lever in the cost model: it roughly halves the production-path headline, and nobody at If has been asked. **Pass:** a number from If, or the slider is demoed at both ends rather than presented at 20 %.
- [ ] **C8.9 — One published figure for the production path.** §10 says ≈$1.7M (8.0 pages/doc), the runbook says ≈$2.3M (11.9 measured) — both correct, published side by side (PRD F19). **Pass:** one number, with its pages/doc stated.
- [ ] **C8.7 — The measured row is shown undiscounted.** `ui/scale.py:71` multiplies the measured $0.18/doc by `(1 − batch_discount)`, producing the runbook's "$17.9M". That blends a harness-inflated measurement with a discount that applies to API list pricing — two errors in opposite directions (**D27**). **Pass:** the measured row reads ≈$36M and is labelled an upper bound; the API rows keep the discount.
- [ ] **C8.4 — Assumptions are editable** and the extrapolation updates live.
- [ ] **C8.5 — Renders in <1 s** from SQLite.
- [ ] **C8.6 — Eval numbers shown with the sample-size caveat.**

### Gate 8

C8.1 and C8.2 pass. **Cut rule:** a static markdown panel with the measured numbers and the
D22 table. The labelling requirement (C8.1) survives the cut — an unlabelled 4× discrepancy is
worse than no tab.

---

# Iteration 9 — Runnable + rehearsed (5:15 → 6:00)

**Goal.** Someone else can run it; the demo has been performed once before it is performed for
the jury.

**Do.**
1. `README.md`: prerequisites (Python 3.13, `uv`, `claude` CLI logged in), two commands, directory layout, how to add documents, known limitations, the data-handling note (D24) and the eval caveat.
2. Full demo dry-run against the clock, out loud.
3. Fix the top 2 issues the dry-run exposes. Nothing else.

### Checks

- [ ] **C9.1 — Clean-checkout reproduction.** On a fresh clone with the same prerequisites: `uv run --system-certs python -m ingest` then `uv run --system-certs streamlit run app.py` reaches the demo table. Best done by someone who did not write it.
- [ ] **C9.2 — README and runbook commands use `--system-certs`.** Both currently document `--native-tls`, which is deprecated in the installed `uv` 0.12.13 and prints a warning on every call (**D23**). Cosmetic, but it is a warning in the repo's own documented workflow, and the fix is a find-and-replace.
- [ ] **C9.3 — Dry-run completed inside 5 minutes**, out loud, following [docs/demo-runbook.md](docs/demo-runbook.md) (which covers all six beats of PRD §13 and has a "if something goes wrong" section). **Pass:** timed once, out loud. Written ≠ rehearsed.
- [ ] **C9.4 — Known limitations written down**: sample size, folder-label caveat, headless-CLI expedient, data handling (D5, D20, D24). The README covers provenance and cost honestly already; add the two that are missing — **quote verification is not implemented** (D26/G3) and the two `?` rows are either-accepted so they cannot fail (PRD F15). Volunteering the limits is what makes the 1.00 credible.
- [ ] **C9.6 — README provenance counts match `eval/ground_truth.csv`.** The README says 2 underwriter-verified / 3 eye-checked / 14 model-assisted; the `labelled_by` column says 2 / 2 / 15 (PRD F14b). **Pass:** they agree. A provenance claim its own data does not support is worse than a smaller honest number.
- [ ] **C9.5 — One flagged row exists and is rehearsed.** The demo shows a flag and explains *why* it flagged — the strongest trust moment available (D19).

### Gate 9

C9.1 and C9.3 pass. Ship.

---

# Cut ladder

Spend from the top when behind. Never from the bottom.

1. **FR-6 highlight boxes** — already a stretch; quote + page satisfies G3 (D18).
2. **Iteration 7 free chat** → two canned refine buttons (Gate 7 cut rule).
3. **Iteration 8 tab** → static markdown panel, cost figures still labelled (Gate 8 cut rule).
4. **Iteration 5 translation** → hard-coded Q1 query behind a button (Gate 5 cut rule).
5. **Corpus size** → lower `--max-pages`, ingest fewer documents. The UI works off the index, so a partial corpus still demos.

**Never cut:** Iteration 3 (blind ground truth — without it G1 is an assertion), Iteration 4
(extraction correctness — it *is* G1), Iteration 6 quote verification (D18 — cutting it leaves
the UI identical while making the central claim unverified).

**Where the remaining time goes, given the run is green.** Iterations 1–5 and 7–8 are built, so the
ladder is no longer about what to drop but what to add. In order:

1. **Quote verification** (**D26** option 3) — the only item that changes what the demo can honestly claim, and cheaper now that `MIGRATIONS` exists.
2. **Ask If about the scan share** (C8.8) — ten minutes, and it is the number the whole cost case rests on.
3. **One production-path figure** (C8.9) and the **undiscounted measured row** (C8.7) — minutes each, both things a jury would catch.
4. **The two `?` rows** (C3.6), then the README reconciliations (C9.2, C9.6), then the basis label (C6.5), then `tokens_per_page_image` (C8.3).

Note the reordering: C8.3 was second on this list and is now last, because D28 removed its
consequence. C8.8 took its place — the assumption underneath the number now matters more than the
number itself.

# Traceability

| PRD requirement | Iteration | Key checks |
|---|---|---|
| FR-1 Ingestion | 1, 2 | C1.1, C1.5, C2.2, C2.4 |
| FR-2 Extraction + evidence | 2, 4 | C2.1, C2.3, C4.3, C4.4 |
| FR-3 NL → table | 5 | C5.1, C5.2, C5.3, C5.4 |
| FR-4 Follow-up chat | 7 | C7.1, C7.2, C7.3 |
| FR-5 Evidence view | 6 | C6.1 |
| FR-6 Highlight (stretch) | — | cut ladder step 1 |
| FR-7 Confidence + flags | 6 | C6.2, C6.3, C6.4 |
| FR-8 Scale dashboard | 8 | C8.1, C8.2, C8.3 |
| FR-9 Runnable repo | 9 | C9.1, C9.2 |
| G1 Answer Q1 correctly | 3, 4 | C3.1, C4.1, C4.2 |
| G2 NL in, table out | 5 | C5.1, C5.3 |
| G3 Trust by construction | 6 | C6.1, C6.2 |
| G4 Scale backed by measurement | 8 | C8.1, C8.3 |
| G5 Runnable by someone else | 9 | C9.1 |

# Status log

Fill in as you go. This is what you read from when the jury asks "how do you know?".

| Iteration | Gate | Time | Checks failed | Cuts applied | Notes |
|---|---|---|---|---|---|
| 0 Pre-flight | ☐ | | | | D26 option chosen: ___ (C0.6) · rasterisation scale: ___ (C1.4) |
| 1 End-to-end | ☐ | | | | |
| 2 Schema frozen | ☐ | | | | freeze announced at: ___ |
| 3 Ground truth | ☐ | | | | positives outside Q1 folder: **0** (C3.3) · `?` rows resolved to: ___ (C3.6) |
| 4 Extraction | ☑ | | C4.3 blocked (D26) | | **precision 1.00 / recall 1.00, attachment 4/4, limit 4/4** |
| 5 Ask → table | ☑ | | | | cache + badge live (D17) |
| 6 Evidence | ◑ | | C6.2 blocked (D26), C6.5 open | | rows flagged: **7 / 17** (one scope-restricted positive) |
| 7 Chat | ☑ | | | | language detection + glossary (D15) |
| 8 Scale | ◑ | | C8.3, C8.7, C8.8, C8.9 open | | measured **$0.18/doc** (Sonnet 5) · production path ≈$1.7–2.3M |
| 9 Ship | ☐ | | | | |
