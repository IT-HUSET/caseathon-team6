"""Tests for the parts that don't need Claude: schema validation, query building, merge/flags, parsing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import config
from index import db
from index.schema import ExtractionValidationError, validate_extraction, EXTRACTION_EXAMPLE
from ingest.claude_cli import parse_json_payload, strip_fences
from ingest.extract import ChunkResult, chunk_pages
from ingest.merge import merge_chunks
from query.execute import InvalidQuery, build_sql, execute, validate


# --- claude_cli parsing --------------------------------------------------------

def test_strip_fences_and_parse():
    assert strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert parse_json_payload('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_payload('prefix {"a": {"b": 2}} suffix') == {"a": {"b": 2}}
    with pytest.raises(json.JSONDecodeError):
        parse_json_payload("no json here")


# --- extraction schema ---------------------------------------------------------

def test_validate_extraction_accepts_example():
    assert validate_extraction(EXTRACTION_EXAMPLE, 1, 15) == EXTRACTION_EXAMPLE


def test_validate_extraction_rejects_bad_page_and_types():
    bad = json.loads(json.dumps(EXTRACTION_EXAMPLE))
    bad["excess_auto"]["evidence_page"] = 99
    with pytest.raises(ExtractionValidationError, match="outside chunk"):
        validate_extraction(bad, 1, 15)
    bad = json.loads(json.dumps(EXTRACTION_EXAMPLE))
    bad["geography_us"] = "yes"
    with pytest.raises(ExtractionValidationError, match="boolean"):
        validate_extraction(bad, 1, 15)
    with pytest.raises(ExtractionValidationError, match="missing keys"):
        validate_extraction({"policy_no": "x"}, 1, 15)


def test_chunk_pages_absolute_numbering():
    pages = [Path(f"p{i}.png") for i in range(1, 33)]
    chunks = chunk_pages(pages, chunk_size=15)
    assert [(f, len(p)) for f, p in chunks] == [(1, 15), (16, 15), (31, 2)]


# --- merge + review flags (FR-1 merge rules, FR-7) -----------------------------

def _chunk(idx: int, first: int, last: int, data: dict | None, status: str = "ok") -> ChunkResult:
    return ChunkResult(idx, first, last, status=status, data=data)


def test_merge_first_non_null_header_and_positive_wins():
    c0 = _chunk(0, 1, 15, {**EXTRACTION_EXAMPLE, "has_excess_auto_liability": False, "excess_auto": None,
                           "policyholder": None})
    c1 = _chunk(1, 16, 20, {**EXTRACTION_EXAMPLE, "policy_no": "OTHER", "policyholder": "Acme"})
    facts, evidence = merge_chunks([c1, c0])  # order-insensitive
    assert facts["policy_no"] == EXTRACTION_EXAMPLE["policy_no"]      # first chunk's header wins
    assert facts["policyholder"] == "Acme"                           # first non-null
    assert facts["has_excess_auto"] == 1                             # positive wins over False
    assert facts["ea_attachment_amount"] == 1000000
    assert facts["ea_limit_currency"] == "EUR"
    assert facts["needs_review"] == 0
    fields = {e["field"] for e in evidence}
    assert fields == {"geography_us", "has_excess_auto", "excess_auto", "excess_auto_limit"}


def test_merge_flags_low_confidence_missing_quote_and_failed_chunk():
    low = json.loads(json.dumps(EXTRACTION_EXAMPLE))
    low["excess_auto"]["confidence"] = "low"
    facts, _ = merge_chunks([_chunk(0, 1, 5, low)])
    assert facts["needs_review"] == 1 and any("low" in r for r in facts["review_reasons"])

    noquote = json.loads(json.dumps(EXTRACTION_EXAMPLE))
    noquote["excess_auto"]["evidence_quote"] = None
    facts, _ = merge_chunks([_chunk(0, 1, 5, noquote)])
    assert facts["needs_review"] == 1 and any("no evidence quote" in r for r in facts["review_reasons"])

    facts, _ = merge_chunks([_chunk(0, 1, 5, EXTRACTION_EXAMPLE), _chunk(1, 6, 9, None, "extraction_failed")])
    assert facts["needs_review"] == 1 and any("chunk 1" in r for r in facts["review_reasons"])


def test_merge_negative_document_has_no_figures():
    neg = {**EXTRACTION_EXAMPLE, "has_excess_auto_liability": False, "excess_auto": None, "geography_us": False}
    facts, evidence = merge_chunks([_chunk(0, 1, 3, neg)])
    assert facts["has_excess_auto"] == 0
    assert facts["ea_attachment_amount"] is None and facts["ea_limit_amount"] is None


# --- query whitelist + SQL (FR-3) ----------------------------------------------

def test_validate_query_rejects_unknown_field_and_bad_op():
    with pytest.raises(InvalidQuery):
        validate({"filters": [{"field": "broker", "op": "eq", "value": "x"}]})
    with pytest.raises(InvalidQuery):
        validate({"filters": [{"field": "policy_no", "op": "gt", "value": "x"}]})
    with pytest.raises(InvalidQuery):
        validate({"aggregate": {"fn": "sum", "field": "policy_no"}})
    with pytest.raises(InvalidQuery):
        validate({"columns": ["policy_no; DROP TABLE documents"]})


def test_build_sql_is_parametrised_and_always_has_policy_no():
    q = validate({"filters": [{"field": "has_excess_auto", "op": "eq", "value": True},
                              {"field": "ea_limit_amount", "op": "gt", "value": "10000000"}],
                  "columns": ["ea_limit_amount", "ea_limit_currency"]})
    sql, params, cols = build_sql(q)
    assert params == [1, 10000000.0]
    assert cols[:2] == ["doc_id", "policy_no"] and cols[-1] == "needs_review"
    assert "ORDER BY f.needs_review" in sql


def test_execute_against_sqlite(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "t.sqlite")
    conn = db.connect(config.DB_PATH)
    db.upsert_document(conn, "d1", "a.pdf", "h1", 3, "ok")
    db.upsert_document(conn, "d2", "b.pdf", "h2", 3, "ok")
    db.replace_policy_facts(conn, "d1", {"policy_no": "LP1", "has_excess_auto": 1, "geography_us": 1,
                                         "ea_limit_amount": 25e6, "ea_limit_currency": "EUR", "needs_review": 0}, [])
    db.replace_policy_facts(conn, "d2", {"policy_no": "LP2", "has_excess_auto": 0, "geography_us": 1,
                                         "needs_review": 1, "review_reasons": ["x"]}, [])

    rs = execute(conn, validate({"filters": [{"field": "has_excess_auto", "op": "eq", "value": True}],
                                 "columns": ["ea_limit_amount"]}))
    assert [r["policy_no"] for r in rs.rows] == ["LP1"]

    rs = execute(conn, validate({"aggregate": {"fn": "count", "field": None}}))
    assert rs.rows == [{"count": 2}]

    rs = execute(conn, validate({"aggregate": {"fn": "sum", "field": "ea_limit_amount"},
                                 "group_by": "ea_limit_currency"}))
    assert {r["ea_limit_currency"]: r["sum_ea_limit_amount"] for r in rs.rows} == {None: None, "EUR": 25e6}


def test_merge_treats_string_null_as_missing():
    d = {**EXTRACTION_EXAMPLE, "policyholder": "null", "client_no": ""}
    facts, _ = merge_chunks([_chunk(0, 1, 5, d)])
    assert facts["policyholder"] is None and facts["client_no"] is None


def test_query_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "c.sqlite")
    conn = db.connect(config.DB_PATH)
    assert db.normalise_question("  Sum   the limits by currency?! ") == "sum the limits by currency"
    assert db.cache_get(conn, "Sum the limits") is None
    db.cache_put(conn, "Sum the limits", '{"columns": ["policy_no"]}')
    assert db.cache_get(conn, "sum the limits.") == '{"columns": ["policy_no"]}'
    assert conn.execute("SELECT hits FROM query_cache").fetchone()[0] == 1


def test_detect_language():
    from query.chat import detect_language
    assert detect_language("Sum the limits by currency.") == "en"
    assert detect_language("Summera limiterna per valuta.") == "sv"
    assert detect_language("Hur många policyer har excess auto-täckning i USA?") == "sv"
