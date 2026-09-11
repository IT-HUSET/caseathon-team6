# Architecture decisions — Policy Insight

Companion to [prd.md](prd.md). The PRD states **what** the prototype must do and how it is
accepted; this file states **what we decided and why**, including the alternatives we rejected.
[../plan.md](../plan.md) states the order we build it in.

Every decision has an ID (`D1`…`D28`). The PRD and the plan reference these IDs instead of
repeating rationale, so there is exactly one place where a design argument lives. If you are
about to argue with the design during the build, argue with the entry here — and if you win,
change the entry rather than the code alone.

**Status legend** — `Accepted`: in force. `Accepted (expedient)`: in force for this prototype
only, with the production answer stated. `Provisional`: accepted but resting on a check that
has not yet passed (see plan.md). `Open`: not yet decided; blocking or near-blocking.

## Index

| ID | Decision | Status | PRD |
|---|---|---|---|
| **Architecture & pipeline** | | | |
| D1 | Extract once, query many | Accepted | §5, G4 |
| D2 | Page images are the universal input | Accepted (expedient) | F5, FR-1 |
| D3 | ~~Text-layer fast path in the prototype~~ → **reversed**: one path in the prototype, fast path is production | Superseded | FR-1, D21 |
| D4 | Chunk at ≤15 pages with explicit merge rules | Accepted | FR-1 |
| D5 | `claude -p` headless CLI as the LLM transport | Accepted (expedient) | F4 |
| D6 | SQLite as the index | Accepted | §5, §7.2 |
| D7 | Streamlit as the UI | Accepted | §5 |
| **Extraction & schema** | | | |
| D8 | One fixed published schema; Q2/Q3 fields reserved and null | Accepted | §7.1 |
| D9 | `excess_auto` is a list, not an object | Accepted | §7.1 |
| D10 | Verbatim figures stored alongside parsed numbers (+ `limit_aggregate_amount`) | Accepted — revised | §7.1, F21 |
| D11 | Geographical scope is rule-based; **`us_scope_restriction` holds restrictions verbatim** (replaces `us_excluded`) | Accepted — revised | FR-2, F18 |
| D12 | `doc_id` is a content hash; raw extractions retained | Accepted | §7.2, FR-1 |
| **Query & UI** | | | |
| D13 | The model emits a validated filter DSL, never SQL | Accepted | FR-3, §8 |
| D14 | Refuse and explain rather than answer off-schema | Accepted | FR-3 |
| D15 | Follow-up chat answers only from supplied rows (+ language detection, field glossary) | Accepted | FR-4 |
| D16 | Near-duplicate documents are grouped, not dropped (resolved: duplicate, not layers) | Accepted | FR-3, F11 |
| D17 | Query translations cached by normalised question text | Accepted — **implemented** | §8 |
| **Trust** | | | |
| D18 | Evidence is a page plus a quote **verified against a stored transcript** | Accepted | G3, FR-2, FR-7 |
| D19 | Confidence and review flags are surfaced, never auto-hidden (+ evidence shows the value it supports) | Accepted | FR-7 |
| **Evaluation** | | | |
| D20 | Ground truth is labelled blind of folder names | Accepted | §9, F9 |
| **Scale** | | | |
| D21 | The scale-out path is **get-text-once** (text layer free, OCR on the scanned share), then a small model batched | Accepted — revised | §10 |
| D22 | Cost figures are labelled by model; measured ≠ extrapolated (reconciled with the built tab) | Accepted | FR-8, §10 |
| D27 | Three cost figures, three labels: CLI-measured, API-modelled, OCR-modelled | Accepted — **model labelling fixed in code** | FR-8, F16 |
| **Build environment** | | | |
| D23 | Dependencies declared in `pyproject.toml`, run through `uv` | Accepted | F7 |
| D24 | Everything local except page content sent to Claude | Accepted (expedient) | §8 |
| **Open** | | | |
| D25 | Whether the example corpus may be sent to a consumer subscription | **Open — blocking** | §11, §14 |
| D26 | Reconcile the committed skeleton with the revised schema | **Open — G3 not yet demonstrated** | §7, plan.md |
| D28 | The archive is assumed ~20 % scanned — load-bearing and unconfirmed | Accepted (working assumption) | F1, §14 |

---

## A. Architecture & pipeline

### D1 — Extract once, query many

**Context.** The archive is ~200M documents. Any design that reads documents *at query time*
has a cost and latency profile that grows with corpus size, which makes the demo a toy no
matter how good it looks on 19 files.

**Decision.** LLM reading cost is paid **once per document, at ingestion**, and produces a
structured, evidenced record. Questions are answered against that index. The LLM at query time
only translates the question (D13) and reasons over a handful of already-retrieved rows (D15).

**Why not the alternatives.**

| Alternative | Rejected because |
|---|---|
| RAG over page chunks at query time | Every question re-reads documents; cost and latency grow with corpus size, and aggregate questions ("sum limits by currency") are exactly what retrieval is worst at. |
| Full-text search only | The facts are not stated in a searchable canonical form — "in excess of USD 1,000,000" needs reading, not matching (F3). |
| Read-on-demand with a cache | Same as RAG for the cold path, and the first portfolio question is always cold. |

**Consequences.**
- Adding a new question type may require re-extraction, but only **per document**, never per corpus.
- The index schema (D8) becomes the contract between ingestion and query; freezing it early is on the critical path (plan.md, Iteration 2).
- The scale argument is an arithmetic argument rather than a hand-wave (D21, D22).

**Revisit when** questions start arriving that the schema cannot express faster than the schema can be extended — then add the vector + BM25 "unknown question" path from D21 Stage 3.

### D2 — Page images are the universal input

**Context.** 17 of 19 example PDFs have no text layer (F1), and `claude -p` on the build
machine cannot read PDFs directly (F5, needs poppler).

**Decision.** Rasterise every PDF page to PNG with `pypdfium2` + `pillow` and send page images
to the model. Start at 1.5× (~1,200 px wide).

**Why not the alternatives.** A dedicated OCR service is the right production answer and is
Stage 1 of D21 — it is not available on the build machine inside the time box. Installing
poppler to pass PDFs through directly would not help: the scans have no text to extract.

