"""Per-chunk extraction: page PNGs -> validated s7.1 JSON (FR-2).

`extract_chunk()` builds the prompt, runs `claude -p`, parses defensively,
validates against the schema, retries once on invalid output, and returns a
`ChunkResult` that is *never* silently dropped: on failure `status` is
`extraction_failed` and the raw text is kept for debugging (`raw_extractions`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import config
from index.schema import (EXTRACTION_EXAMPLE, EXTRACTION_REQUIRED_KEYS,
                          ExtractionValidationError, validate_extraction)
from ingest.claude_cli import ClaudeCLIError, run_claude

PROMPT_PATH = Path(__file__).parent / "prompts" / "extraction.md"

# Loose structured-output schema: guarantees the top-level keys exist; the
# finer type checks stay in `validate_extraction` so error messages are ours.
EXTRACTION_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {k: {} for k in EXTRACTION_REQUIRED_KEYS + ["offshore_indicators", "layer"]},
    "required": EXTRACTION_REQUIRED_KEYS,
    "additionalProperties": True,
}


@dataclass
class ChunkResult:
    chunk_index: int
    first_page: int
    last_page: int
    status: str                                  # ok | extraction_failed | cli_failed
    data: dict[str, Any] | None = None
    raw_text: str | None = None
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def pages_in_chunk(self) -> int:
        return self.last_page - self.first_page + 1


def build_prompt(doc_name: str, page_paths: list[Path], first_page: int, total_pages: int) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    page_list = "\n".join(
        f"- page {first_page + i}: {p.resolve()}" for i, p in enumerate(page_paths)
    )
    return (template
            .replace("{EXAMPLE}", json.dumps(EXTRACTION_EXAMPLE, indent=2, ensure_ascii=False))
            .replace("{DOC_NAME}", doc_name)
            .replace("{FIRST_PAGE}", str(first_page))
            .replace("{LAST_PAGE}", str(first_page + len(page_paths) - 1))
            .replace("{TOTAL_PAGES}", str(total_pages))
            .replace("{PAGE_LIST}", page_list))


def chunk_pages(page_paths: list[Path], chunk_size: int = config.CHUNK_PAGES) -> list[tuple[int, list[Path]]]:
    """Split into (first_page_number, paths) tuples; page numbers are 1-based and absolute."""
    return [(i + 1, page_paths[i:i + chunk_size]) for i in range(0, len(page_paths), chunk_size)]


def extract_chunk(doc_name: str, chunk_index: int, first_page: int, page_paths: list[Path],
                  total_pages: int, model: str | None = None) -> ChunkResult:
    last_page = first_page + len(page_paths) - 1
    prompt = build_prompt(doc_name, page_paths, first_page, total_pages)
    result = ChunkResult(chunk_index, first_page, last_page, status="extraction_failed")

    for attempt in range(config.PARSE_RETRIES + 1):
        try:
            res = run_claude(
                prompt, model=model, tools=["Read"], json_schema=EXTRACTION_JSON_SCHEMA,
                max_turns=len(page_paths) + 5, add_dirs=[config.PAGES_DIR],
            )
        except ClaudeCLIError as e:
            result.status, result.error = "cli_failed", str(e)
            return result

        # Accumulate cost across a retry so the metrics reflect what was actually spent.
        for k in ("duration_ms", "input_tokens", "output_tokens", "cost_usd", "num_turns"):
            if res.metrics.get(k) is not None:
                result.metrics[k] = (result.metrics.get(k) or 0) + res.metrics[k]
        result.metrics["model"] = res.metrics.get("model") or model or config.MODEL
        result.raw_text = res.text

        if res.data is None:
            result.error = "model output is not JSON"
            continue
        try:
            result.data = validate_extraction(res.data, first_page, last_page)
        except ExtractionValidationError as e:
            result.error = f"schema validation: {e}"
            continue
        result.status, result.error = "ok", None
        return result
    return result
