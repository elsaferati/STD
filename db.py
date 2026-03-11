from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from threading import local
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

_BASE_DIR = Path(__file__).resolve().parent
_MIGRATIONS_DIR = _BASE_DIR / "migrations"
_THREAD_LOCAL = local()
_MIGRATIONS_TABLE = "schema_migrations"


def _get_database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


def _open_connection(*, autocommit: bool) -> psycopg.Connection:
    return psycopg.connect(
        _get_database_url(),
        row_factory=dict_row,
        autocommit=autocommit,
    )


def _thread_connection() -> psycopg.Connection:
    conn = getattr(_THREAD_LOCAL, "conn", None)
    if conn is None or conn.closed:
        conn = _open_connection(autocommit=True)
        _THREAD_LOCAL.conn = conn
    return conn


def _drop_thread_connection() -> None:
    conn = getattr(_THREAD_LOCAL, "conn", None)
    if conn is None:
        return
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    _THREAD_LOCAL.conn = None


@contextmanager
def get_connection():
    conn = _thread_connection()
    try:
        yield conn
    except (psycopg.InterfaceError, psycopg.OperationalError):
        _drop_thread_connection()
        raise


@contextmanager
def transaction():
    conn = _open_connection(autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _execute_with_retry(
    query: str,
    params: Iterable[Any] | None = None,
    *,
    fetch: str | None = None,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            with get_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query, params or ())
                    if fetch == "one":
                        row = cursor.fetchone()
                        return dict(row) if row else None
                    if fetch == "all":
                        rows = cursor.fetchall()
                        return [dict(row) for row in rows]
                    return None
        except (psycopg.InterfaceError, psycopg.OperationalError) as exc:
            last_error = exc
            _drop_thread_connection()
            if attempt == 1:
                raise
    if last_error is not None:
        raise last_error


def execute(query: str, params: Iterable[Any] | None = None) -> None:
    _execute_with_retry(query, params)


def fetch_one(query: str, params: Iterable[Any] | None = None) -> dict[str, Any] | None:
    return _execute_with_retry(query, params, fetch="one")


def fetch_all(query: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    rows = _execute_with_retry(query, params, fetch="all")
    return rows if isinstance(rows, list) else []


def init_db() -> None:
    auto_init = (os.getenv("DB_AUTO_INIT") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not auto_init:
        return

    migration_files = sorted(_MIGRATIONS_DIR.glob("*.sql"), key=lambda item: item.name)
    if not migration_files:
        raise RuntimeError("No migration files found in migrations/")

    with _open_connection(autocommit=False) as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_MIGRATIONS_TABLE} (
                    file_name TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cursor.execute(f"SELECT file_name FROM {_MIGRATIONS_TABLE}")
            applied = {str(row["file_name"]) for row in cursor.fetchall() or []}
            for migration_file in migration_files:
                if migration_file.name in applied:
                    continue
                sql = migration_file.read_text(encoding="utf-8")
                cursor.execute(sql)
                cursor.execute(
                    f"INSERT INTO {_MIGRATIONS_TABLE} (file_name, applied_at) VALUES (%s, now())",
                    (migration_file.name,),
                )
        conn.commit()
