"""Evidence panel (FR-5): page image + verbatim quote + field + confidence.

Quotes are rendered as text (st.code / st.text), never as HTML (PRD s8).
"""

from __future__ import annotations

import json
import sqlite3

import streamlit as st

from index import db
from ingest.rasterise import page_image_path

FIELD_LABELS = {
    "geography_us": "Cover applies in the US",
    "has_excess_auto": "Has excess auto liability",
    "excess_auto": "Excess auto: attachment point",
    "excess_auto_limit": "Excess auto: limit",
}

CONFIDENCE_ICON = {"high": "🟢", "medium": "🟡", "low": "🔴", None: "⚪"}


def render(conn: sqlite3.Connection, doc_id: str) -> None:
    doc = conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
    facts = conn.execute("SELECT * FROM policy_facts WHERE doc_id = ?", (doc_id,)).fetchone()
    if doc is None:
        st.warning("Document not found in the index.")
        return

    st.subheader(facts["policy_no"] if facts and facts["policy_no"] else doc_id)
    st.caption(f"{doc['path']} · {doc['pages']} page(s) · status: {doc['status']}")
    if facts and facts["needs_review"]:
        reasons = json.loads(facts["review_reasons"] or "[]")
        st.warning("**Needs review** — " + "; ".join(reasons))

    rows = db.evidence_for_document(conn, doc_id)
    if not rows:
        st.info("No evidenced values for this document.")
        return

    labels = [f"{CONFIDENCE_ICON.get(r['confidence'])} {FIELD_LABELS.get(r['field'], r['field'])} — p. {r['page']}"
              for r in rows]
    choice = st.radio("Evidenced value", labels, key=f"ev-{doc_id}", label_visibility="collapsed")
    row = rows[labels.index(choice)]

    img_col, quote_col = st.columns([3, 2])
    with quote_col:
        st.markdown(f"**Field:** {FIELD_LABELS.get(row['field'], row['field'])}")
        st.markdown(f"**Page:** {row['page']}  ·  **Confidence:** {row['confidence'] or 'n/a'}")
        st.markdown("**Verbatim quote:**")
        st.code(row["quote"] or "(no quote recorded)", language=None, wrap_lines=True)
        if row["field"] in ("excess_auto", "excess_auto_limit") and facts:
            st.markdown(
                f"Attachment point: **{facts['ea_attachment_amount'] or '–'} {facts['ea_attachment_currency'] or ''}**  \n"
                f"Limit: **{facts['ea_limit_amount'] or '–'} {facts['ea_limit_currency'] or ''}**  \n"
                f"Basis: {facts['ea_basis'] or '–'}"
            )
    with img_col:
        if row["page"]:
            img = page_image_path(doc_id, row["page"])
            if img.exists():
                # FR-6 (stretch): draw bbox_json here when present.
                st.image(str(img), caption=f"{doc['path']} — page {row['page']}", use_container_width=True)
            else:
                st.info(f"Page image missing: {img}")
        else:
            st.info("No page recorded for this value.")
