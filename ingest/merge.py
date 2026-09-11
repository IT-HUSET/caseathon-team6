"""Merge chunk results into one document record (FR-1 merge rules, FR-7 review flags).

Rules from the PRD:
- header fields: first non-null wins (chunks are in page order, header is on p1)
- cover facts: union with their evidence; a positive `has_excess_auto_liability`
  from any chunk wins over false/null, and the chunk that stated it supplies the figures
- needs_review when: any displayed value is `low`, a non-null value has no evidence
  quote, any chunk failed extraction, or the US excess auto cover carries a scope
  restriction (`excess_auto.us_scope_restriction`)
"""

from __future__ import annotations

from typing import Any

from ingest.extract import ChunkResult

HEADER_FIELDS = {
    # extraction key -> policy_facts column
    "policy_no": "policy_no",
    "client_no": "client_no",
    "policyholder": "policyholder",
    "policy_period_start": "period_start",
    "policy_period_end": "period_end",
    "document_language": "language",
    "product_line": "product_line",
    "geography_scope": "geography_scope",
}

EXCESS_AUTO_FIELDS = {
    "attachment_point_amount": "ea_attachment_amount",
    "attachment_point_currency": "ea_attachment_currency",
    "limit_amount": "ea_limit_amount",
    "limit_aggregate_amount": "ea_limit_aggregate_amount",
    "limit_currency": "ea_limit_currency",
    "basis": "ea_basis",
    "notes": "ea_notes",
    "us_scope_restriction": "ea_us_restriction",
}

# Fields whose evidence/confidence decide the review flag (the "displayed values").
REVIEWED_FIELDS = ("geography_us", "has_excess_auto", "excess_auto", "excess_auto_limit")


def _bool_to_int(v: Any) -> int | None:
    return None if v is None else int(bool(v))


def _clean(v: Any) -> Any:
    """Models sometimes emit the string "null"/"" for missing values; treat those as None."""
    if isinstance(v, str) and v.strip().lower() in ("", "null", "none", "n/a"):
        return None
    return v


def _evidence_row(field: str, ev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not ev:
        return None
    return {
        "field": field,
        "page": ev.get("evidence_page"),
        "quote": ev.get("evidence_quote"),
        "confidence": ev.get("confidence"),
        "bbox": ev.get("bbox"),           # FR-6 stretch; normally absent
    }


def merge_chunks(chunks: list[ChunkResult]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return (facts for policy_facts, evidence rows)."""
    facts: dict[str, Any] = {col: None for col in HEADER_FIELDS.values()}
    facts.update({col: None for col in EXCESS_AUTO_FIELDS.values()})
    facts.update({"geography_us": None, "has_excess_auto": None})
    evidence: list[dict[str, Any]] = []
    reasons: list[str] = []

    ok_chunks = [c for c in sorted(chunks, key=lambda c: c.chunk_index) if c.status == "ok" and c.data]
    failed = [c for c in chunks if c.status != "ok"]
    for c in failed:
        reasons.append(f"chunk {c.chunk_index} (pages {c.first_page}-{c.last_page}): {c.status}")

    # Header: first non-null wins.
    for c in ok_chunks:
        for src, col in HEADER_FIELDS.items():
            if facts[col] is None and _clean(c.data.get(src)) is not None:
                facts[col] = _clean(c.data[src])

    # Boolean cover facts: any True wins, else any False, else None. Keep the evidence of the winner.
    for src, col in (("geography_us", "geography_us"), ("has_excess_auto_liability", "has_excess_auto")):
        winner: ChunkResult | None = None
        for c in ok_chunks:
            v = c.data.get(src)
            if v is True:
                winner = c
                break
            if v is False and winner is None:
                winner = c
        if winner is not None:
            facts[col] = _bool_to_int(winner.data.get(src))
            row = _evidence_row(col, (winner.data.get("field_evidence") or {}).get(src))
            if row:
                evidence.append(row)
            elif facts[col] is not None:
                reasons.append(f"{col} has no evidence quote")

    # Excess auto figures: take them from the first chunk that reports the cover with an object.
    ea_src = next((c.data["excess_auto"] for c in ok_chunks
                   if c.data.get("has_excess_auto_liability") and isinstance(c.data.get("excess_auto"), dict)), None)
    if ea_src:
        for src, col in EXCESS_AUTO_FIELDS.items():
            facts[col] = _clean(ea_src.get(src))
        row = _evidence_row("excess_auto", ea_src)
        if row and (row["quote"] or row["page"]):
            evidence.append(row)
        lim = ea_src.get("limit_evidence")
        if isinstance(lim, dict) and (lim.get("evidence_quote") or lim.get("evidence_page")):
            evidence.append(_evidence_row("excess_auto_limit", lim))
        if any(ea_src.get(k) is not None for k in ("attachment_point_amount", "limit_amount")) and not ea_src.get("evidence_quote"):
            reasons.append("excess_auto figures have no evidence quote")
        # FR-7: cover that exists but is narrower in the US than the headline says is an underwriter call, not a fact.
        if facts["ea_us_restriction"]:
            reasons.append(f"US excess auto cover is restricted: {facts['ea_us_restriction']}")

    # FR-7: low confidence on any displayed value.
    for row in evidence:
        if row["field"] in REVIEWED_FIELDS and row["confidence"] == "low":
            reasons.append(f"{row['field']} confidence is low")
        if row["field"] in REVIEWED_FIELDS and row["confidence"] is None:
            reasons.append(f"{row['field']} has no confidence")

    facts["needs_review"] = int(bool(reasons))
    facts["review_reasons"] = reasons
    return facts, evidence
