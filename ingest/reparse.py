"""Rebuild policy_facts/evidence from stored raw JSON - no Claude calls (PRD s11 mitigation).

Use after changing merge rules, review-flag logic or the schema validator:

    uv run --native-tls python -m ingest --reparse
"""

from __future__ import annotations

import json
import logging

from index import db
from index.schema import ExtractionValidationError, validate_extraction
from ingest.claude_cli import parse_json_payload
from ingest.extract import ChunkResult
from ingest.merge import merge_chunks

log = logging.getLogger("ingest")


def reparse_document(conn, doc_id: str) -> str:
    """Re-validate and re-merge one document. Returns the new document status."""
    raws = conn.execute(
        "SELECT chunk_index, json FROM raw_extractions WHERE doc_id = ? ORDER BY chunk_index", (doc_id,)
    ).fetchall()
    metrics = {r["chunk_index"]: r for r in conn.execute(
        "SELECT chunk_index, pages_in_chunk FROM ingest_metrics WHERE doc_id = ?", (doc_id,)
    ).fetchall()}
    chunks: list[ChunkResult] = []
    first = 1
    for r in raws:
        pages = metrics[r["chunk_index"]]["pages_in_chunk"] if r["chunk_index"] in metrics else 1
        last = first + pages - 1
        chunk = ChunkResult(r["chunk_index"], first, last, status="extraction_failed", raw_text=r["json"])
        try:
            chunk.data = validate_extraction(parse_json_payload(r["json"] or ""), first, last)
            chunk.status = "ok"
        except (json.JSONDecodeError, ExtractionValidationError) as e:
            chunk.error = str(e)
        chunks.append(chunk)
        first = last + 1

    facts, evidence = merge_chunks(chunks)
    db.replace_policy_facts(conn, doc_id, facts, evidence)
    n_ok = sum(c.status == "ok" for c in chunks)
    status = "ok" if n_ok == len(chunks) and chunks else ("partial" if n_ok else "failed")
    conn.execute("UPDATE documents SET status = ? WHERE doc_id = ?", (status, doc_id))
    conn.commit()
    return status


def reparse_all() -> dict[str, str]:
    conn = db.connect()
    try:
        # Skip 'pending' documents: another ingest process may be writing their chunks right now.
        ids = [r["doc_id"] for r in conn.execute(
            """SELECT DISTINCT r.doc_id FROM raw_extractions r JOIN documents d USING (doc_id)
               WHERE d.status != 'pending' ORDER BY r.doc_id"""
        ).fetchall()]
        out = {}
        for doc_id in ids:
            out[doc_id] = reparse_document(conn, doc_id)
            log.info("%s: reparsed -> %s", doc_id, out[doc_id])
        return out
    finally:
        conn.close()
