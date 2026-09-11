"""Central configuration for Policy Insight.

Plain constants with environment overrides so the ingest CLI, the query layer
and the Streamlit app agree on paths and defaults.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

# --- Inputs -----------------------------------------------------------------
EXAMPLES_DIR = ROOT_DIR / "docs" / "examples"

# --- Outputs (gitignored) ---------------------------------------------------
DATA_DIR = ROOT_DIR / "data"
PAGES_DIR = DATA_DIR / "pages"          # data/pages/<doc_id>/p<N>.png
DB_PATH = DATA_DIR / "index.sqlite"
QUERY_LOG_PATH = DATA_DIR / "query_log.jsonl"

# --- Rasterisation (FR-1) ---------------------------------------------------
RENDER_SCALE = float(os.environ.get("PI_RENDER_SCALE", "2.0"))   # A4 -> ~1,190 px wide (PRD target ~1,200 px)

# --- Extraction (FR-1 / FR-2) -----------------------------------------------
CHUNK_PAGES = int(os.environ.get("PI_CHUNK_PAGES", "15"))       # max pages per claude -p call
CONCURRENCY = int(os.environ.get("PI_CONCURRENCY", "3"))        # parallel claude -p processes
CLI_RETRIES = 2                                                  # transient CLI failures
PARSE_RETRIES = 1                                                # invalid JSON -> retry once (FR-2)

# --- Claude CLI (F4: headless `claude -p`, no API key on this machine) ------
# Resolved to the full executable path so subprocess needs no shell (see ingest/claude_cli.py).
CLAUDE_BIN = shutil.which(os.environ.get("PI_CLAUDE_BIN", "claude")) or "claude"
# PRD s10 prices the prototype path with Sonnet 5; override with PI_MODEL (e.g. claude-opus-5).
MODEL = os.environ.get("PI_MODEL", "claude-sonnet-5")
CLI_TIMEOUT_S = int(os.environ.get("PI_CLI_TIMEOUT_S", "600"))

# --- Scale tab defaults (PRD s10; list prices Sept 2026 - re-check before use) ---
SCALE_DEFAULTS = {
    "corpus_documents": 200_000_000,
    "avg_pages_per_doc": 8.0,
    "tokens_per_page_image": 1_500,
    "output_tokens_per_doc": 400,
    "batch_discount": 0.5,
    "prefilter_share": 1.0,          # share of corpus that passes Stage 0 triage
    "ocr_cost_per_1000_pages": 1.5,
    "text_tokens_per_doc": 4_000,    # Stage 1+2 path: OCR text instead of images
}

MODEL_PRICES_PER_MTOK = {            # (input, output) USD per 1M tokens
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
