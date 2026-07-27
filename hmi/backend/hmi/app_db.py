"""Application SQLite database (users, roles). Separate from timeline/parse DBs."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import bcrypt

from hmi.config import PROJECT_ROOT

APP_DB_PATH = PROJECT_ROOT / "data" / "app.db"

VALID_ROLES = frozenset({"admin", "reviewer", "dataset_manager", "model_trainer"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_user (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_user_role (
  user_id TEXT NOT NULL REFERENCES app_user(id),
  role TEXT NOT NULL CHECK (role IN ('admin','reviewer','dataset_manager','model_trainer')),
  PRIMARY KEY (user_id, role)
);
"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def ensure_schema() -> None:
    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()
    from hmi.taxonomy_db import ensure_taxonomy_schema

    ensure_taxonomy_schema()
    from hmi.review_db import ensure_review_schema

    ensure_review_schema()
    from hmi.dataset_db import ensure_dataset_schema

    ensure_dataset_schema()


@contextmanager
def db_conn() -> Iterator[sqlite3.Connection]:
    ensure_schema()
    conn = sqlite3.connect(APP_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_user(row: sqlite3.Row, roles: list[str]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "is_active": bool(row["is_active"]),
        "roles": roles,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_user_roles(conn: sqlite3.Connection, user_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT role FROM app_user_role WHERE user_id = ? ORDER BY role",
        (user_id,),
    ).fetchall()
    return [r["role"] for r in rows]


def get_user_by_username(username: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM app_user WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None:
            return None
        roles = get_user_roles(conn, row["id"])
        return _row_to_user(row, roles)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            return None
        roles = get_user_roles(conn, row["id"])
        return _row_to_user(row, roles)


def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM app_user WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or not row["is_active"]:
            return None
        if not verify_password(password, row["password_hash"]):
            return None
        roles = get_user_roles(conn, row["id"])
        return _row_to_user(row, roles)


def create_user(
    username: str,
    password: str,
    *,
    display_name: str | None = None,
    roles: list[str] | None = None,
    is_active: bool = True,
) -> dict[str, Any]:
    username = username.strip()
    if not username:
        raise ValueError("username required")
    if len(password) < 8:
        raise ValueError("password must be at least 8 characters")
    role_list = list(roles or [])
    invalid = set(role_list) - VALID_ROLES
    if invalid:
        raise ValueError(f"invalid roles: {sorted(invalid)}")

    user_id = str(uuid.uuid4())
    now = _utc_now_iso()
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT 1 FROM app_user WHERE username = ?",
            (username,),
        ).fetchone()
        if existing:
            raise ValueError(f"username already exists: {username}")

        conn.execute(
            """
            INSERT INTO app_user (id, username, password_hash, display_name, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                hash_password(password),
                display_name or username,
                1 if is_active else 0,
                now,
                now,
            ),
        )
        for role in role_list:
            conn.execute(
                "INSERT INTO app_user_role (user_id, role) VALUES (?, ?)",
                (user_id, role),
            )

    user = get_user_by_id(user_id)
    assert user is not None
    return user


def list_users() -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM app_user ORDER BY username").fetchall()
        return [_row_to_user(row, get_user_roles(conn, row["id"])) for row in rows]


def update_user(
    user_id: str,
    *,
    display_name: str | None = None,
    is_active: bool | None = None,
    roles: list[str] | None = None,
    password: str | None = None,
) -> dict[str, Any]:
    user = get_user_by_id(user_id)
    if user is None:
        raise ValueError(f"user not found: {user_id}")

    if password is not None and len(password) < 8:
        raise ValueError("password must be at least 8 characters")

    if roles is not None:
        invalid = set(roles) - VALID_ROLES
        if invalid:
            raise ValueError(f"invalid roles: {sorted(invalid)}")

    now = _utc_now_iso()
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM app_user WHERE id = ?", (user_id,)).fetchone()
        if row is None:
            raise ValueError(f"user not found: {user_id}")

        fields: list[str] = []
        values: list[Any] = []
        if display_name is not None:
            fields.append("display_name = ?")
            values.append(display_name.strip() or row["username"])
        if is_active is not None:
            fields.append("is_active = ?")
            values.append(1 if is_active else 0)
        if password is not None:
            fields.append("password_hash = ?")
            values.append(hash_password(password))

        if fields:
            fields.append("updated_at = ?")
            values.append(now)
            values.append(user_id)
            conn.execute(
                f"UPDATE app_user SET {', '.join(fields)} WHERE id = ?",
                values,
            )

        if roles is not None:
            conn.execute("DELETE FROM app_user_role WHERE user_id = ?", (user_id,))
            for role in roles:
                conn.execute(
                    "INSERT INTO app_user_role (user_id, role) VALUES (?, ?)",
                    (user_id, role),
                )

    updated = get_user_by_id(user_id)
    assert updated is not None
    return updated
