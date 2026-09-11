"""PDF -> page PNGs (FR-1).

Text PDFs and scans go through the same path on purpose: one code path to
maintain, and the page images are needed by the evidence view anyway (G3).
"""

from __future__ import annotations

import threading
from pathlib import Path

import pypdfium2 as pdfium

import config

# PDFium is not thread-safe: concurrent PdfDocument use from the ingest thread pool
# fails with "Data format error". All PDFium calls go through this lock.
_PDFIUM_LOCK = threading.Lock()


def page_image_path(doc_id: str, page: int) -> Path:
    """1-based page number -> data/pages/<doc_id>/p<N>.png"""
    return config.PAGES_DIR / doc_id / f"p{page}.png"


def page_count(pdf_path: Path) -> int:
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            return len(pdf)
        finally:
            pdf.close()


def rasterise(pdf_path: Path, doc_id: str, scale: float = config.RENDER_SCALE,
              max_pages: int | None = None, force: bool = False) -> list[Path]:
    """Render every page (or the first `max_pages`) to PNG. Returns paths in page order.

    Skips pages whose PNG already exists unless `force`, so re-running ingestion
    on a partially processed corpus is cheap.
    """
    out_dir = config.PAGES_DIR / doc_id
    out_dir.mkdir(parents=True, exist_ok=True)
    with _PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            n = len(pdf) if max_pages is None else min(len(pdf), max_pages)
            paths: list[Path] = []
            for i in range(n):
                out = page_image_path(doc_id, i + 1)
                if force or not out.exists():
                    page = pdf[i]
                    bitmap = page.render(scale=scale)
                    image = bitmap.to_pil()
                    image.save(out, format="PNG")
                    page.close()
                paths.append(out)
            return paths
        finally:
            pdf.close()
