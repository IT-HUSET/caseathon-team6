"""Validate a JSON query against the published schema and run it in SQLite (FR-3).

The model never writes SQL. It emits `{filters, columns, group_by, aggregate}`
using only names from `index.schema.QUERY_FIELDS`; this module builds a
parametrised statement from that whitelist and rejects everything else.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from index.schema import AGGREGATES, ALWAYS_COLUMNS, OPS_BY_TYPE, QUERY_FIELDS


class InvalidQuery(ValueError):
    """The JSON query uses a field/op/aggregate outside the whitelist."""


@dataclass
class Query:
    filters: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    group_by: str | None = None
    aggregate: dict[str, Any] | None = None      # {"fn": "sum", "field": "ea_limit_amount"}
    explanation: str = ""

    @property
    def is_aggregate(self) -> bool:
        return self.aggregate is not None


@dataclass
class ResultSet:
    columns: list[str]
    rows: list[dict[str, Any]]
    sql: str
    params: list[Any]
    explanation: str = ""


def _coerce(field_name: str, value: Any) -> Any:
    typ = QUERY_FIELDS[field_name][1]
    if value is None:
        return None
    if typ == "bool":
        if isinstance(value, str):
            return 1 if value.strip().lower() in ("true", "1", "yes", "ja") else 0
        return int(bool(value))
    if typ == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            raise InvalidQuery(f"{field_name}: {value!r} is not a number")
    return str(value)


def validate(raw: dict[str, Any]) -> Query:
    if not isinstance(raw, dict):
        raise InvalidQuery("query must be a JSON object")
    q = Query(explanation=str(raw.get("explanation") or ""))

    for f in raw.get("filters") or []:
        name, op = f.get("field"), f.get("op")
        if name not in QUERY_FIELDS:
            raise InvalidQuery(f"unknown field {name!r}")
        typ = QUERY_FIELDS[name][1]
        if op not in OPS_BY_TYPE[typ]:
            raise InvalidQuery(f"operator {op!r} not allowed on {name} ({typ})")
        value = f.get("value")
        if op == "in":
            if not isinstance(value, list):
                raise InvalidQuery(f"{name}: 'in' needs a list value")
            value = [_coerce(name, v) for v in value]
        elif op in ("is_null", "not_null"):
            value = None
        else:
            value = _coerce(name, value)
        q.filters.append({"field": name, "op": op, "value": value})

    for c in raw.get("columns") or []:
        if c not in QUERY_FIELDS:
            raise InvalidQuery(f"unknown column {c!r}")
        if c not in q.columns:
            q.columns.append(c)

    gb = raw.get("group_by")
    if gb is not None:
        if gb not in QUERY_FIELDS:
            raise InvalidQuery(f"unknown group_by field {gb!r}")
        q.group_by = gb

    agg = raw.get("aggregate")
    if agg is not None:
        fn, fld = agg.get("fn"), agg.get("field")
        if fn not in AGGREGATES:
            raise InvalidQuery(f"unknown aggregate {fn!r}")
        if fn != "count":
            if fld not in QUERY_FIELDS or QUERY_FIELDS[fld][1] != "number":
                raise InvalidQuery(f"aggregate {fn} needs a numeric field, got {fld!r}")
        q.aggregate = {"fn": fn, "field": fld}
    return q


_SQL_OPS = {"eq": "=", "neq": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _where(filters: list[dict[str, Any]]) -> tuple[str, list[Any]]:
    clauses, params = [], []
    for f in filters:
        col = QUERY_FIELDS[f["field"]][0]
        op, val = f["op"], f["value"]
        if op in _SQL_OPS:
            clauses.append(f"f.{col} {_SQL_OPS[op]} ?")
            params.append(val)
        elif op == "contains":
            clauses.append(f"f.{col} LIKE ? COLLATE NOCASE")
            params.append(f"%{val}%")
        elif op == "in":
            clauses.append(f"f.{col} IN ({', '.join('?' for _ in val)})")
            params.extend(val)
        elif op == "is_null":
            clauses.append(f"f.{col} IS NULL")
        elif op == "not_null":
            clauses.append(f"f.{col} IS NOT NULL")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def build_sql(q: Query) -> tuple[str, list[Any], list[str]]:
    where, params = _where(q.filters)
    base = "FROM policy_facts f JOIN documents d USING (doc_id)"

    if q.is_aggregate:
        fn, fld = q.aggregate["fn"], q.aggregate["field"]
        expr = "COUNT(*)" if fn == "count" else f"{fn.upper()}(f.{QUERY_FIELDS[fld][0]})"
        label = fn if fn == "count" else f"{fn}_{fld}"
        select = [f"{expr} AS {label}"]
        out_cols = [label]
        group = ""
        if q.group_by:
            gcol = QUERY_FIELDS[q.group_by][0]
            select.insert(0, f"f.{gcol} AS {q.group_by}")
            out_cols.insert(0, q.group_by)
            group = f" GROUP BY f.{gcol}"
        sql = f"SELECT {', '.join(select)} {base}{where}{group} ORDER BY 1"
        return sql, params, out_cols

    cols = list(dict.fromkeys(ALWAYS_COLUMNS[:1] + q.columns + ALWAYS_COLUMNS[1:]))
    select = ["f.doc_id AS doc_id"] + [f"f.{QUERY_FIELDS[c][0]} AS {c}" for c in cols]
    # FR-7: flagged rows sort to the bottom by default.
    sql = f"SELECT {', '.join(select)} {base}{where} ORDER BY f.needs_review, f.policy_no"
    return sql, params, ["doc_id"] + cols


def execute(conn: sqlite3.Connection, q: Query) -> ResultSet:
    sql, params, out_cols = build_sql(q)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    return ResultSet(columns=out_cols, rows=rows, sql=sql, params=params, explanation=q.explanation)
