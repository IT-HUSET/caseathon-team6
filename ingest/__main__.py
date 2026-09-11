"""CLI entry point:  uv run --native-tls python -m ingest [options]

Walks the corpus, rasterises pages, extracts facts with `claude -p`, writes the
SQLite index. Idempotent by file hash; `--force` re-ingests.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

import config
from ingest.pipeline import ingest_corpus


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingest", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", type=Path, default=config.EXAMPLES_DIR, help="folder to walk for *.pdf")
    ap.add_argument("--force", action="store_true", help="re-ingest documents already in the index")
    ap.add_argument("--concurrency", type=int, default=config.CONCURRENCY, help="parallel claude -p processes")
    ap.add_argument("--max-pages", type=int, default=None, help="only read the first N pages of each document")
    ap.add_argument("--limit", type=int, default=None, help="only process the first N PDFs (smoke test)")
    ap.add_argument("--only", action="append", default=None, metavar="SUBSTR",
                    help="only PDFs whose path contains SUBSTR (repeatable), e.g. --only 2025.12.12")
    ap.add_argument("--model", default=None, help=f"claude model (default {config.MODEL})")
    ap.add_argument("--dry-run", action="store_true", help="rasterise and register documents; skip Claude")
    ap.add_argument("--reparse", action="store_true",
                    help="rebuild facts/evidence from stored raw JSON (no Claude calls); ignores other options")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    if args.reparse:
        from ingest.reparse import reparse_all
        results = reparse_all()
        counts = {s: sum(v == s for v in results.values()) for s in ("ok", "partial", "failed")}
        print(f"reparsed {len(results)} document(s): " + ", ".join(f"{k}={v}" for k, v in counts.items()))
        return 0

    started = time.monotonic()
    outcomes = ingest_corpus(args.root, concurrency=args.concurrency, force=args.force,
                             max_pages=args.max_pages, dry_run=args.dry_run, limit=args.limit,
                             only=args.only, model=args.model)
    elapsed = time.monotonic() - started

    width = max((len(o.doc_id) for o in outcomes), default=10)
    for o in outcomes:
        extra = f"  {o.error}" if o.error and o.status != "skipped" else ""
        print(f"{o.status:8} {o.doc_id:{width}} pages={o.pages:<3} chunks ok/failed={o.chunks_ok}/{o.chunks_failed}{extra}")
    counts = {s: sum(o.status == s for o in outcomes) for s in ("ok", "partial", "failed", "skipped")}
    print(f"\n{len(outcomes)} document(s) in {elapsed:.1f}s: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"index: {config.DB_PATH}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