**Consequences.**
- OCR/vision is the main path, not a fallback, so extraction quality is bounded by image legibility. A misread digit in an attachment point is the single error that invalidates Q1, which is why the rasterisation scale is a checked decision and not a default (plan.md, C1.4).
- Page images are needed by the evidence view (D18) anyway, so this is not wasted work.
- Vision tokens dominate ingestion cost, and they are **not** cheap: Sonnet 5 and Opus 5 are high-resolution vision models (up to 2,576 px on the long edge, up to ~4,784 tokens per image). See D22 — this is where the original cost model went wrong.

**Revisit when** moving off the prototype: Stage 1 of D21 replaces this with OCR-once.

### D3 — Text-layer fast path as a deliberate exception

**Context.** D2 argues for one input path for all documents, which is the right
maintainability instinct. But two of the 19 documents *do* have text layers (F1) — and both are
in the Q1 positive folder, i.e. among the documents whose correctness matters most.

**Decision.** Where a page has an extractable text layer, send the text instead of the image.
Page images are still rendered for the UI either way.

**Why not "one path only".** The no-branching rule is a maintainability argument, and it loses
here to a rate-limit argument: Pro-plan quota is the primary threat to the build (§11), and
this branch costs about ten lines while removing two of the most important documents from the
vision budget entirely. Accepting one branch to protect the demo's most load-bearing documents
is the right trade at a 6-hour scale.

---

**REVERSED in `b8d5173`. The prototype keeps one path; the fast path moves to production (D21 Stage 1).**

Two things changed the balance, and both point the same way:

1. **Scans are now the minority case, not the norm (D28).** The archive is assumed ~20 % scanned. A prototype whose cheap path is the *common* production case and whose expensive path is the *rare* one demonstrates the wrong half. Reading every page as an image proves the hard case works; the text layer is the easy case that needs no proof.
2. **The rate-limit argument expired.** It was sized for a build that had not run. The full corpus has since ingested without trouble (PRD F15) — 226 pages, no quota wall. A branch justified by a risk that did not materialise is just a branch.

The two documents it would have protected are, on top of that, the two `?` rows — near-duplicate
prints whose excess auto status is still unsettled (PRD F11–F12). It was the weakest possible case
for an exception.

**Consequences.** Ingestion keeps one code path, which is simpler than the two this entry
originally accepted. The text-layer optimisation is not lost — it is Stage 1 of D21, where it does
far more work (it is what makes the production path cheap at all). Mathias's call, and the right
one.

### D4 — Chunk at ≤15 pages with explicit merge rules

**Context.** Documents run 2–85 pages (F2), and one 85-page document is 38% of all corpus
pages (F10). A whole document does not reliably fit one call at usable image resolution.

**Decision.** Process in chunks of ≤15 pages and merge per document, with the merge rules
stated rather than left to implementation accident:

- header fields (`policy_no`, `client_no`, period, language, …): first non-null wins;
- `excess_auto[]` entries: concatenate, then dedupe on (attachment amount+currency, limit amount+currency, basis); **differing entries are kept, not reconciled**, and the document is flagged for review (D19);
- `field_evidence`: keep the highest-confidence entry per field, retaining the others.

**Why the rules are written down.** With a single `excess_auto` object the merge was undefined:
if chunk 1 and chunk 6 of the 85-page document each returned a figure, one silently won. Silent
resolution of contradictory evidence is the worst possible behaviour for a system whose entire
claim is traceability — hence "kept, not reconciled" (and see D9).

**Consequences.** A document can legitimately produce several `excess_auto` rows. The UI must
handle that, and disagreement becomes a visible review flag rather than a coin flip.

### D5 — `claude -p` headless CLI as the LLM transport

**Context.** No Anthropic API key and no `ant` CLI on the build machine; only the `claude` CLI
under a Claude Code Pro subscription (F4).

**Decision.** Drive the model through `claude -p --output-format json` via `subprocess`.

**Why not the alternatives.** There is no API key to use the SDK with, and obtaining one is not
inside the time box. Mocking the model would remove the only interesting part of the prototype.

**Consequences.**
- Zero marginal cost, but **rate-limited** — the main build risk (§11), and the reason for D3, `--max-pages` and subset iteration in plan.md. Confirmed 2026-09-11: `ANTHROPIC_BASE_URL` is the default `https://api.anthropic.com`, no proxy, so Pro-plan limits are the *only* throttle and F6's timings are representative (PRD F4).
- No temperature or seed control, which is why determinism is handled by caching (D17) rather than by sampling settings.
- The measured cost figures come from Claude Code's default Opus-class model, which is **not** the model the extrapolation prices (D22).
- Everything above the transport — prompt, schema, parsing, merge — is unchanged on the API or Batch API. This is the honest answer to "why a CLI?": it is a dev-time expedient with a one-file blast radius, and D21 Stage 2 is the same prompt on the Batch API.

**Revisit when** an API key exists. Replacing this is a single module (`ingest/llm.py`).

### D6 — SQLite as the index

**Context.** The prototype needs a queryable store for ~19 documents and a few hundred
evidence rows, with zero setup cost and no service to run during a demo.

**Decision.** `data/index.sqlite`, stdlib `sqlite3`, schema in PRD §7.2.

**Why not the alternatives.** Postgres or DuckDB buys nothing at this size and costs setup time
and a demo failure mode. Parquet/DuckDB would be the natural next step at 10⁶–10⁸ rows, and
D21 Stage 3 says so; the SQL surface barely changes.

**Consequences.** No concurrent writers, so ingestion workers serialise writes through one
connection. The filter DSL (D13) compiles to SQLite SQL, which is the dialect most portable to
whatever replaces it.

### D7 — Streamlit as the UI

**Context.** Four views needed (Ask, Results, Evidence, Scale) in roughly 2 hours of the time
box, by Python developers, including image display and a chat box.

**Decision.** Streamlit, single `app.py`.

**Why not the alternatives.** A React/FastAPI split doubles the surface and adds a build step
for no demo benefit. A notebook is not demoable to a jury. Gradio is comparable but weaker at
tables, which are the core of G2.

**Consequences.** Re-run-on-interaction means the result set and chat history live in
`st.session_state`; anything expensive must be cached. UI polish has a low ceiling — acceptable,
since the cut order puts correctness above chrome.

