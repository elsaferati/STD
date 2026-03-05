from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from passlib.context import CryptContext

from db import execute, fetch_one

_PWD_CONTEXT = CryptContext(schemes=["argon2"], deprecated="auto")
_SESSION_COOKIE_NAME = "session_id"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_ttl() -> timedelta:
    days = int((os.getenv("AUTH_SESSION_DAYS") or "7").strip())
    return timedelta(days=max(1, days))


def hash_password(password: str) -> str:
    return _PWD_CONTEXT.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _PWD_CONTEXT.verify(password, password_hash)


def create_session(user_id: str, ip_address: str | None, user_agent: str | None) -> str:
    session_id = str(uuid4())
    created_at = _now()
    expires_at = created_at + _session_ttl()
    execute(
        """
        INSERT INTO sessions (id, user_id, created_at, expires_at, last_seen_at, ip_address, user_agent)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            session_id,
            user_id,
            created_at,
            expires_at,
            created_at,
            ip_address,
            user_agent,
        ),
    )
    return session_id


def _user_client_branches(user_id: str) -> list[str]:
    rows = fetch_one(
        """
        SELECT COALESCE(array_agg(ucs.branch_id ORDER BY ucs.branch_id), ARRAY[]::text[]) AS client_branches
        FROM user_client_scopes ucs
        WHERE ucs.user_id = %s
        """,
        (user_id,),
    ) or {}
    raw = rows.get("client_branches")
    if not isinstance(raw, list):
        return []
    return [str(item).strip().lower() for item in raw if str(item or "").strip()]


def revoke_session(session_id: str) -> None:
    execute(
        "UPDATE sessions SET revoked_at = %s WHERE id = %s",
        (_now(), session_id),
    )


def get_session_user(session_id: str) -> dict[str, Any] | None:
    if not session_id:
        return None
    now = _now()
    row = fetch_one(
        """
        SELECT s.id AS session_id,
               s.user_id,
               s.expires_at,
               s.last_seen_at,
               s.revoked_at,
               u.id AS id,
               u.username,
               u.role,
               u.is_active
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.id = %s
        """,
        (session_id,),
    )
    if not row:
        return None
    if row.get("revoked_at") is not None:
        return None
    expires_at = row.get("expires_at")
    if isinstance(expires_at, datetime) and expires_at <= now:
        return None
    if not row.get("is_active"):
        return None

    # Avoid a write on every authenticated API request.
    last_seen_at = row.get("last_seen_at")
    if not isinstance(last_seen_at, datetime) or last_seen_at <= now - timedelta(seconds=60):
        execute("UPDATE sessions SET last_seen_at = %s WHERE id = %s", (now, session_id))
    return {
        "id": row.get("id"),
        "username": row.get("username"),
        "role": row.get("role"),
        "client_branches": _user_client_branches(str(row.get("id") or "")),
        "session_id": row.get("session_id"),
    }


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    if not username or not password:
        return None
    row = fetch_one(
        """
        SELECT id, username, password_hash, role, is_active
        FROM users
        WHERE lower(username) = lower(%s)
        """,
        (username.strip(),),
    )
    if not row or not row.get("is_active"):
        return None
    if not verify_password(password, row.get("password_hash") or ""):
        return None
    execute("UPDATE users SET last_login_at = %s WHERE id = %s", (_now(), row["id"]))
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "client_branches": _user_client_branches(str(row["id"])),
    }


def seed_admin_user() -> bool:
    username = (os.getenv("ADMIN_USERNAME") or "").strip()
    password = (os.getenv("ADMIN_PASSWORD") or "").strip()
    email = (os.getenv("ADMIN_EMAIL") or "").strip() or None
    if not username or not password:
        return False

    existing = fetch_one(
        "SELECT id FROM users WHERE lower(username) = lower(%s)",
        (username,),
    )
    if existing:
        return False

    execute(
        """
        INSERT INTO users (id, username, password_hash, email, role, is_active, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            str(uuid4()),
            username,
            hash_password(password),
            email,
            "admin",
            True,
            _now(),
            _now(),
        ),
    )
    return True


def session_cookie_name() -> str:
    return _SESSION_COOKIE_NAME


def session_cookie_options() -> dict[str, Any]:
    secure = (os.getenv("AUTH_COOKIE_SECURE") or "").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "httponly": True,
        "samesite": "Lax",
        "secure": secure,
        "path": "/",
        "max_age": int(_session_ttl().total_seconds()),
    }
