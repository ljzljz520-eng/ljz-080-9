"""DuckDB 持久化层：全局连接 + 进程内写锁。"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "farmpresale.duckdb"

_write_lock = threading.RLock()
_conn: duckdb.DuckDBPyConnection | None = None


def get_conn() -> duckdb.DuckDBPyConnection:
    global _conn
    if _conn is None:
        _conn = duckdb.connect(str(DB_PATH))
        _conn.execute("PRAGMA threads=2")
    return _conn


def fetchall(query: str, params: Iterable[Any] | None = None) -> list[dict]:
    cur = get_conn().execute(query, list(params or []))
    cols = [d[0] for d in cur.description] if cur.description else []
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def fetchone(query: str, params: Iterable[Any] | None = None) -> dict | None:
    cur = get_conn().execute(query, list(params or []))
    cols = [d[0] for d in cur.description] if cur.description else []
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def execute(query: str, params: Iterable[Any] | None = None) -> None:
    with _write_lock:
        get_conn().execute(query, list(params or []))


@contextmanager
def transaction():
    """写事务：同一把锁保证对 DuckDB 单连接的串行写入。"""
    _write_lock.acquire()
    conn = get_conn()
    try:
        conn.execute("BEGIN TRANSACTION")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        _write_lock.release()


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
