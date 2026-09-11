"""The published, fixed schema (PRD s7 / FR-3).

Two things live here:

1. QUERY_FIELDS - the whitelist of columns a natural-language question may be
   translated into. Claude only ever emits field names, operators and values
   from this list; `query.execute` refuses anything else. No free-form SQL.

2. EXTRACTION_* - the shape of the JSON Claude returns per page-chunk at
   ingestion (s7.1) and the defensive validation for it (FR-2).
"""

from __future__ import annotations

import json
from typing import Any

# ---------------------------------------------------------------------------
# 1. Query schema (what the UI can ask)
# ---------------------------------------------------------------------------

# name -> (sql column in policy_facts, type, description shown to Claude)
QUERY_FIELDS: dict[str, tuple[str, str, str]] = {
    "policy_no":              ("policy_no", "text", "Policy number, e.g. LP0000045733-23"),
    "client_no":              ("client_no", "text", "Client number, e.g. LC0021022747"),
    "policyholder":           ("policyholder", "text", "Policyholder name (often redacted -> null)"),
    "period_start":           ("period_start", "date", "Policy period start, ISO date"),
    "period_end":             ("period_end", "date", "Policy period end, ISO date"),
    "language":               ("language", "text", "Document language code (en, sv, da, fi)"),
    "product_line":           ("product_line", "text", "liability | property | marine | other"),
    "geography_scope":        ("geography_scope", "text", "Geographical scope as written, e.g. 'World Wide'"),
    "geography_us":           ("geography_us", "bool", "True if cover applies in the United States"),
    "has_excess_auto":        ("has_excess_auto", "bool", "True if the policy carries excess auto liability cover"),
    "ea_attachment_amount":   ("ea_attachment_amount", "number", "Excess auto attachment point (excess point) amount"),
    "ea_attachment_currency": ("ea_attachment_currency", "text", "Currency of the attachment point (ISO code)"),
    "ea_limit_amount":        ("ea_limit_amount", "number", "Excess auto limit amount"),
    "ea_limit_currency":      ("ea_limit_currency", "text", "Currency of the limit (ISO code)"),
    "ea_basis":               ("ea_basis", "text", "Basis of the limit, e.g. 'per occurrence'"),
    "needs_review":           ("needs_review", "bool", "True when any value is low-confidence or unevidenced"),
}

# Always shown in a result table regardless of what the question asked for (FR-3).
ALWAYS_COLUMNS = ["policy_no", "needs_review"]

OPS_BY_TYPE: dict[str, set[str]] = {
    "text":   {"eq", "neq", "contains", "in", "is_null", "not_null"},
    "date":   {"eq", "neq", "gt", "gte", "lt", "lte", "is_null", "not_null"},
    "bool":   {"eq", "is_null", "not_null"},
    "number": {"eq", "neq", "gt", "gte", "lt", "lte", "in", "is_null", "not_null"},
}

AGGREGATES = {"count", "sum", "avg", "min", "max"}

QUERY_JSON_EXAMPLE = {
    "filters": [
        {"field": "has_excess_auto", "op": "eq", "value": True},
        {"field": "geography_us", "op": "eq", "value": True},
    ],
    "columns": ["policy_no", "policyholder", "period_start", "period_end",
                "ea_attachment_amount", "ea_attachment_currency",
                "ea_limit_amount", "ea_limit_currency"],
    "group_by": None,
    "aggregate": None,
    "explanation": "Policies with excess auto liability cover in the US, with attachment point and limit.",
}

# Returned when the question cannot be mapped (FR-3): the model sets this instead of a query.
UNMAPPABLE_EXAMPLE = {
    "unmappable": True,
    "reason": "The index has no broker field.",
}


def schema_for_prompt() -> str:
    """Human/LLM-readable description of the query schema, embedded in the translate prompt."""
    lines = ["field | type | meaning", "--- | --- | ---"]
    for name, (_, typ, desc) in QUERY_FIELDS.items():
        lines.append(f"{name} | {typ} | {desc}")
    ops = "\n".join(f"- {t}: {', '.join(sorted(o))}" for t, o in OPS_BY_TYPE.items())
    return (
        "\n".join(lines)
        + "\n\nAllowed operators per type:\n" + ops
        + "\n\nAllowed aggregates: " + ", ".join(sorted(AGGREGATES))
        + "\n\nExample query JSON:\n" + json.dumps(QUERY_JSON_EXAMPLE, indent=2)
        + "\n\nIf the question cannot be answered from these fields, return:\n"
        + json.dumps(UNMAPPABLE_EXAMPLE, indent=2)
    )


# ---------------------------------------------------------------------------
# 2. Extraction schema (what Claude returns per chunk at ingestion, s7.1)
# ---------------------------------------------------------------------------

CONFIDENCE_LEVELS = {"high", "medium", "low"}

