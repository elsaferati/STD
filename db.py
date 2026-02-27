from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

import psycopg
from psycopg.rows import dict_row

_BASE_DIR = Path(__file__).resolve().parent
_MIGRATIONS_DIR = _BASE_DIR / "migrations"


def _get_database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not configured")
    return url


@contextmanager
def get_connection():
    conn = psycopg.connect(_get_database_url(), row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.close()


def execute(query: str, params: Iterable[Any] | None = None) -> None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params or ())
            conn.commit()


def fetch_one(query: str, params: Iterable[Any] | None = None) -> dict[str, Any] | None:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params or ())
            row = cursor.fetchone()
            return dict(row) if row else None


def fetch_all(query: str, params: Iterable[Any] | None = None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(query, params or ())
            rows = cursor.fetchall()
            return [dict(row) for row in rows]


def init_db() -> None:
    auto_init = (os.getenv("DB_AUTO_INIT") or "").strip().lower() in {"1", "true", "yes", "on"}
    if not auto_init:
        return

    migration_file = _MIGRATIONS_DIR / "001_create_users_sessions.sql"
    if not migration_file.exists():
        raise RuntimeError("Missing migration file: migrations/001_create_users_sessions.sql")

    sql = migration_file.read_text(encoding="utf-8")
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql)
            conn.commit()
