"""SQLite access layer (PRD s7.2).

Single-file database at `config.DB_PATH`. Schema is created on first connect
and is idempotent, so both the ingest CLI and the Streamlit app can call
`connect()` without coordination.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id       TEXT PRIMARY KEY,
    path         TEXT NOT NULL,
    file_hash    TEXT NOT NULL,
    pages        INTEGER,
    ingested_at  TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',   -- pending | ok | partial | failed
    error        TEXT
);

CREATE TABLE IF NOT EXISTS policy_facts (
    doc_id                  TEXT PRIMARY KEY REFERENCES documents(doc_id) ON DELETE CASCADE,
    policy_no               TEXT,
    client_no               TEXT,
    policyholder            TEXT,
    period_start            TEXT,
    period_end              TEXT,
    language                TEXT,
    product_line            TEXT,
    geography_scope         TEXT,
    geography_us            INTEGER,                -- 1 / 0 / NULL
    has_excess_auto         INTEGER,                -- 1 / 0 / NULL
    ea_attachment_amount    REAL,
    ea_attachment_currency  TEXT,
    ea_limit_amount         REAL,
    ea_limit_currency       TEXT,
    ea_basis                TEXT,
    ea_notes                TEXT,
    ea_us_restriction       TEXT,                   -- restriction on US excess auto cover, as worded; NULL = unrestricted
    needs_review            INTEGER NOT NULL DEFAULT 0,
    review_reasons          TEXT                    -- JSON list of strings
);

CREATE TABLE IF NOT EXISTS evidence (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id      TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    field       TEXT NOT NULL,
    page        INTEGER,
    quote       TEXT,
    confidence  TEXT,                                -- high | medium | low
    bbox_json   TEXT                                 -- FR-6 stretch, normally NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_doc ON evidence(doc_id);

CREATE TABLE IF NOT EXISTS ingest_metrics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    pages_in_chunk  INTEGER NOT NULL,
    duration_ms     INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        REAL,
    num_turns       INTEGER,
    model           TEXT,
    status          TEXT                             -- ok | extraction_failed | cli_failed
);

CREATE TABLE IF NOT EXISTS query_cache (
    question_norm  TEXT PRIMARY KEY,
    question       TEXT NOT NULL,
    query_json     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    hits           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS raw_extractions (
    doc_id       TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    json         TEXT,
    PRIMARY KEY (doc_id, chunk_index)
);
"""

FACT_COLUMNS = [
    "policy_no", "client_no", "policyholder", "period_start", "period_end", "language",
    "product_line", "geography_scope", "geography_us", "has_excess_auto",
    "ea_attachment_amount", "ea_attachment_currency", "ea_limit_amount", "ea_limit_currency",
    "ea_basis", "ea_notes", "ea_us_restriction", "needs_review", "review_reasons",
]

# Columns added after the first release; applied to existing databases on connect().
MIGRATIONS = [
    ("policy_facts", "ea_us_restriction", "ALTER TABLE policy_facts ADD COLUMN ea_us_restriction TEXT"),
]


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    """Open (and initialise) the index. Rows come back as `sqlite3.Row`."""
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass  # another worker is switching the mode right now; the default journal is fine
    conn.executescript(SCHEMA)
    for table, column, ddl in MIGRATIONS:
        if column not in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}:
            conn.execute(ddl)
    conn.commit()
    return conn


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- documents ---------------------------------------------------------------

