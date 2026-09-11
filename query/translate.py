"""Natural-language question -> validated `Query` (FR-3).

One `claude -p` call with no tools and a fixed prompt (determinism, s8), then
`query.execute.validate` enforces the whitelist. Every call is appended to
`data/query_log.jsonl` with its metrics.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import config
from index.schema import schema_for_prompt
from ingest.claude_cli import ClaudeCLIError, run_claude
from query.execute import InvalidQuery, Query, validate

PROMPT_PATH = Path(__file__).parent / "prompts" / "translate.md"

TRANSLATE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "filters": {"type": "array"},
        "columns": {"type": "array", "items": {"type": "string"}},
        "group_by": {"type": ["string", "null"]},
        "aggregate": {"type": ["object", "null"]},
        "explanation": {"type": "string"},
        "unmappable": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "additionalProperties": True,
}


@dataclass
class Translation:
    query: Query | None            # None when unmappable / invalid
    unmappable_reason: str | None
    raw: Any
    metrics: dict[str, Any]


def build_prompt(question: str) -> str:
    return (PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{SCHEMA}", schema_for_prompt())
            .replace("{QUESTION}", question.strip()))


def log_query(kind: str, question: str, payload: Any, metrics: dict[str, Any]) -> None:
    config.QUERY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.QUERY_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"kind": kind, "question": question, "payload": payload,
                            "metrics": metrics}, ensure_ascii=False, default=str) + "\n")


def translate(question: str, model: str | None = None) -> Translation:
    try:
        res = run_claude(build_prompt(question), model=model, tools=None,
                         json_schema=TRANSLATE_JSON_SCHEMA, max_turns=1, effort="low")
    except ClaudeCLIError as e:
        log_query("translate", question, {"error": str(e)}, {})
        return Translation(None, f"Query translation failed: {e}", None, {})

    log_query("translate", question, res.data, res.metrics)
    if res.data is None:
        return Translation(None, "The model did not return a JSON query.", res.text, res.metrics)
    if res.data.get("unmappable"):
        return Translation(None, res.data.get("reason") or "Not answerable from the index.", res.data, res.metrics)
    try:
        return Translation(validate(res.data), None, res.data, res.metrics)
    except InvalidQuery as e:
        return Translation(None, f"The model proposed a query outside the schema: {e}", res.data, res.metrics)
