"""Read-only access to the prebuilt DuckDB file (built by scripts/build_data.py)."""
from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

DB_PATH = Path(os.environ.get("APP_DB", Path(__file__).parent / "data" / "app.duckdb"))
_local = threading.local()


def con() -> duckdb.DuckDBPyConnection:
    c = getattr(_local, "con", None)
    if c is None:
        c = duckdb.connect(str(DB_PATH), read_only=True)
        _local.con = c
    return c


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = con().execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def one(sql: str, params: list | None = None) -> dict | None:
    r = rows(sql, params)
    return r[0] if r else None