---

## B. Extraction & schema

### D8 — One fixed published schema; Q2/Q3 fields reserved and null

**Context.** The case has three questions; the prototype answers one (Q1). The credible claim
is not "we built Q1" but "Q2 and Q3 are fields, not rebuilds".

**Decision.** A single extraction schema (PRD §7.1) covering Q1, with `offshore_indicators` and
`layer` present and always `null`. The schema is **published** — the query translator (D13) is
shown the same field list the UI validates against.

**Consequences.** The Q2/Q3 story is demonstrable by pointing at the schema rather than
asserted verbally. Freezing the schema is the coupling point for parallel work (plan.md
Iteration 2), and changing it after that invalidates the index.

### D9 — `excess_auto` is a list, not an object

**Context.** A single object could not represent a policy stating more than one excess auto
section, and made chunk merging undefined (D4). Separately, the case's Q3 is about layers of the
same risk — "X in excess of Y" — so multiple excess structures per document are expected, not
exotic.

**Decision.** `excess_auto` is an array of entries, each carrying its own evidence, confidence
and originating chunk.

**Consequences.** `policy_facts` holds one row per document while `excess_auto` is a child
table (§7.2). The result table may show several rows per document, which the near-duplicate and
grouping rules (D16) must account for.

### D10 — Verbatim figures stored alongside parsed numbers

**Context.** The use case asks for "the attachment point and **possible** limit". Limits are
sometimes unstated, sometimes stated as unlimited, and sometimes carried only in the underlying
policy. An integer-only field collapses all three into a `null` indistinguishable from a failed
read — and "we could not read it" and "the policy does not say" are very different answers to an
underwriter.

**Decision.** Store `attachment_raw` / `limit_raw` (verbatim, as printed) next to the parsed
numbers, plus `limit_is_unlimited`, plus a separate `aggregate_amount` because `basis` is
single-valued and cannot express a policy carrying both a per-occurrence and an aggregate limit.

**Amended after labelling (PRD F13).** Reading the documents turned up a rule the schema did not
cover: the excess auto cover frequently has **no separate sublimit**, in which case the limit is
the policy's overall/total sum insured — printed in a sum-insured table on a **different page**
from the attachment point. So the limit needs its own evidence (`limit_evidence`: page + quote +
confidence) and a `limit_source` marker (`auto sublimit` | `total sum insured`). One evidence page
per excess-auto entry is not enough. This came from the skeleton's extraction prompt
(`ingest/prompts/extraction.md`) and is merged into PRD §7.1.

**Amended again in `0ea7ce9` — the aggregate limit, and a narrowing I did not anticipate.**

This entry argued for a separate aggregate field on the grounds that `basis` is single-valued and
cannot carry both a per-occurrence and an aggregate limit. Running the pipeline produced the
evidence: `LP0000043203-21`'s limit quote is *"TOTAL Sum Insured USD 10,000,000 20,000,000"* — both
figures on one table row, the second silently discarded (PRD F21). It is now
`ea_limit_aggregate_amount`, threaded through DB, validator, merge, prompts, UI and eval.

Two things about his implementation are better than what this entry proposed:

- **No `aggregate_currency`.** I specified one; he takes the aggregate in the limit's currency. A sum-insured row states one currency for both cells, so a separate field would be a column that is either redundant or filled by guesswork — and a guessed currency on a money figure is worse than no field. Deliberate narrowing, not an omission.
- **The prompt names both failure modes.** "Do not copy the per-occurrence figure into it" and "do not take the aggregate from a different row (e.g. Products Liability when the limit came from General Liability)". The second is real: on two of the four positives the General Liability row has a blank aggregate cell while Products Liability beside it shows `50,000,000/50,000,000` (PRD F22). The tempting wrong answer is on the same page, and both are correctly labelled `null`.

**Consequences.** Wider schema; parsing failures degrade to a displayable verbatim string rather
than to silence. Aggregation (FR-4 "sum limits by currency") must skip rows where only the raw form
exists, and say that it did. A `total sum insured` limit is a weaker claim than an auto sublimit and
should read that way in the UI — it is the policy's overall cap, not an auto-specific figure. An
absent aggregate is a *fact about the policy*, not a gap in the extraction, and the README now says
so explicitly — worth keeping, because a blank cell in a demo table reads as a miss unless someone
says otherwise.

### D11 — Geographical scope is a rule-based derivation; `us_excluded` is separate

**Context.** FR-2 instructs the model not to infer unstated facts, yet the worked example sets
`geography_us: true` from "Geographical scope: World Wide" — which is an inference. Left
unresolved, that contradiction propagates into the prompt, and the model resolves it
arbitrarily.

**Decision.** Treat scope as the **one permitted derivation**, expressed as an explicit rule in
the prompt: a stated worldwide scope includes the US, *unless* the wording excludes it.
`geography_us` carries its own evidence quote either way, so the derivation is auditable.
`us_excluded` is a separate field with separate evidence.

**Why the exclusion clause gets named treatment.** "Worldwide excluding USA/Canada" is one of the
most common clauses in liability wordings and is this prototype's single largest false-positive
risk. It is given to the model as a named negative example, and `geography_us` carries an evidence
quote either way.

---

**Superseded in `b8d5173`: `us_scope_restriction` replaces the `us_excluded` boolean.**

This entry originally proposed a binary `us_excluded` field. Running the corpus turned up the case
that breaks it — `LP0000036557-30`, whose wording is *"No excess auto cover in USA is given, except
for people travelling from abroad"* (PRD F18). The cover is neither present-as-stated nor excluded.
A boolean has to round it to one or the other, and **both roundings are wrong**: call it excluded
and a real policy vanishes from the answer; call it covered and a USD 1,000,000 attachment point is
presented as a clean fact to an underwriter who would have read that sentence very differently.

The replacement keeps the wording instead of classifying it:

- `has_excess_auto_liability` stays `true` and the US attachment point is still reported — the cover does exist;
- `us_scope_restriction` holds the restriction **verbatim, in the document's own words** (stored as `ea_us_restriction`);
- a non-null value is a **review trigger** (D19), so the row surfaces for a human rather than resolving itself;
- the extraction prompt says explicitly not to bury restrictions in `notes`, because `notes` is not wired to the review list.

