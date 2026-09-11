"""Compare the index against eval/ground_truth.csv (PRD s9).

    uv run --native-tls python eval/run_eval.py [--add-missing-rows]

Reports precision/recall for "policy has US excess auto cover", exact-match
rate for attachment point and limit among true positives, and the share of
rows flagged "Needs review".

ground_truth.csv columns (one row per PDF, `file` relative to docs/examples):
    file, policy_no, has_excess_auto_us (Y/N), attachment_amount, attachment_currency,
    attachment_page, attachment_quote, limit_amount, limit_currency, limit_page,
    limit_quote, notes
Rows with an empty `has_excess_auto_us` are treated as not yet labelled and skipped; `?` means either
answer is accepted. Extra columns (e.g. `labelled_by`) are preserved.
`--add-missing-rows` appends a blank row for every PDF not yet in the CSV.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import config  # noqa: E402
from index import db  # noqa: E402
from ingest.pipeline import find_pdfs, make_doc_id  # noqa: E402

GT_PATH = Path(__file__).parent / "ground_truth.csv"
GT_COLUMNS = ["file", "policy_no", "has_excess_auto_us", "attachment_amount", "attachment_currency",
              "attachment_page", "attachment_quote", "limit_amount", "limit_currency", "limit_page",
              "limit_quote", "notes"]


def read_gt() -> list[dict[str, str]]:
    if not GT_PATH.exists():
        return []
    with GT_PATH.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def add_missing_rows() -> None:
    rows = read_gt()
    columns = list(rows[0].keys()) if rows else GT_COLUMNS   # preserve any extra columns (e.g. labelled_by)
    known = {r["file"].replace("\\", "/") for r in rows}
    added = 0
    for pdf in find_pdfs(config.EXAMPLES_DIR):
        rel = pdf.relative_to(config.EXAMPLES_DIR).as_posix()
        if rel not in known:
            rows.append({c: "" for c in columns} | {"file": rel})
            added += 1
    with GT_PATH.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"{GT_PATH}: {added} row(s) added, {len(rows)} total")


def _yn(v: str | None) -> bool | str | None:
    """Y/N -> bool; empty -> None (unlabelled); '?' -> 'either' (any prediction accepted)."""
    v = (v or "").strip().lower()
    if v == "":
        return None
    if v == "?":
        return "either"
    return v in ("y", "yes", "true", "1")


def _num(v: str | None) -> float | None:
    v = (v or "").strip().replace(",", "").replace(" ", "")
    return float(v) if v else None


def _cur(v: str | None) -> str:
    return (v or "").strip().upper()


def run() -> int:
    gt = read_gt()
    if not gt:
        print("no ground truth yet — see eval/ground_truth.csv")
        return 2
    conn = db.connect()
    facts = {r["doc_id"]: dict(r) for r in db.all_facts(conn)}

    tp = fp = fn = tn = 0
    exact_attach = exact_limit = positives = flagged = unlabelled = not_extracted = ambiguous = 0
    exact_agg = [0, 0]   # matches, scored (only when the ground truth has a limit_aggregate_amount column)
    lines = []
    for g in gt:
        truth = _yn(g.get("has_excess_auto_us"))
        if truth is None:
            unlabelled += 1
            continue
        doc_id = make_doc_id(config.EXAMPLES_DIR / g["file"].replace("\\", "/"), config.EXAMPLES_DIR)
        f = facts.get(doc_id) or {}
        if f.get("status") not in ("ok", "partial"):
            # No extraction happened (missing, failed, pending): never score it as a correct negative.
            not_extracted += 1
            lines.append(f"--  {g['file']:55} truth={truth!s:5} NOT EXTRACTED ({f.get('status') or 'missing'})")
            continue
        pred = bool(f.get("has_excess_auto")) and bool(f.get("geography_us"))
        flagged += bool(f.get("needs_review"))
        if truth == "either":
            ambiguous += 1
            lines.append(f"?   {g['file']:55} truth=?     pred={pred!s:5}  (either accepted)")
            continue
        if truth and pred:
            tp += 1
        elif truth:
            fn += 1
        elif pred:
            fp += 1
        else:
            tn += 1

        detail = ""
        if truth:
            positives += 1
            a_ok = (_num(g.get("attachment_amount")) == f.get("ea_attachment_amount")
                    and _cur(g.get("attachment_currency")) == _cur(f.get("ea_attachment_currency")))
            l_ok = (_num(g.get("limit_amount")) == f.get("ea_limit_amount")
                    and _cur(g.get("limit_currency")) == _cur(f.get("ea_limit_currency")))
            exact_attach += a_ok
            exact_limit += l_ok
            detail_agg = ""
            if "limit_aggregate_amount" in g:
                g_ok = _num(g.get("limit_aggregate_amount")) == f.get("ea_limit_aggregate_amount")
                exact_agg[0] += g_ok
                exact_agg[1] += 1
                detail_agg = f"  agg {'OK ' if g_ok else 'BAD'} {f.get('ea_limit_aggregate_amount')}"
            detail = (f"  attach {'OK ' if a_ok else 'BAD'} {f.get('ea_attachment_amount')} {f.get('ea_attachment_currency') or ''}"
                      f"  limit {'OK ' if l_ok else 'BAD'} {f.get('ea_limit_amount')} {f.get('ea_limit_currency') or ''}" + detail_agg)
        missing = "" if f else "  (not in index)"
        flag = "  [needs review]" if f.get("needs_review") else ""
        lines.append(f"{'OK ' if truth == pred else 'BAD'} {g['file']:55} truth={truth!s:5} pred={pred!s:5}{detail}{missing}{flag}")

    print("\n".join(lines))
    labelled = len(gt) - unlabelled - not_extracted - ambiguous
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    print(f"\nscored {labelled}/{len(gt)} rows (unlabelled: {unlabelled}, not extracted: {not_extracted}, '?' either-accepted: {ambiguous})")
    print(f"US excess auto cover:  precision {precision:.2f}  recall {recall:.2f}  (tp={tp} fp={fp} fn={fn} tn={tn})")
    if positives:
        print(f"exact match on true positives: attachment {exact_attach}/{positives}, limit {exact_limit}/{positives}"
              + (f", aggregate {exact_agg[0]}/{exact_agg[1]}" if exact_agg[1] else ""))
    print(f"rows flagged needs_review: {flagged}/{labelled}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--add-missing-rows", action="store_true",
                    help="append a blank row for every PDF not yet in ground_truth.csv (existing rows untouched)")
    args = ap.parse_args()
    if args.add_missing_rows:
        add_missing_rows()
        sys.exit(0)
    sys.exit(run())
