"""Headless `claude -p` wrapper (PRD F4/F5, s8 observability).

Why the CLI and not the SDK: the build machine has no API key, only a
Claude Code subscription. The same prompts run unchanged on the Anthropic
API / Batch API in production (PRD s10, Stage 2).

`run_claude()` returns a `ClaudeResult` with the raw text, the parsed JSON (if
any) and the metrics (`duration_ms`, tokens, `cost_usd`, `num_turns`, `model`)
that feed `ingest_metrics` and the query log.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import config


DEFAULT_SYSTEM_PROMPT = (
    "You are a precise document-analysis assistant for an insurance company. "
    "Follow the user's instructions exactly and return only what is asked for."
)


class ClaudeCLIError(RuntimeError):
    """Non-zero exit, timeout, or unparseable envelope from `claude -p`."""


@dataclass
class ClaudeResult:
    text: str                                    # model's final text ("result")
    data: Any | None                             # parsed JSON payload, if any
    metrics: dict[str, Any] = field(default_factory=dict)
    envelope: dict[str, Any] = field(default_factory=dict)   # full --output-format json object
    stderr: str = ""


_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


def strip_fences(text: str) -> str:
    """Remove a single surrounding ```json fence if the model added one."""
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text.strip()


def parse_json_payload(text: str) -> Any:
    """Parse JSON from model text: exact, fence-stripped, or first {...} block."""
    for candidate in (text, strip_fences(text)):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise json.JSONDecodeError("no JSON object found in model output", text, 0)


def _dominant_model(model_usage: dict[str, Any]) -> str | None:
    """The model that did the work, not whichever key happens to come first.

    `claude -p` reports every model the CLI touched: a small auxiliary call (Haiku,
    fractions of a cent) sits alongside the model that actually ran the extraction.
    `next(iter(...))` picked the auxiliary one, mislabelling the run and every cost
    figure derived from it -- and labelling the model is the whole point of the
    measured row on the Scale tab (PRD F16). Rank by cost, fall back to tokens.
    """
    def weight(usage: Any) -> tuple[float, float]:
        usage = usage if isinstance(usage, dict) else {}
        return (usage.get("costUSD") or 0,
                (usage.get("inputTokens") or 0) + (usage.get("outputTokens") or 0))

    return max(model_usage, key=lambda name: weight(model_usage[name])) if model_usage else None


def _metrics_from_envelope(env: dict[str, Any]) -> dict[str, Any]:
    usage = env.get("usage") or {}
    model_usage = env.get("modelUsage") or {}
    model = _dominant_model(model_usage) if isinstance(model_usage, dict) else None
    return {
        "duration_ms": env.get("duration_ms"),
        "duration_api_ms": env.get("duration_api_ms"),
        "input_tokens": (usage.get("input_tokens") or 0)
                        + (usage.get("cache_creation_input_tokens") or 0)
                        + (usage.get("cache_read_input_tokens") or 0),
        "output_tokens": usage.get("output_tokens"),
        "cost_usd": env.get("total_cost_usd"),
        "num_turns": env.get("num_turns"),
        "model": model,
        "session_id": env.get("session_id"),
        "is_error": env.get("is_error", False),
    }


def build_command(prompt: str, *, system_prompt: str | None = None, model: str | None = None,
                  tools: Sequence[str] | None = None, json_schema: dict[str, Any] | None = None,
                  max_turns: int | None = None, add_dirs: Sequence[Path] | None = None,
                  effort: str | None = None) -> list[str]:
    # The prompt itself is NOT on the command line: it is piped to stdin by `run_claude`
    # (multi-line prompts and Windows command-line quoting/length limits do not mix).
    cmd = [config.CLAUDE_BIN, "-p", "--output-format", "json", "--no-session-persistence",
           "--model", model or config.MODEL]
    # Replace Claude Code's coding-agent system prompt (~10k tokens) with a minimal one so the
    # measured tokens/cost reflect the extraction work itself (PRD s8 observability).
    cmd += ["--system-prompt", system_prompt or DEFAULT_SYSTEM_PROMPT]
    # `--tools ""` disables every built-in tool (query-time calls); ingestion passes ["Read"].
    cmd += ["--tools", *(tools if tools else [""])]
    if tools:
        cmd += ["--allowedTools", *tools]
    if json_schema:
        cmd += ["--json-schema", json.dumps(json_schema)]
    if max_turns is not None:
        cmd += ["--max-turns", str(max_turns)]
    if add_dirs:
        cmd += ["--add-dir", *[str(d) for d in add_dirs]]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def run_claude(prompt: str, *, expect_json: bool = True, retries: int = config.CLI_RETRIES,
               timeout_s: int = config.CLI_TIMEOUT_S, **kwargs: Any) -> ClaudeResult:
    """Run one headless call. Retries transient CLI failures with backoff.

    A JSON parse failure of the *payload* is NOT retried here - that is the
    caller's decision (FR-2: extraction retries once, then records failure).
    """
    cmd = build_command(prompt, **kwargs)
    env = os.environ.copy()
    # Running from inside another Claude Code session must not be treated as nesting.
    env.pop("CLAUDECODE", None)
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        started = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=timeout_s, env=env, cwd=config.ROOT_DIR,
            )
        except subprocess.TimeoutExpired:
            last_err = ClaudeCLIError(f"claude -p timed out after {timeout_s}s")
            _backoff(attempt)
            continue
        wall_ms = int((time.monotonic() - started) * 1000)
        if proc.returncode != 0:
            last_err = ClaudeCLIError(f"claude -p exit {proc.returncode}: {proc.stderr.strip()[:500]}")
            _backoff(attempt)
            continue
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            last_err = ClaudeCLIError(f"envelope is not JSON: {proc.stdout[:200]!r}")
            _backoff(attempt)
            continue
        metrics = _metrics_from_envelope(envelope)
        metrics.setdefault("duration_ms", wall_ms)
        if envelope.get("is_error"):
            last_err = ClaudeCLIError(f"claude reported error: {envelope.get('result', '')[:500]}")
            _backoff(attempt)
            continue
        text = envelope.get("result") or ""
        data: Any | None = None
        if expect_json:
            # `--json-schema` puts the validated object in structured_output; otherwise parse text.
            if envelope.get("structured_output") is not None:
                data = envelope["structured_output"]
            else:
                try:
                    data = parse_json_payload(text)
                except json.JSONDecodeError:
                    data = None
        return ClaudeResult(text=text, data=data, metrics=metrics, envelope=envelope, stderr=proc.stderr)
    assert last_err is not None
    raise last_err


def _backoff(attempt: int) -> None:
    time.sleep(min(2 ** attempt * 2, 30))
