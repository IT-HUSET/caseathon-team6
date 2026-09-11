"""Policy Insight — Streamlit UI.  Run:  uv run --native-tls streamlit run app.py

Tabs: Ask (question -> table + follow-up chat), Evidence (page image + quote),
Scale (measured cost/time -> 200M-document extrapolation), Index (what is loaded).
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

import config
from index import db
from index.schema import QUERY_FIELDS
from query import chat, translate
from query.execute import Query, execute
from ui import evidence, scale

st.set_page_config(page_title="Policy Insight", page_icon="📄", layout="wide")

DEMO_QUESTION = "Find all liability policies with excess auto cover in the United States. Show attachment point and limit."


@st.cache_resource
def get_conn():
    return db.connect()


conn = get_conn()
ss = st.session_state
ss.setdefault("query", None)          # current validated Query
ss.setdefault("result", None)         # current ResultSet
ss.setdefault("chat", [])             # list[chat.ChatTurn]
ss.setdefault("selected_doc", None)
ss.setdefault("notice", None)
ss.setdefault("cached", False)

st.title("Policy Insight")
st.caption("Natural-language questions over If Industrial policy documents — every value traceable to a page.")

tab_ask, tab_evidence, tab_scale, tab_index = st.tabs(["Ask", "Evidence", "Scale", "Index"])


def run_query(q: Query) -> None:
    ss.query = q
    ss.result = execute(conn, q)
    ss.chat = []


# --------------------------------------------------------------------------- Ask
with tab_ask:
    with st.form("ask"):
        question = st.text_input("Question", value=DEMO_QUESTION, help="English or Swedish")
        submitted = st.form_submit_button("Ask", type="primary")
    if submitted and question.strip():
        with st.spinner("Translating question…"):
            t = translate.translate(question)
        if t.query is None:
            ss.notice = t.unmappable_reason
            ss.query = ss.result = None
        else:
            ss.notice = None
            ss.cached = t.cached
            run_query(t.query)

    if ss.notice:
        st.error(f"Can't answer that from the index: {ss.notice}")
        with st.expander("What the index can answer"):
            st.table(pd.DataFrame(
                [{"field": k, "type": v[1], "meaning": v[2]} for k, v in QUERY_FIELDS.items()]
            ))

    if ss.result is not None:
        res = ss.result
        if res.explanation:
            st.markdown(f"*{res.explanation}*" + ("  ·  `cached translation`" if ss.cached else ""))
        df = pd.DataFrame(res.rows, columns=res.columns)

        if ss.query and not ss.query.is_aggregate:
            only_flagged = st.toggle("Show only rows that need review", value=False)
            if only_flagged and "needs_review" in df:
                df = df[df["needs_review"] == 1]
            st.caption(f"{len(df)} row(s). Flagged rows (⚠️) sort to the bottom. Select a row to open its evidence.")
            show = df.copy()
            if "needs_review" in show:
                show.insert(0, "review", show["needs_review"].map({1: "⚠️", 0: ""}))
                show = show.drop(columns=["needs_review"])
            event = st.dataframe(show, hide_index=True, use_container_width=True,
                                 on_select="rerun", selection_mode="single-row",
                                 column_config={"doc_id": None})
            sel = event.selection.rows if event and event.selection else []
            if sel:
                ss.selected_doc = df.iloc[sel[0]]["doc_id"]
                st.info(f"Evidence for **{df.iloc[sel[0]]['policy_no']}** is open in the Evidence tab.")
        else:
            st.dataframe(df, hide_index=True, use_container_width=True)

        with st.expander("Query (validated JSON → SQL)"):
            st.json({"filters": ss.query.filters, "columns": ss.query.columns,
                     "group_by": ss.query.group_by, "aggregate": ss.query.aggregate})
            st.code(res.sql + "\n-- params: " + json.dumps(res.params, default=str), language="sql")

        # ---- follow-up chat (FR-4)
        st.divider()
        st.markdown("**Follow-up on these rows**")
        for turn in ss.chat:
            with st.chat_message(turn.role):
                st.markdown(turn.content)
        msg = st.chat_input("e.g. Sum the limits by currency")
        if msg:
            with st.chat_message("user"):
                st.markdown(msg)
            with st.chat_message("assistant"):
                with st.spinner("Thinking…"):
                    ans = chat.ask(conn, res.rows, ss.chat, msg)
                if ans.error:
                    st.error(ans.error)
                else:
                    st.markdown(ans.text)
                    if ans.refine is not None:
                        if st.button("Apply proposed filter to the table"):
                            run_query(ans.refine)
                            st.rerun()
            ss.chat += [chat.ChatTurn("user", msg), chat.ChatTurn("assistant", ans.text or ans.error or "")]

# --------------------------------------------------------------------------- Evidence
with tab_evidence:
    docs = conn.execute(
        "SELECT d.doc_id, COALESCE(f.policy_no, d.doc_id) AS label FROM documents d "
        "LEFT JOIN policy_facts f USING (doc_id) ORDER BY label"
    ).fetchall()
    if not docs:
        st.info("The index is empty. Run `uv run --native-tls python -m ingest` first.")
    else:
        ids = [d["doc_id"] for d in docs]
        labels = {d["doc_id"]: d["label"] for d in docs}
        default = ids.index(ss.selected_doc) if ss.selected_doc in ids else 0
        chosen = st.selectbox("Document", ids, index=default, format_func=lambda i: labels[i])
        evidence.render(conn, chosen)

# --------------------------------------------------------------------------- Scale
with tab_scale:
    m = scale.measured(db.ingestion_summary(conn))
    st.subheader("Measured on this ingestion run")
    c = st.columns(6)
    c[0].metric("Documents", m["documents"])
    c[1].metric("Pages", m["pages"])
    c[2].metric("Pages / doc (median)", f"{m['pages_median']:.0f}" if m["pages_median"] else "–")
    c[3].metric("Seconds / doc (p50 / p95)",
                f"{m['secs_p50']:.0f} / {m['secs_p95']:.0f}" if m["secs_p50"] is not None else "–")
    c[4].metric("Tokens / doc (in / out)",
                f"{m['input_tokens_per_doc']:,.0f} / {m['output_tokens_per_doc']:,.0f}"
                if m["input_tokens_per_doc"] is not None else "–")
    c[5].metric("Cost / doc (API-equiv.)", scale.fmt_usd(m["cost_per_doc"]))

    st.subheader("Extrapolation")
    left, right = st.columns([1, 2])
    with left:
        d = config.SCALE_DEFAULTS
        a = {
            "corpus_documents": st.number_input("Documents in archive", value=d["corpus_documents"], step=10_000_000),
            "avg_pages_per_doc": st.number_input("Avg pages / doc", value=float(m["pages_mean"] or d["avg_pages_per_doc"]), step=1.0),
            "prefilter_share": st.slider("Share passing Stage 0 triage", 0.05, 1.0, d["prefilter_share"], 0.05),
            "batch_discount": st.slider("Batch API discount", 0.0, 0.5, d["batch_discount"], 0.05),
            "tokens_per_page_image": st.number_input("Tokens / page image", value=d["tokens_per_page_image"], step=100),
            "output_tokens_per_doc": st.number_input("Output tokens / doc", value=d["output_tokens_per_doc"], step=50),
            "ocr_cost_per_1000_pages": st.number_input("OCR cost / 1,000 pages ($)", value=d["ocr_cost_per_1000_pages"], step=0.1),
            "text_tokens_per_doc": st.number_input("Text tokens / doc after OCR", value=d["text_tokens_per_doc"], step=500),
        }
        model = st.selectbox("Model (list price)", list(config.MODEL_PRICES_PER_MTOK),
                             index=list(config.MODEL_PRICES_PER_MTOK).index(config.MODEL)
                             if config.MODEL in config.MODEL_PRICES_PER_MTOK else 0)
    with right:
        x = scale.extrapolate(a, model, m["cost_per_doc"])
        st.markdown(f"Documents read after triage: **{x['documents_read']:,.0f}** · pages: **{x['pages_read']:,.0f}**")
        rows = [
            {"Path": f"Prototype path — vision on page images ({model})",
             "Per doc": scale.fmt_usd(x["vision"]["per_doc"]), "Full corpus": scale.fmt_usd(x["vision"]["total"])},
            {"Path": f"Stage 1 OCR once + Stage 2 text extraction ({model})",
             "Per doc": scale.fmt_usd(x["ocr_text"]["ocr_per_doc"] + x["ocr_text"]["llm_per_doc"]),
             "Full corpus": f"{scale.fmt_usd(x['ocr_text']['total'])}  (OCR {scale.fmt_usd(x['ocr_text']['ocr_total'])} + LLM {scale.fmt_usd(x['ocr_text']['llm_total'])})"},
        ]
        if x["measured"]:
            rows.insert(0, {"Path": "Measured cost/doc from this run × corpus (with batch discount)",
                            "Per doc": scale.fmt_usd(x["measured"]["per_doc"]),
                            "Full corpus": scale.fmt_usd(x["measured"]["total"])})
        st.table(pd.DataFrame(rows))
        st.caption("List prices Sept 2026 (PRD s10); re-check before any business case. A query costs cents regardless of corpus size.")

    st.subheader("Why this scales: extract once, query many")
    st.markdown(
        "- **Stage 0 — triage on existing metadata (no LLM).** Product line, document type, date and language "
        "route documents to the right schema and drop irrelevant ones.\n"
        "- **Stage 1 — OCR once, store text + layout.** Vision reading of every page is the expensive path; "
        "dedicated OCR yields text with exact bounding boxes.\n"
        "- **Stage 2 — schema extraction with a small model, batched.** Same prompt and schema as this prototype, "
        "via the Batch API; escalate only low-confidence documents.\n"
        "- **Stage 3 — index.** Facts + evidence in a columnar store; queries hit the index, the LLM only translates "
        "and summarises.\n"
        "- **Stage 4 — human feedback loop.** Underwriter corrections become regression tests; re-extraction is per "
        "document, never per corpus."
    )

# --------------------------------------------------------------------------- Index
with tab_index:
    facts = [dict(r) for r in db.all_facts(conn)]
    if not facts:
        st.info("The index is empty. Run `uv run --native-tls python -m ingest` first.")
    else:
        st.dataframe(pd.DataFrame(facts), hide_index=True, use_container_width=True)
    st.caption(f"SQLite: {config.DB_PATH} · model: {config.MODEL}")