**Why this is the better design, stated plainly:** it declines to make a judgement the system is not
entitled to make. Every boolean encoding of this field is a silent underwriting decision taken by a
prompt. Carrying the sentence and flagging it is the only option that leaves the decision where it
belongs — and it is a stronger demo beat than a clean table, because it shows the system knowing the
limits of what it read. Mathias's design; it replaces mine wholesale.

**Consequences.** One documented exception to "do not infer" (the scope rule), stated in the prompt
and visible in the evidence panel. A wrong read is caught by ground truth (D20) rather than silently
inflating recall. Flagged rows moved 6/17 → 7/17 when the field landed — the new flag is a true
positive that was previously being presented as unqualified.

### D12 — `doc_id` is a content hash; raw extractions retained

**Decision.** `doc_id` is the first 16 hex chars of the SHA-256 of the file bytes. Ingestion is
idempotent on it; `--force` re-ingests. Every raw model response is kept in `raw_extractions`.

**Why.** A path- or filename-derived id would make the identifier depend on the folder — and
folders are exactly what D20 refuses to trust. Content hashing also survives the renames and
moves that a 6-hour build produces. Retained raw responses mean a parsing or schema fix can be
replayed **without re-reading pages**, which is the difference between a 30-second fix and
another 20 minutes of rate-limited ingestion.

**Consequences.** Identical files anywhere in the tree collapse to one document. **Near-identical**
files do not (F11) — that is D16's problem, not this one.

---

## C. Query & UI

### D13 — The model emits a validated filter DSL, never SQL

**Context.** The model must turn "which liability policies carry excess auto cover in the US"
into an executable query, against an index the user cannot see.

**Decision.** The model returns JSON — `filters[]` (field, op, value), `columns[]`, optional
`group_by`/`aggregate` — against the published schema (D8). The app validates every field and
operator against a whitelist, then compiles to SQL itself. **No model-authored SQL is ever
executed.**

