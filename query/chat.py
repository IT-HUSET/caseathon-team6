"""Follow-up chat over the current result set (FR-4).

Each turn sends the rows (with their evidence quotes), the conversation so far
and the new message. The answer is prose with citations; it may also carry a
`REFINE: {...}` line proposing new filters, which the UI validates before use.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from index import db
from index.schema import QUERY_FIELDS
from ingest.claude_cli import ClaudeCLIError, run_claude
from query.execute import InvalidQuery, Query, validate
from query.translate import log_query

PROMPT_PATH = Path(__file__).parent / "prompts" / "chat.md"
_REFINE_RE = re.compile(r"^REFINE:\s*(\{.*\})\s*$", re.MULTILINE | re.DOTALL)


@dataclass
class ChatTurn:
    role: str            # user | assistant
    content: str


@dataclass
class ChatAnswer:
    text: str
    refine: Query | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


def rows_with_evidence(conn: sqlite3.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach the evidence rows of each result row so the model can cite pages."""
    out = []
    for r in rows:
        item = dict(r)
        if r.get("doc_id"):
            item["evidence"] = [
                {"field": e["field"], "page": e["page"], "quote": e["quote"], "confidence": e["confidence"]}
                for e in db.evidence_for_document(conn, r["doc_id"])
            ]
        out.append(item)
    return out


def build_prompt(rows: list[dict[str, Any]], history: list[ChatTurn], question: str) -> str:
    hist = "\n".join(f"{t.role}: {t.content}" for t in history) or "(none)"
    return (PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{FIELDS}", ", ".join(QUERY_FIELDS))
            .replace("{ROWS}", json.dumps(rows, ensure_ascii=False, indent=1, default=str))
            .replace("{HISTORY}", hist)
            .replace("{QUESTION}", question.strip()))


def ask(conn: sqlite3.Connection, rows: list[dict[str, Any]], history: list[ChatTurn],
        question: str, model: str | None = None) -> ChatAnswer:
    prompt = build_prompt(rows_with_evidence(conn, rows), history, question)
    try:
        res = run_claude(prompt, expect_json=False, model=model, tools=None, max_turns=1, effort="medium")
    except ClaudeCLIError as e:
        log_query("chat", question, {"error": str(e)}, {})
        return ChatAnswer(text="", error=str(e))

    text, refine = res.text, None
    m = _REFINE_RE.search(text)
    if m:
        text = text[:m.start()].rstrip()
        try:
            refine = validate(json.loads(m.group(1)))
        except (json.JSONDecodeError, InvalidQuery):
            refine = None  # a bad refine proposal is dropped, the prose answer still stands
    log_query("chat", question, {"answer": text, "refine": m.group(1) if m else None}, res.metrics)
    return ChatAnswer(text=text, refine=refine, metrics=res.metrics)
