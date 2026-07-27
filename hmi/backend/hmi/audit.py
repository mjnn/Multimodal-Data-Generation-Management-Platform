"""Audit log persistence (SQLite app.db)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn


def append_audit_log(
    *,
    actor_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str,
    detail: dict[str, Any] | None = None,
    conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    log_id = str(uuid.uuid4())
    now = _utc_now_iso()
    detail_json = json.dumps(detail, ensure_ascii=False) if detail else None

    def _insert(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO audit_log
              (id, actor_id, action, resource_type, resource_id, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (log_id, actor_id, action, resource_type, resource_id, detail_json, now),
        )

    if conn is not None:
        _insert(conn)
    else:
        with db_conn() as connection:
            _insert(connection)

    row = {
        "id": log_id,
        "actor_id": actor_id,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "detail": detail,
        "created_at": now,
    }
    return row


def list_audit_logs(
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    with db_conn() as conn:
        if resource_type and resource_id:
            rows = conn.execute(
                """
                SELECT * FROM audit_log
                WHERE resource_type = ? AND resource_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (resource_type, resource_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM audit_log
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_audit_row(r) for r in rows]


def _audit_row(row: sqlite3.Row) -> dict[str, Any]:
    detail = None
    raw = row["detail_json"]
    if raw:
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
    return {
        "id": row["id"],
        "actor_id": row["actor_id"],
        "action": row["action"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "detail": detail,
        "created_at": row["created_at"],
    }