**Why not model-authored SQL.** It is the obvious shortcut and it is wrong here on three
counts: it is an injection surface; it fails in ways that are unreadable to a jury ("the model
wrote a bad join"); and it makes a hallucinated column indistinguishable from a real one. A
whitelist makes an off-schema question a *detectable* condition, which is what D14 needs.

**Consequences.** Expressible questions are bounded by the DSL. That bound is a feature — it is
what makes D14 possible — and the honest answer to "what about questions you did not
anticipate?" is D21 Stage 3, not a bigger DSL.

### D14 — Refuse and explain rather than answer off-schema

**Decision.** When a question cannot be mapped to the schema, the app says so and lists what it
*can* answer. It never returns a partial or improvised table.

**Why.** The user is a domain expert who does not trust a number without a source (§3). A
plausible-looking table for "who is the broker?" costs more trust than an honest refusal, and
the failure is silent — nobody in a demo audience can tell that a column was invented.

### D15 — Follow-up chat answers only from supplied rows

**Decision.** Each chat turn is sent the current result rows *with their evidence quotes*, the
history, and the message. The model is instructed to answer only from those rows, to cite
`policy_no` and page for every fact, and to say so when the answer is not present.

**Why.** The chat is the one place in the UI where the model speaks in prose, so it is where
unsourced claims would enter. Constraining it to the visible result set keeps every sentence
traceable and keeps the turn cheap.

**Amended `148f78b` — answer language is detected, and field names are translated.** The build
added `detect_language()` (Swedish letters, or ≥2 words from a Swedish stop-word set) and passes the
resulting language into the chat prompt, replacing an instruction that asked the model to infer it.
It also supplies a glossary so prose says "attachment point" rather than `ea_attachment_amount` —
leaking column names into an answer aimed at an underwriter undercuts the whole "not a database"
framing. Both are the right call: language detection is deterministic and testable
(`tests/test_skeleton.py::test_detect_language`), where prompt-inferred language is neither.

### D16 — Near-duplicate documents are grouped, not dropped

**Context.** The two text PDFs extract 7,945 vs 7,941 characters over 9 pages each — near
identical, both in the Q1 folder (F11). Content hashing (D12) will not collapse them.

**Resolved 2026-09-11.** They are a duplicate/variant print of the same policy
(`LP0000045733-23`, same period), **not** two layers of one programme. So the marker reads
"duplicate", and the Q3-inside-Q1 hypothesis is dropped. Separately, and still open: both are
labelled `?` for excess auto cover — two independent reads found none (F12, PRD §14 Q3).

**Decision.** Group rows sharing `policy_no` + period into one row with a "duplicate" marker,
expandable to both sources. Recorded in `related_documents`. The wording matters: "related
documents" implied a programme relationship that turned out not to exist.

**Why not dedupe-and-drop.** Dropping one hides a document the underwriter may need, and if
they are genuinely two layers, they are two real answers. Two near-identical adjacent rows read
as double counting — the same table with one grouped row reads as the system understanding the
programme, which is the better demo and the more honest one.

### D17 — Query translations cached by normalised question text

**Context.** §8 originally demanded "identical question → identical JSON query in ≥9/10 runs" —
unverifiable without spending 10 rate-limited calls, and unachievable by configuration since
`claude -p` exposes no temperature control (D5).

**Decision.** Cache translations keyed on normalised question text. A repeated question is then
identical **by construction**. Verified by one spot-check per demo question.

**Implemented (`148f78b`).** `query_cache` table keyed on `normalise_question()` (trimmed,
lower-cased, whitespace collapsed, trailing punctuation stripped); **only successful, validated
translations are cached** — unmappable or failed ones never are, so a transient failure cannot be
memoised; a cached entry that no longer validates against the schema is deleted and re-translated,
so a schema change cannot serve a stale query; and the UI marks a cached answer with a
`cached translation` badge (`app.py`), which makes the repeatability visible during the demo rather
than merely true.

**Consequences.** Demo repeatability stops depending on sampling luck, and the second run of a
question is instant — which also makes the rehearsal honest. The badge doubles as the C5.5
check: if it does not appear on the second ask, the cache is not working.

---

## D. Trust

### D18 — Evidence is a page plus a quote verified against a stored transcript

**Context.** G3 claims "trust by construction". As originally specified, nothing verified that
`evidence_quote` actually appeared on `evidence_page`: the model asserted the quote, the index
stored it, the UI displayed it. With 17 of 19 documents having no text layer, there was no text
to check against — so the claim was *trust by assertion*, and the FR-7 acceptance criterion
("corrupting a quote flags the row") would have passed silently while testing nothing.

**Decision.** Each chunk also returns a plain-text transcript per page, stored in `page_text`.
Every `evidence_quote` is fuzzy-matched against the transcript of the page it cites; a mismatch
sets `quote_unverified`, which is a review flag (D19).

**Why this is cheap.** The model is already reading the page — the transcript is close to free
in tokens and needs no second call.

**Consequences.**
- G3 becomes a checked property of the system rather than a claim about the model.
- The quote can be highlighted in context without bounding boxes, which makes FR-6 genuinely optional rather than quietly load-bearing.
- It produces exactly the artefact D21 Stage 1 needs, so the prototype's trust mechanism and the production pipeline's OCR store are the same idea at different scales.
- **This is excluded from the cut list** in plan.md. Cutting it would not reduce scope; it would convert a verified claim into an unverified one while leaving the UI looking identical — the worst kind of cut.

### D19 — Confidence and review flags are surfaced, never auto-hidden

**Decision.** A row is flagged "Needs review" on any of: low confidence; a non-null value with
no quote; an `extraction_failed` chunk; `quote_unverified` (D18); chunks disagreeing on an
`excess_auto[]` entry (D4). Flagged rows are visually distinct, sort last, and can be filtered
*to*. Nothing is silently dropped.

**Why not filter them out.** A clean table that quietly omits uncertain rows is a table that
lies by omission, and it fails the case's own criterion ("missing some actual cases"). Showing
the uncertainty is also the more persuasive demo: a system that says "these three need a human"
is more credible to underwriters than one claiming perfection on 19 documents.

**Amended `148f78b` — evidence must display the value it supports.** The build added the extracted
value next to each evidence quote (`ui/evidence.py: _value_text`), because a quote that supports
`geography_us: false` and a quote that supports `true` look identical side by side: a reader sees a
sentence about the USA on the page and reads it as confirmation. A verified quote attached to an
unstated polarity is a *new* way to mislead, and it survives quote verification (D18) untouched —
verification checks that the quote is on the page, not that it supports the value it is filed
under. Good catch, and it belongs here rather than in the code alone. The 6 flagged rows in the
first full run are mostly exactly this shape: low confidence on an *absence* (PRD F15).

---

## E. Evaluation

### D20 — Ground truth is labelled blind of folder names

**Context.** The corpus arrives in four folders named after use cases, and it is tempting to
read `excess auto liability/` as the answer key for Q1. The case brief does not support that: it
asks contributors for "15–20 documents per use case" as documents *to search through*, so a
folder records what a document was contributed **for**, not a verified per-question label (F9).

**Decision.** Label all 19 documents from their content, folder ignored. The folder is recorded
in a separate `contributed_for` column so the two can be compared.

**Why this matters more than it looks.** `Layers/` is the likeliest source of further Q1
positives — a layer is literally "X in excess of Y", the same structure as an excess auto
attachment point. Scoring one of those as a false positive would fail a demo that was in fact
correct, and would do so in the exact way the case brief warns about. Folder-derived labels also
make the eval circular: it would measure agreement with a filing convention, not with the
documents.

**Outcome (2026-09-11) — this decision paid off, in the direction nobody predicted.** Labelling
produced **4 positives, 13 negatives and 2 unresolved**, not the 6/13 the folder implies. The two
`?` rows are both *inside* `excess auto liability/`, and two independent reads (text layer and
page images) found no explicit excess auto cover in either (PRD F12). The predicted failure was
extra positives hiding in `Layers/`; the actual failure is the Q1 folder over-stating its own
positives. Had the folder been the answer key, §9 would have demanded recall on two documents
that appear to carry no such cover — an unreachable target, chased for hours.

**Consequence now visible (PRD F14).** 15 of the 19 rows are marked
`claude-assisted (batch read, unverified)`. An eval labelled by the same model family that does
the extracting measures self-consistency, not correctness — so the negative set is currently
weaker evidence than the positive set. The four positives carry human or eye-checked provenance.
Cheapest fix inside the time box: eye-check only the negatives the system disagrees with.

With 4 positives and 13 negatives, precision and recall are **directional** indicators, not
statistically meaningful figures — stated on the Scale tab and in the README rather than quietly
implied.

---

## F. Scale

### D21 — The scale-out path is OCR-once, then a small model batched

The prototype is deliberately the small end of a pipeline whose cost is linear in documents
*once*, and near-constant per query (D1).

**Stage 0 — Triage on existing metadata (no LLM).** Product line, document type, date and
language route documents to the right extraction schema and exclude irrelevant ones. Even a weak
pre-filter (only liability policies, for Q1) cuts the LLM-read population by an order of
magnitude.

**Stage 1 — Get text once, store text + layout.** At archive scale, vision-LLM reading of every
page is the expensive path (D22). Most of the archive is text-based PDFs (D28), whose text layer —
with character positions — comes out free via `pypdfium2`. Only the scanned share goes through
dedicated OCR (Azure Document Intelligence, AWS Textract, or open-source on GPU), once per page.
Either way the store holds text with bounding boxes, which yields exact highlight coordinates —
what FR-6 approximates — and reduces later extraction to a text task. It is the same artefact D18
produces at prototype scale, and it is where D3's text-layer fast path now lives.

Framing this as "get text" rather than "OCR" is not cosmetic: it moves OCR from *the* Stage 1 cost
to a minority surcharge, which is most of why the production path is cheap (D22).

**Stage 2 — Schema extraction with a small model, batched.** Text-only extraction with
Haiku-class models via the Batch API (−50%), asynchronous, resumable, keyed by document hash
(D12). The extraction prompt is the schema from PRD §7.1 with evidence quotes required —
unchanged from the prototype. Escalate only low-confidence documents to a larger model.

**Stage 3 — Index.** Structured facts and evidence in a columnar/OLAP store (or Postgres at
10⁸ rows); page text in a search engine with vector + BM25 for the "unknown question" path that
the DSL (D13) deliberately does not cover. Queries hit the index; the LLM only translates and
summarises.

**Stage 4 — Human feedback loop.** Underwriter flags and corrections (D19) become regression
tests and few-shot examples. Re-extraction is per document, never per corpus (D1).

**Consequences.** Throughput becomes a parallelism and batching question rather than an
architecture question. Stage 1 is a one-off cost with a permanent payoff, which is what D22's
corrected arithmetic makes obvious.

### D22 — Cost figures are labelled by model; measured ≠ extrapolated

**Context.** An earlier version of this model assumed ~1,500 tokens per page image, putting the
full-corpus vision path at ≈$2.8M and making it look comparable to OCR. Two independent routes
show that is 2–3× too low. First, Sonnet 5 and Opus 5 are high-resolution vision models — up to
2,576 px on the long edge, up to ~4,784 tokens per image — and a ~1,200 px-wide page (D2) sits
well above the low-resolution tier. Second, the measurement in F6 says the same thing: ~$0.01
per page measured, against ~$0.002 implied by the old figure.

**Decision.** Price the vision path at ~3,500 tokens/page, and **label every figure with the
model that produced it**. `claude -p` measures an Opus-class model at $5/$25 (D5); the
extrapolation reprices to Sonnet 5 ($2/$10) or Haiku 4.5 ($1/$5) with Batch −50%. The Scale tab
shows the repricing as an explicit step.

**Reconciled against the built Scale tab (2026-09-11, `148f78b`).** The implemented tab
(`ui/scale.py`, `config.py`) and this entry disagreed. Resolved as follows, taking the measurement
from their side and the token figure from this one:

- **Pages per document: theirs wins.** This entry assumed 8; the actual run measured a **mean of 11.9** (median 8) over 226 pages (PRD F17). The tab already seeds its input from the measurement (`app.py:164`), which is the right behaviour — the assumption should follow the data.
- **Tokens per page image: this entry wins.** `config.SCALE_DEFAULTS["tokens_per_page_image"]` is still **1,500**, the figure the review corrected to ~3,500 (see the context above). It is the last uncorrected input in the model.
- **A third cost category is needed**, discovered by running it: measured-through-the-CLI is **≈$0.18/doc**, about **9× the ≈$0.02/doc** the same work costs on the API, because every `claude -p` call carries Claude Code's prompt overhead (PRD F16). So there are now three figures, not two, and the middle one is the only sound basis for extrapolation.

**Re-reconciled after `b8d5173`.** Two corrections land together, and one of them is mine:

- **The measured figures are Sonnet-priced, not Opus.** This entry previously said the measurement ran on "Claude Code's default Opus-class model". It does not: `config.MODEL` is `claude-sonnet-5` and the CLI is invoked with `--model`. The reason nobody could tell is the bug in `ingest/claude_cli.py` that recorded the *auxiliary* model (Haiku) for every run — fixed, with a regression test, and verified by re-ingesting (`claude-haiku-4-5-20251001` → `claude-sonnet-5`, same $0.1446). The labelling mechanism this entry depends on now actually works.
- **The production path is re-modelled around the scan share (D28).** OCR is paid only on the ~20 % of documents that are scans, and text extraction scales per page (`text_tokens_per_page: 500`) instead of a flat 4k per document.

**Cost envelope** (200M documents, Sonnet 5 + Batch −50%; totals shown at both page counts because
the published figures disagree — see below):

| Path | @ 8.0 pages/doc | @ 11.9 pages/doc (measured) | Use it for |
|---|---|---|---|
| Measured through the CLI (harness overhead, multi-turn) | — | ≈ $0.18/doc → **≈ $36M** | An **upper bound only**. Never the headline. |
| Prototype path — every page as an image, at the tab's 1,500 tok/page | ≈ $2.8M | ≈ $4.0M | What the tab shows today — still understated. |
| Prototype path at the **measured render** (~2,585 tok/page) | ≈ $4.5M | ≈ $6.6M | The honest vision-path figure. |
| **Production path — text layer free, OCR on the 20 % scanned share, text-only extraction** | **≈ $1.7M** | **≈ $2.3M** | The recommended path (D21). |
| With Stage 0 triage keeping 20 % | ≈ $0.35M | ≈ $0.5M | The realistic programme cost. |

**Where the per-page token figure landed.** Not 1,500 (config), not 3,500 (this entry's earlier
correction — too high), but **~2,585**: the rasteriser emits 1224×1584 px pages, and `(w×h)/750` is
the image-token formula. Measured `input_tokens` cannot substitute — at 5,747/page it carries the
CLI's multi-turn overhead (D27). The remaining honest step is one `count_tokens` call on a real page
image (plan.md C8.3), but the stakes have dropped: **the ordering no longer flips.** D28's scan share
makes the production path cheaper than the vision path at *any* of these token figures, so the
uncorrected 1,500 now understates a path we are not recommending.

**Two defects that survive this round.**

1. **The same path is published at two different totals** — §10 says ≈$1.7M, the runbook says ≈$2.3M (PRD F19). Both are right for their own pages/doc (8.0 config default vs 11.9 measured). A jury reading both finds an inconsistency nobody intended. Pick one and state its assumption.
2. **The Batch discount is still applied to the measured row** (`ui/scale.py:71`). It is now labelled an upper bound with the multi-turn overhead explained, which is a real improvement — but multiplying a harness-inflated measurement by an API-pricing discount still nets two errors against each other. Show it undiscounted (plan.md C8.7).

**Two corrections this implies for the build.**

1. **The tab currently inverts the recommendation.** At 1,500 tokens/page it shows vision ($4.0M) as *cheaper* than OCR ($4.8M), and the runbook repeats that ordering. At the corrected token figure the ordering flips — vision $8.8M against OCR $4.8M — which restores D21's conclusion. Fixing one number in `config.py` changes which architecture the demo appears to recommend, so it is worth the two minutes.
2. **Do not apply the Batch discount to the measured CLI cost.** `ui/scale.py:71` computes the measured row as `measured_cost_per_doc × docs × (1 − batch_discount)`, which is how $0.18/doc became the runbook's "$17.9M". That figure mixes a harness-inflated measurement with a discount that applies to API list pricing — two errors pointing in opposite directions, netting out to a number that is neither. Show the measured row **undiscounted** as a ceiling, and let the API rows carry the discount.

**The `count_tokens` check is still outstanding**, and running it settles the only remaining
disagreement. The measured `input_tokens_per_doc` in `ingest_metrics` cannot substitute for it:
that number carries the same CLI prompt overhead that inflates the $0.18 (PRD F16), so it cannot
isolate the image tokens. One `count_tokens` call on one real page image, against the API, ends the
argument — plan.md check C8.3.

**Why label the models.** FR-8 populates the Scale tab from measured `total_cost_usd`
(Opus-priced) and then extrapolates with Sonnet prices. Unlabelled, those two numbers sit ~4×
apart with no explanation, on the one slide whose entire purpose is to be arithmetic a jury can
trust. An unexplained 4× is worse than a large number.

**Consequences.** The correction **strengthens** the recommendation: once the vision path is
priced honestly at ≈$6M against ≈$2.8M for OCR-plus-Haiku, Stage 1 (D21) stops being a marginal
preference and becomes the obvious architecture. The prototype's vision path is a 6-hour
expedient and the numbers now say so out loud. Prices are September 2026 Anthropic list prices
and must be re-checked before any real business case; re-baseline page tokens with
`count_tokens` on one real page image before quoting a figure.

---

## G. Build environment

### D23 — Dependencies declared in `pyproject.toml`, run through `uv`

**Context.** `uv` needs `--native-tls` on this network, and the project `settings.json` denies
`pip install`, `uv add`, `uv remove` and `uv pip` (F7).

**Decision.** Declare every dependency once in `pyproject.toml` and run everything through
`uv run`. Nothing is installed ad hoc.

**Note.** `--native-tls` is **deprecated** in the installed `uv` (0.12.13) in favour of
`--system-certs`; both work today and the deprecated flag prints a warning on every invocation.
Use `--system-certs` in committed commands and the README so the repo does not ship a warning
in its own documented workflow. Python 3.13.1 is present on the machine, so the
`requires-python = ">=3.13"` pin resolves without a download.

**Consequences.** Adding a dependency is a file edit plus a re-run, not an install command —
which is what makes FR-9 ("a second person reproduces the demo") achievable.

### D24 — Everything local except page content sent to Claude

**Decision.** PDFs, page images, transcripts and the index stay on the build machine. The only
data leaving it is page content sent to the model through `claude -p` (D5). Documented in the
README, not only here.

**Consequences and the honest caveat.** The example PDFs are real If Industrial documents, only
partly redacted (F2), and D5 routes their page content through a personal Claude Pro
subscription. The production answer is the Anthropic API, where commercial terms and data
handling apply and the archive never leaves If's control. Whether the *example set* may be used
this way is not our call to assume — see D25.

---

## Open

### D25 — Whether the example corpus may be sent to a consumer subscription

**Status: Open, and it blocks ingestion.** D5 and D24 together mean real policy documents are
transmitted to a personal Claude Pro subscription. That is the standing assumption of the whole
build, and it has not been confirmed by anyone entitled to confirm it.

**What we need.** A yes/no from the case owner on using the provided example set this way.

**If the answer is no.** The fallback inside the time box is to redact harder before
rasterising (crop headers, mask `LP`/`LC` numbers) and demo on that, accepting reduced header
extraction quality — or to obtain API access under commercial terms, which is out of the time
box. Either way this is decided **before** ingestion starts, not after 226 pages have been sent.
See plan.md Iteration 0, check C0.4.


### D26 — Reconcile the committed skeleton with the revised schema

**Status: Open, and it blocks plan.md Iteration 2.** Commit `0aa6b3b` ("Skeleton") landed a
working code skeleton — rasteriser, `claude -p` wrapper, SQLite layer, chunk merge, extraction
prompt, query translation, chat, Streamlit UI, eval harness, tests. It was written against the
**pre-review** PRD, so it implements the earlier schema. The gap, field by field:

| Revised PRD requires | Skeleton has | Decision it implements |
|---|---|---|
| `excess_auto` as a **list** | a single object (`"excess_auto must be an object or null"`) | D9 |
| `page_text` table + quote verification | neither | **D18** |
| `us_excluded` field | exclusion collapsed into `geography_us: false` | D11 |
| `limit_raw`, `limit_is_unlimited`, `aggregate_amount` | none | D10 |
| `related_documents` table | none | D16 |
| `input_path_kind` + text-layer fast path | image path only | D3 |
| 5 review-flag triggers | 3 (low confidence, missing quote, failed chunk) | D19 |

The skeleton is also **ahead** of the PRD in one respect, which is why this is a reconciliation
and not a rewrite: its extraction prompt already handles "World Wide excluding USA/Canada" →
false, and it introduced `limit_source` / `limit_evidence` (now merged into PRD §7.1 as D10's
amendment, PRD F13).

**Options.**

1. **Adapt the skeleton** — add the missing columns and the `page_text` table, change
   `excess_auto` to a list, extend the flag triggers. Keeps the working code and the tests.
   Largest single piece is quote verification (D18), which is new behaviour rather than a column.
2. **Keep the skeleton's schema and drop the revisions** — cheapest in hours, but it discards
   D18 (quote verification), which the PRD's G3 now depends on, and D9 (list) re-opens the
   silent-merge hole the chunking exposed.
3. **Split** — adopt D9, D18 and `us_excluded` (the three that affect correctness or the central
   trust claim) and defer D10's extra columns, D16's table and D3's fast path.

**Recommendation: option 3.** `excess_auto` as a list and `page_text` + verification are the two
that change what the demo can honestly claim; the rest are schema comfort that can land later or
not at all. Whoever owns track A should make this call before the schema freeze, because
everything downstream keys off it.

**Status after `148f78b`: still open, and the green run does not close it.** The build ran the full
corpus on the skeleton's schema and scored precision 1.00 / recall 1.00 (PRD F15). It is tempting to
read that as "the revisions were unnecessary" — they measure different things:

- The eval asks *does the extracted value match the label?* On 13 of 17 scored rows the label is itself model-assisted (PRD F14), so agreement there is partly self-agreement.
- Quote verification (D18) asks *does the quote actually appear on the page it cites?* Nothing in the current build checks this, and a 1.00 eval score is compatible with every quote being fabricated, provided the *numbers* are right. That is not a hypothetical failure mode for a vision model reading a scan: right number, invented sentence.

So the honest position is that G1 is met and **G3 is not yet demonstrated** — which is why §9.3 now
says so explicitly. Option 3 remains the recommendation, and `page_text` + verification is the piece
that turns a strong result into a defensible one. `excess_auto`-as-a-list is now lower priority than
it looked: the run produced no document with two excess auto sections, so the silent-merge hole
(D4, D9) is real but unexercised on this corpus.

**What a jury will actually ask.** "How do you know the quote is really on that page?" The current
answer is "the model said so". That is the gap worth closing with the remaining time, ahead of any
schema widening.

**Cheaper than assessed, and now verified.** `index/db.py` carries a `MIGRATIONS` list applied on
`connect()` (PRD F20). Tested against the one database that could test it — a local index created
before *either* new column existed: opening it with the current code added `ea_us_restriction` and
`ea_limit_aggregate_amount` in sequence, leaving the existing row intact (PRD F23). Adding a column
is no longer a 20-minute re-read of the corpus, which removes the main practical objection to
option 3. `page_text` is a new table rather than a column, but the same mechanism covers it; only
back-filling it needs a re-read, and only for documents already ingested.

**Which makes the remaining objection purely one of hours, not of risk.** Option 3 is now: one
migration, one verification pass, and a fourth review trigger. The reason to do it is unchanged —
without it, "every number has a page" is the model's word (D18).

**This is a team decision, not one to take by inference** — the skeleton is someone else's work
and the trade is about their hours.


### D27 — Three cost figures, three labels: CLI-measured, API-modelled, OCR-modelled

**Context.** Running the pipeline produced a number nobody predicted: **≈$0.18/doc** measured
through `claude -p`, against **≈$0.02/doc** for the same work on the API (PRD F16). The gap is
Claude Code's per-call prompt overhead — system prompt and tool definitions on every chunk call —
and it is roughly 9×. An earlier draft of D22 had already been wrong once in the other direction by
assuming image tokens were cheap; this is the same class of error with a different sign.

**Decision.** The Scale tab and every cost claim carry **three** separately labelled figures, never
a blend:

1. **CLI-measured** — what this run actually cost. An **upper bound**, shown undiscounted. It measures the harness as much as the workload, so it never leads.
2. **API-modelled (vision)** — the prototype's own approach priced on the API, at a token figure established by `count_tokens` on a real page image rather than assumed.
3. **API-modelled (OCR + text)** — the recommended production path (D21).

**Why a decision and not just a fix.** The temptation under time pressure is to show the single
most impressive number, and the measured figure is the one with real provenance — it is *measured*,
which feels unarguable. But $0.18/doc × 200M documents is $36M, a number that would sink the
business case on the strength of a development expedient (D5). Equally, quoting only the $0.02
model invites "so you didn't actually measure it". Three labelled figures is the only framing that
survives both questions, and it costs one extra table row.

**Consequences.** `ui/scale.py:71` must stop applying the Batch discount to the measured row
(see D22). The `count_tokens` baseline (plan.md C8.3) moves from nice-to-have to required, because
figure 2 is the one the recommendation rests on and it is currently the weakest-sourced of the
three.

**Confirmed independently in `b8d5173`.** Mathias reached the same conclusion without seeing this
entry — decisions.md has never been pushed — and labelled the Scale tab's measured row as an upper
bound, explaining that the CLI "reads each page in a separate turn and re-sends context, ~3–4× the
tokens of one API call carrying all page images". Measured here at 2.2× on an 8-page chunk
(`num_turns=10`, 45,976 input tokens against ~2,585/page of actual image). Two people arriving at
the same correction from different directions is the best evidence available that it is real.

**The labelling mechanism now works.** This decision requires every figure to name its model, and
until `b8d5173` the code could not: `_metrics_from_envelope` recorded `next(iter(modelUsage))`, which
is the auxiliary Haiku call, not the Sonnet call that did the work and carried 98 % of the cost.
Fixed in `ingest/claude_cli.py` with `_dominant_model()` (rank by cost, fall back to tokens) plus a
regression test built from a captured envelope. Ranking by *cost* rather than tokens matters: in the
captured envelope Sonnet used 6 tokens to Haiku's 909 and still carried the cost, so a token-ranked
fix would have reproduced the bug exactly.


### D28 — The archive is assumed ~20 % scanned, and that assumption is load-bearing

**Status: Accepted as a working assumption; the number itself is unconfirmed.**

**Context.** The PRD carried "17 of 19 examples are scans" straight into the architecture: OCR/vision
was declared mandatory on the main path, and the cost model priced OCR across the whole corpus. In
`b8d5173` Mathias challenged the inference rather than the observation — 19 documents chosen for a
caseathon are not a sample of a 200M-document archive, and a modern insurance archive is mostly
text-based PDFs with a long tail of scans.

**Decision.** Assume **~20 % of the archive is scanned**, price the text layer as free and OCR as a
surcharge on that share only, and expose the share as a slider on the Scale tab so nobody has to take
the number on faith.

**Why this is the right way to hold it.** The assumption is *large*: it moves the production path from
≈$4.8M to ≈$1.7–2.3M, roughly halving the headline. An assumption that big, that favourable, and that
unverified is exactly the kind a jury should be suspicious of — so it is stated in F1 as an
assumption, named in the README, and made adjustable in the UI. A slider that anyone can drag to 100 %
is a stronger position than a confident number, because it invites the check instead of surviving it.

**What it does not change.** The prototype still reads every page as an image (D3, revised): scans are
the hard case and the case that must work. The assumption affects the *production* cost model and
nothing about what is built or demonstrated.

**What would falsify it.** One question to the case owner: what share of the LH policy archive has no
text layer? If the answer is "most of it", the production path returns to ≈$4.8M, OCR dominates again,
and D21 Stage 1 reverts to its original framing — the architecture survives, the business case gets
worse. If the answer is 20 % or less, the current numbers stand. Either way this is a ten-minute
question with a six-figure consequence, and it is PRD §14 Q6.
