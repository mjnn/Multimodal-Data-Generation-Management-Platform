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
    action: str | None = None,
    actor_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    items, _ = query_audit_logs(
        resource_type=resource_type,
        resource_id=resource_id,
        action=action,
        actor_id=actor_id,
        limit=limit,
        offset=offset,
    )
    return items


def query_audit_logs(
    *,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    actor_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    where: list[str] = []
    params: list[Any] = []

    if resource_type:
        where.append("a.resource_type = ?")
        params.append(resource_type.strip())
    if resource_id:
        where.append("a.resource_id = ?")
        params.append(resource_id.strip())
    if action:
        where.append("a.action = ?")
        params.append(action.strip())
    if actor_id:
        where.append("a.actor_id = ?")
        params.append(actor_id.strip())

    clause = f" WHERE {' AND '.join(where)}" if where else ""

    with db_conn() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM audit_log a{clause}",
            params,
        ).fetchone()
        total = int(count_row["cnt"]) if count_row else 0
        rows = conn.execute(
            f"""
            SELECT a.*, u.username AS actor_username
            FROM audit_log a
            LEFT JOIN app_user u ON u.id = a.actor_id
            {clause}
            ORDER BY a.created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    return [_audit_row(r) for r in rows], total


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
        "actor_username": row["actor_username"] if "actor_username" in row.keys() else None,
        "action": row["action"],
        "resource_type": row["resource_type"],
        "resource_id": row["resource_id"],
        "detail": detail,
        "created_at": row["created_at"],
    }
