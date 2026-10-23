"""Read-only access to the app data (Parquet built by scripts/build_data.py).

Parquet is loaded once into a shared in-memory DuckDB; each thread gets its own cursor.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import duckdb

PQ_DIR = Path(os.environ.get("APP_DATA", Path(__file__).parent / "data" / "pq"))
_local = threading.local()
_lock = threading.Lock()
_root: duckdb.DuckDBPyConnection | None = None


def _root_con() -> duckdb.DuckDBPyConnection:
    global _root
    with _lock:
        if _root is None:
            c = duckdb.connect(":memory:")
            for f in sorted(PQ_DIR.glob("*.parquet")):
                c.execute(f"create table {f.stem} as select * from read_parquet('{f.as_posix()}')")
            _root = c
    return _root


def con() -> duckdb.DuckDBPyConnection:
    c = getattr(_local, "con", None)
    if c is None:
        c = _root_con().cursor()
        _local.con = c
    return c


def rows(sql: str, params: list | None = None) -> list[dict]:
    cur = con().execute(sql, params or [])
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def one(sql: str, params: list | None = None) -> dict | None:
    r = rows(sql, params)
    return r[0] if r else None