EXTRACTION_EXAMPLE: dict[str, Any] = {
    "policy_no": "LP0000045733-23",
    "client_no": "LC0021022747",
    "policyholder": None,
    "policy_period_start": "2022-01-01",
    "policy_period_end": "2022-12-31",
    "document_language": "en",
    "product_line": "liability",
    "cover_summary": ["General Liability", "Product Liability", "Recall"],
    "geography_scope": "World Wide",
    "geography_us": True,
    "has_excess_auto_liability": True,
    "excess_auto": {
        "attachment_point_amount": 1000000,
        "attachment_point_currency": "USD",
        "limit_amount": 25000000,
        "limit_currency": "EUR",
        "basis": "per occurrence",
        "notes": "applies to owned/hired/non-owned autos in USA; limit_source: total sum insured",
        "evidence_page": 8,
        "evidence_quote": "The insurance covers ... in excess of USD 1,000,000 ...",
        "confidence": "high",
        "limit_evidence": {"evidence_page": 3, "evidence_quote": "Total Sum Insured EUR 25,000,000 per occurrence", "confidence": "high"},
    },
    "field_evidence": {
        "geography_us": {"evidence_page": 2, "evidence_quote": "Geographical scope: World Wide", "confidence": "high"},
        "has_excess_auto_liability": {"evidence_page": 8, "evidence_quote": "...", "confidence": "high"},
    },
    "offshore_indicators": None,   # reserved for Q2
    "layer": None,                 # reserved for Q3
}

# Top-level keys the chunk JSON must contain (values may be null).
EXTRACTION_REQUIRED_KEYS = [
    "policy_no", "client_no", "policyholder", "policy_period_start", "policy_period_end",
    "document_language", "product_line", "cover_summary", "geography_scope", "geography_us",
    "has_excess_auto_liability", "excess_auto", "field_evidence",
]

EVIDENCE_KEYS = ("evidence_page", "evidence_quote", "confidence")


class ExtractionValidationError(ValueError):
    """Raised when a chunk result does not conform to s7.1 (FR-2: retry once, then record)."""


def _check_evidence(name: str, ev: Any, first_page: int, last_page: int) -> None:
    if ev is None:
        return
    if not isinstance(ev, dict):
        raise ExtractionValidationError(f"{name}: evidence must be an object")
    page = ev.get("evidence_page")
    if page is not None and not isinstance(page, int):
        raise ExtractionValidationError(f"{name}: evidence_page must be an integer")
    if page is not None and not (first_page <= page <= last_page):
        raise ExtractionValidationError(f"{name}: evidence_page {page} outside chunk {first_page}-{last_page}")
    conf = ev.get("confidence")
    if conf is not None and conf not in CONFIDENCE_LEVELS:
        raise ExtractionValidationError(f"{name}: confidence {conf!r} not in {sorted(CONFIDENCE_LEVELS)}")
    quote = ev.get("evidence_quote")
    if quote is not None and not isinstance(quote, str):
        raise ExtractionValidationError(f"{name}: evidence_quote must be a string")


def _coerce_null_strings(value: Any) -> Any:
    """The model sometimes writes the JSON string "null" where it means null
    (seen for `excess_auto` and `policyholder`). Normalise recursively."""
    if isinstance(value, str):
        return None if value.strip().lower() in ("null", "none") else value
    if isinstance(value, dict):
        return {k: _coerce_null_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce_null_strings(v) for v in value]
    return value


def validate_extraction(obj: Any, first_page: int, last_page: int) -> dict[str, Any]:
    """Type-check a parsed chunk result. Returns a normalised copy (string "null" -> None) on success."""
    if not isinstance(obj, dict):
        raise ExtractionValidationError("top level is not a JSON object")
    obj = _coerce_null_strings(obj)
    missing = [k for k in EXTRACTION_REQUIRED_KEYS if k not in obj]
    if missing:
        raise ExtractionValidationError(f"missing keys: {missing}")
    for key in ("geography_us", "has_excess_auto_liability"):
        if obj[key] is not None and not isinstance(obj[key], bool):
            raise ExtractionValidationError(f"{key} must be boolean or null")
    ea = obj.get("excess_auto")
    if ea is not None:
        if not isinstance(ea, dict):
            raise ExtractionValidationError("excess_auto must be an object or null")
        for amt in ("attachment_point_amount", "limit_amount"):
            if ea.get(amt) is not None and not isinstance(ea[amt], (int, float)):
                raise ExtractionValidationError(f"excess_auto.{amt} must be a number or null")
        _check_evidence("excess_auto", ea, first_page, last_page)
        _check_evidence("excess_auto.limit_evidence", ea.get("limit_evidence"), first_page, last_page)
    fe = obj.get("field_evidence")
    if fe is not None:
        if not isinstance(fe, dict):
            raise ExtractionValidationError("field_evidence must be an object or null")
        for name, ev in fe.items():
            _check_evidence(f"field_evidence.{name}", ev, first_page, last_page)
    return obj
