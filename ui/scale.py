"""Scale & cost maths for the Scale tab (FR-8, PRD s10).

Measured numbers come from `ingest_metrics`; the extrapolation is pure
arithmetic over editable assumptions so the jury can change any input.
"""

from __future__ import annotations

import statistics
from typing import Any

import config


def measured(summary: dict[str, Any]) -> dict[str, Any]:
    """Per-document statistics from `db.ingestion_summary()`."""
    per_doc = [d for d in summary["per_doc"] if d.get("ms")]
    secs = sorted((d["ms"] or 0) / 1000 for d in per_doc)
    tin = [d["tin"] or 0 for d in per_doc]
    tout = [d["tout"] or 0 for d in per_doc]
    cost = [d["cost"] or 0 for d in per_doc]
    pages = summary["page_counts"]

    def pct(xs: list[float], p: float) -> float | None:
        if not xs:
            return None
        k = max(0, min(len(xs) - 1, round(p * (len(xs) - 1))))
        return xs[k]

    return {
        "documents": summary["documents"],
        "pages": summary["pages"],
        "pages_median": statistics.median(pages) if pages else None,
        "pages_mean": statistics.fmean(pages) if pages else None,
        "secs_p50": pct(secs, 0.5),
        "secs_p95": pct(secs, 0.95),
        "secs_mean": statistics.fmean(secs) if secs else None,
        "input_tokens_per_doc": statistics.fmean(tin) if tin else None,
        "output_tokens_per_doc": statistics.fmean(tout) if tout else None,
        "cost_per_doc": statistics.fmean(cost) if cost else None,
        "cost_total": sum(cost),
    }


def extrapolate(a: dict[str, Any], model: str, measured_cost_per_doc: float | None = None) -> dict[str, Any]:
    """Cost envelope for the corpus under assumptions `a` (keys as in config.SCALE_DEFAULTS)."""
    price_in, price_out = config.MODEL_PRICES_PER_MTOK[model]
    docs = a["corpus_documents"] * a["prefilter_share"]
    pages = docs * a["avg_pages_per_doc"]

    # Prototype path: vision reading of every page image, scan or not.
    tokens_in_vision = a["avg_pages_per_doc"] * a["tokens_per_page_image"]
    cost_vision_doc = (tokens_in_vision * price_in + a["output_tokens_per_doc"] * price_out) / 1e6
    cost_vision_doc *= (1 - a["batch_discount"])

    # Production path (Stage 1+2): text PDFs give up their text layer for free;
    # only the scanned share is OCR'd. Extraction is then text-only for every document.
    tokens_in_text = a["avg_pages_per_doc"] * a["text_tokens_per_page"]
    cost_text_doc = (tokens_in_text * price_in + a["output_tokens_per_doc"] * price_out) / 1e6
    cost_text_doc *= (1 - a["batch_discount"])
    cost_ocr_scan = a["avg_pages_per_doc"] * a["ocr_cost_per_1000_pages"] / 1000   # per scanned doc
    cost_ocr_doc = cost_ocr_scan * a["scan_share"]                                  # averaged over the corpus

    return {
        "documents_read": docs,
        "pages_read": pages,
        "scanned_documents": docs * a["scan_share"],
        "vision": {"per_doc": cost_vision_doc, "total": cost_vision_doc * docs,
                   "tokens_per_doc": tokens_in_vision + a["output_tokens_per_doc"]},
        "ocr_text": {"ocr_per_doc": cost_ocr_doc, "ocr_per_scanned_doc": cost_ocr_scan,
                     "llm_per_doc": cost_text_doc,
                     "tokens_per_doc": tokens_in_text + a["output_tokens_per_doc"],
                     "ocr_total": cost_ocr_doc * docs, "llm_total": cost_text_doc * docs,
                     "total": (cost_ocr_doc + cost_text_doc) * docs},
        "measured": None if measured_cost_per_doc is None else {
            "per_doc": measured_cost_per_doc,
            "total": measured_cost_per_doc * docs * (1 - a["batch_discount"]),
        },
    }


def fmt_usd(x: float | None) -> str:
    if x is None:
        return "–"
    if x >= 1e6:
        return f"${x / 1e6:,.1f} M"
    if x >= 1e3:
        return f"${x / 1e3:,.1f} k"
    if x >= 1:
        return f"${x:,.2f}"
    return f"${x:.4f}"
