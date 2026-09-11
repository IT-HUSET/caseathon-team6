"""Per-document orchestration: hash -> rasterise -> extract chunks -> merge -> SQLite (FR-1).

`ingest_document()` is self-contained so it can run in a thread pool; each
call opens its own SQLite connection.
"""

from __future__ import annotations

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import config
from index import db
from ingest.extract import ChunkResult, chunk_pages, extract_chunk
from ingest.merge import merge_chunks
from ingest.rasterise import rasterise

log = logging.getLogger("ingest")


@dataclass
class IngestOutcome:
    doc_id: str
    path: Path
    status: str            # ok | partial | failed | skipped
    pages: int = 0
    chunks_ok: int = 0
    chunks_failed: int = 0
    error: str | None = None


def find_pdfs(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.pdf") if p.is_file())


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def make_doc_id(path: Path, root: Path) -> str:
    """Readable, filesystem-safe id from the path relative to the corpus root.

    'Offshore Projects/temp.lh.policy. 2020.06.02.pdf' -> 'offshore_projects__temp_lh_policy_2020_06_02'

    Files under docs/examples always get ids relative to that folder, so `--root <subfolder>`
    produces the same ids as a full run (the eval keys on them).
    """
    path = path.resolve()
    base = config.EXAMPLES_DIR.resolve() if path.is_relative_to(config.EXAMPLES_DIR.resolve()) else root.resolve()
    rel = path.relative_to(base).with_suffix("")
    parts = [re.sub(r"[^a-z0-9]+", "_", p.lower()).strip("_") for p in rel.parts]
    return "__".join(parts)


def ingest_document(pdf_path: Path, root: Path, *, force: bool = False,
                    max_pages: int | None = None, dry_run: bool = False,
                    model: str | None = None) -> IngestOutcome:
    doc_id = make_doc_id(pdf_path, root)
    conn = db.connect()
    try:
        digest = file_hash(pdf_path)
        existing = db.get_document_by_hash(conn, digest)
        if existing and existing["status"] in ("ok", "partial") and not force:
            return IngestOutcome(doc_id, pdf_path, "skipped", pages=existing["pages"] or 0)

        rel_path = str(pdf_path.relative_to(config.ROOT_DIR)) if pdf_path.is_relative_to(config.ROOT_DIR) else str(pdf_path)
        db.upsert_document(conn, doc_id, rel_path, digest, None, "pending")
        db.clear_chunk_data(conn, doc_id)

        page_paths = rasterise(pdf_path, doc_id, max_pages=max_pages, force=force)
        n_pages = len(page_paths)
        log.info("%s: %d page(s) rasterised", doc_id, n_pages)

        if dry_run:
            db.upsert_document(conn, doc_id, rel_path, digest, n_pages, "pending", "dry-run: no extraction")
            return IngestOutcome(doc_id, pdf_path, "skipped", pages=n_pages, error="dry-run")

        chunks: list[ChunkResult] = []
        for chunk_index, (first_page, paths) in enumerate(chunk_pages(page_paths)):
            res = extract_chunk(pdf_path.name, chunk_index, first_page, paths, n_pages, model=model)
            db.record_metric(conn, doc_id, chunk_index, res.pages_in_chunk, res.metrics, res.status)
            db.save_raw_extraction(conn, doc_id, chunk_index, res.raw_text)
            log.info("%s: chunk %d pages %d-%d -> %s%s", doc_id, chunk_index, first_page,
                     res.last_page, res.status, f" ({res.error})" if res.error else "")
            chunks.append(res)

        facts, evidence = merge_chunks(chunks)
        db.replace_policy_facts(conn, doc_id, facts, evidence)

        n_ok = sum(c.status == "ok" for c in chunks)
        n_failed = len(chunks) - n_ok
        status = "ok" if n_failed == 0 else ("partial" if n_ok else "failed")
        error = None if n_failed == 0 else "; ".join(c.error or c.status for c in chunks if c.status != "ok")
        db.upsert_document(conn, doc_id, rel_path, digest, n_pages, status, error)
        return IngestOutcome(doc_id, pdf_path, status, n_pages, n_ok, n_failed, error)
    except Exception as e:  # never let one document kill the run (FR-1 AC)
        log.exception("%s: unhandled error", doc_id)
        try:
            db.upsert_document(conn, doc_id, str(pdf_path), file_hash(pdf_path), None, "failed", repr(e))
        except Exception:
            pass
        return IngestOutcome(doc_id, pdf_path, "failed", error=repr(e))
    finally:
        conn.close()


def ingest_corpus(root: Path, *, concurrency: int = config.CONCURRENCY, force: bool = False,
                  max_pages: int | None = None, dry_run: bool = False, limit: int | None = None,
                  only: list[str] | None = None, model: str | None = None) -> list[IngestOutcome]:
    pdfs = find_pdfs(root)
    if only:
        pdfs = [p for p in pdfs if any(s.lower() in str(p).lower() for s in only)]
    pdfs = pdfs[:limit]
    log.info("%d PDF(s) under %s; concurrency=%d", len(pdfs), root, concurrency)
    outcomes: list[IngestOutcome] = []
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = {pool.submit(ingest_document, p, root, force=force, max_pages=max_pages,
                               dry_run=dry_run, model=model): p for p in pdfs}
        for fut in as_completed(futures):
            outcomes.append(fut.result())
    return sorted(outcomes, key=lambda o: str(o.path))