def get_document_by_hash(conn: sqlite3.Connection, file_hash: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM documents WHERE file_hash = ?", (file_hash,)).fetchone()


def upsert_document(conn: sqlite3.Connection, doc_id: str, path: str, file_hash: str,
                    pages: int | None, status: str, error: str | None = None) -> None:
    conn.execute(
        """INSERT INTO documents (doc_id, path, file_hash, pages, ingested_at, status, error)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(doc_id) DO UPDATE SET
             path=excluded.path, file_hash=excluded.file_hash, pages=excluded.pages,
             ingested_at=excluded.ingested_at, status=excluded.status, error=excluded.error""",
        (doc_id, path, file_hash, pages, utcnow(), status, error),
    )
    conn.commit()


def delete_document(conn: sqlite3.Connection, doc_id: str) -> None:
    """Remove a document and (via cascade) its facts, evidence, metrics and raw JSON."""
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
    conn.commit()


# --- facts / evidence --------------------------------------------------------

def replace_policy_facts(conn: sqlite3.Connection, doc_id: str, facts: dict[str, Any],
                         evidence: Iterable[dict[str, Any]]) -> None:
    """Write the merged per-document record. Replaces any previous facts/evidence."""
    values = [facts.get(c) for c in FACT_COLUMNS]
    if isinstance(facts.get("review_reasons"), list):
        values[FACT_COLUMNS.index("review_reasons")] = json.dumps(facts["review_reasons"])
    placeholders = ", ".join("?" for _ in FACT_COLUMNS)
    conn.execute("DELETE FROM policy_facts WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM evidence WHERE doc_id = ?", (doc_id,))
    conn.execute(
        f"INSERT INTO policy_facts (doc_id, {', '.join(FACT_COLUMNS)}) VALUES (?, {placeholders})",
        [doc_id, *values],
    )
    conn.executemany(
        "INSERT INTO evidence (doc_id, field, page, quote, confidence, bbox_json) VALUES (?, ?, ?, ?, ?, ?)",
        [(doc_id, e["field"], e.get("page"), e.get("quote"), e.get("confidence"),
          json.dumps(e["bbox"]) if e.get("bbox") else None) for e in evidence],
    )
    conn.commit()


def record_metric(conn: sqlite3.Connection, doc_id: str, chunk_index: int, pages_in_chunk: int,
                  metrics: dict[str, Any], status: str) -> None:
    conn.execute(
        """INSERT INTO ingest_metrics
           (doc_id, chunk_index, pages_in_chunk, duration_ms, input_tokens, output_tokens,
            cost_usd, num_turns, model, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (doc_id, chunk_index, pages_in_chunk, metrics.get("duration_ms"), metrics.get("input_tokens"),
         metrics.get("output_tokens"), metrics.get("cost_usd"), metrics.get("num_turns"),
         metrics.get("model"), status),
    )
    conn.commit()


def save_raw_extraction(conn: sqlite3.Connection, doc_id: str, chunk_index: int, raw: str | None) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO raw_extractions (doc_id, chunk_index, json) VALUES (?, ?, ?)",
        (doc_id, chunk_index, raw),
    )
    conn.commit()


def clear_chunk_data(conn: sqlite3.Connection, doc_id: str) -> None:
    conn.execute("DELETE FROM ingest_metrics WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM raw_extractions WHERE doc_id = ?", (doc_id,))
    conn.commit()


# --- query cache (FR-3 latency) ---------------------------------------------

def normalise_question(question: str) -> str:
    """Cache key: trimmed, lower-cased, whitespace collapsed, trailing punctuation removed."""
    q = re.sub(r"\s+", " ", question.strip().lower())
    return q.rstrip(" .?!,;:")


def cache_get(conn: sqlite3.Connection, question: str) -> str | None:
    """Return the cached query JSON (and count the hit), or None."""
    key = normalise_question(question)
    row = conn.execute("SELECT query_json FROM query_cache WHERE question_norm = ?", (key,)).fetchone()
    if row is None:
        return None
    conn.execute("UPDATE query_cache SET hits = hits + 1 WHERE question_norm = ?", (key,))
    conn.commit()
    return row["query_json"]


def cache_put(conn: sqlite3.Connection, question: str, query_json: str) -> None:
    conn.execute(
        """INSERT INTO query_cache (question_norm, question, query_json, created_at, hits)
           VALUES (?, ?, ?, ?, 0)
           ON CONFLICT(question_norm) DO UPDATE SET query_json = excluded.query_json, created_at = excluded.created_at""",
        (normalise_question(question), question.strip(), query_json, utcnow()),
    )
    conn.commit()


def cache_delete(conn: sqlite3.Connection, question: str) -> None:
    conn.execute("DELETE FROM query_cache WHERE question_norm = ?", (normalise_question(question),))
    conn.commit()


# --- read side (UI / eval) ---------------------------------------------------

def evidence_for_document(conn: sqlite3.Connection, doc_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM evidence WHERE doc_id = ? ORDER BY page, field", (doc_id,)
    ).fetchall()


def all_facts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT d.doc_id, d.path, d.pages, d.status, d.error, f.*
           FROM documents d LEFT JOIN policy_facts f USING (doc_id)
           ORDER BY d.path"""
    ).fetchall()


def ingestion_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Aggregates for the Scale tab (FR-8). Cheap enough to run on every render."""
    docs = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(pages), 0) AS pages FROM documents WHERE status IN ('ok','partial')"
    ).fetchone()
    per_doc = conn.execute(
        """SELECT doc_id, SUM(duration_ms) AS ms, SUM(input_tokens) AS tin,
                  SUM(output_tokens) AS tout, SUM(cost_usd) AS cost
           FROM ingest_metrics GROUP BY doc_id"""
    ).fetchall()
    page_counts = [r["pages"] for r in conn.execute(
        "SELECT pages FROM documents WHERE pages IS NOT NULL"
    ).fetchall()]
    return {
        "documents": docs["n"],
        "pages": docs["pages"],
        "page_counts": page_counts,
        "per_doc": [dict(r) for r in per_doc],
    }
