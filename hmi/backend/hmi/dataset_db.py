"""Dataset snapshot persistence (SQLite app.db)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

DATASET_STATUSES = frozenset({"building", "ready", "failed", "archived"})

DEFAULT_FEATURE_SPEC: dict[str, Any] = {
    "x": ["fact_clip_embedding", "fact_embedding"],
    "x_schema": ["clip_embedding_v1", "frame_embeddings_v1"],
}
DEFAULT_TARGET_SPEC: dict[str, Any] = {"y": ["clip_label_review.labels_json"]}

DEFAULT_FILTER: dict[str, Any] = {
    "review_status": "reviewed",
    "include_pending_review": False,
    "clip_ids": None,
    "taxonomy_version_id": None,
    "label_filters": None,
    "sample_size": None,
}

_DATASET_SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset_snapshot (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL CHECK (status IN ('building','ready','failed','archived')),
  filter_json TEXT NOT NULL,
  clip_count INTEGER NOT NULL DEFAULT 0,
  feature_spec_json TEXT NOT NULL,
  target_spec_json TEXT NOT NULL,
  oss_manifest_uri TEXT,
  oss_x_uri TEXT,
  oss_y_uri TEXT,
  mc_table_name TEXT,
  error_message TEXT,
  created_by TEXT REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  ready_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dataset_snapshot_status
  ON dataset_snapshot (status, updated_at DESC);
"""


def ensure_dataset_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_DATASET_SCHEMA)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(dataset_snapshot)").fetchall()}
        if "oss_x_uri" not in cols:
            conn.execute("ALTER TABLE dataset_snapshot ADD COLUMN oss_x_uri TEXT")
        if "oss_y_uri" not in cols:
            conn.execute("ALTER TABLE dataset_snapshot ADD COLUMN oss_y_uri TEXT")
        conn.commit()


def _dump_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _load_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "filter_json": _load_json(row["filter_json"]),
        "clip_count": int(row["clip_count"]),
        "feature_spec_json": _load_json(row["feature_spec_json"]),
        "target_spec_json": _load_json(row["target_spec_json"]),
        "oss_manifest_uri": row["oss_manifest_uri"],
        "oss_x_uri": row["oss_x_uri"] if "oss_x_uri" in row.keys() else None,
        "oss_y_uri": row["oss_y_uri"] if "oss_y_uri" in row.keys() else None,
        "mc_table_name": row["mc_table_name"],
        "error_message": row["error_message"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "ready_at": row["ready_at"],
    }


def create_snapshot(
    name: str,
    *,
    description: str | None = None,
    filter_json: dict[str, Any] | str | None = None,
    feature_spec_json: dict[str, Any] | str | None = None,
    target_spec_json: dict[str, Any] | str | None = None,
    status: str = "building",
    created_by: str | None = None,
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("name required")
    if status not in DATASET_STATUSES:
        raise ValueError(f"invalid status: {status}")

    snapshot_id = str(uuid.uuid4())
    now = _utc_now_iso()
    resolved_filter = filter_json if filter_json is not None else DEFAULT_FILTER
    resolved_feature = feature_spec_json if feature_spec_json is not None else DEFAULT_FEATURE_SPEC
    resolved_target = target_spec_json if target_spec_json is not None else DEFAULT_TARGET_SPEC

    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO dataset_snapshot (
              id, name, description, status, filter_json, clip_count,
              feature_spec_json, target_spec_json, oss_manifest_uri, mc_table_name,
              error_message, created_by, created_at, updated_at, ready_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL)
            """,
            (
                snapshot_id,
                name,
                description,
                status,
                _dump_json(resolved_filter),
                _dump_json(resolved_feature),
                _dump_json(resolved_target),
                created_by,
                now,
                now,
            ),
        )

    snapshot = get_snapshot(snapshot_id)
    assert snapshot is not None
    return snapshot


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dataset_snapshot WHERE id = ?",
            (snapshot_id.strip(),),
        ).fetchone()
        return _snapshot_row(row) if row else None


def list_snapshots(
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with db_conn() as conn:
        if status:
            if status not in DATASET_STATUSES:
                raise ValueError(f"invalid status: {status}")
            rows = conn.execute(
                """
                SELECT * FROM dataset_snapshot
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM dataset_snapshot
                WHERE status != 'archived'
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [_snapshot_row(r) for r in rows]


def count_snapshots(*, status: str | None = None, include_archived: bool = False) -> int:
    with db_conn() as conn:
        if status:
            if status not in DATASET_STATUSES:
                raise ValueError(f"invalid status: {status}")
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM dataset_snapshot WHERE status = ?",
                (status,),
            ).fetchone()
        elif include_archived:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM dataset_snapshot").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM dataset_snapshot WHERE status != 'archived'"
            ).fetchone()
    return int(row["cnt"]) if row else 0


def update_snapshot(
    snapshot_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    filter_json: dict[str, Any] | str | None = None,
    clip_count: int | None = None,
    feature_spec_json: dict[str, Any] | str | None = None,
    target_spec_json: dict[str, Any] | str | None = None,
    oss_manifest_uri: str | None = None,
    oss_x_uri: str | None = None,
    oss_y_uri: str | None = None,
    mc_table_name: str | None = None,
    error_message: str | None = None,
    ready_at: str | None = None,
    clear_error: bool = False,
) -> dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dataset_snapshot WHERE id = ?",
            (snapshot_id.strip(),),
        ).fetchone()
        if row is None:
            raise ValueError(f"snapshot not found: {snapshot_id}")

        if status is not None and status not in DATASET_STATUSES:
            raise ValueError(f"invalid status: {status}")

        now = _utc_now_iso()
        new_name = name.strip() if name is not None else row["name"]
        if not new_name:
            raise ValueError("name required")

        new_description = description if description is not None else row["description"]
        new_status = status if status is not None else row["status"]
        new_filter = _dump_json(filter_json) if filter_json is not None else row["filter_json"]
        new_clip_count = clip_count if clip_count is not None else int(row["clip_count"])
        new_feature = (
            _dump_json(feature_spec_json)
            if feature_spec_json is not None
            else row["feature_spec_json"]
        )
        new_target = (
            _dump_json(target_spec_json)
            if target_spec_json is not None
            else row["target_spec_json"]
        )
        if oss_manifest_uri is not None:
            new_oss = oss_manifest_uri or None
        else:
            new_oss = row["oss_manifest_uri"]
        if oss_x_uri is not None:
            new_x = oss_x_uri or None
        else:
            new_x = row["oss_x_uri"] if "oss_x_uri" in row.keys() else None
        if oss_y_uri is not None:
            new_y = oss_y_uri or None
        else:
            new_y = row["oss_y_uri"] if "oss_y_uri" in row.keys() else None
        if mc_table_name is not None:
            new_mc = mc_table_name or None
        else:
            new_mc = row["mc_table_name"]
        if clear_error:
            new_error = None
        elif error_message is not None:
            new_error = error_message
        else:
            new_error = row["error_message"]

        if ready_at is not None:
            new_ready_at = ready_at
        elif status == "ready" and row["status"] != "ready":
            new_ready_at = now
        else:
            new_ready_at = row["ready_at"]

        conn.execute(
            """
            UPDATE dataset_snapshot
            SET name = ?, description = ?, status = ?, filter_json = ?,
                clip_count = ?, feature_spec_json = ?, target_spec_json = ?,
                oss_manifest_uri = ?, oss_x_uri = ?, oss_y_uri = ?, mc_table_name = ?,
                error_message = ?, updated_at = ?, ready_at = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_description,
                new_status,
                new_filter,
                new_clip_count,
                new_feature,
                new_target,
                new_oss,
                new_x,
                new_y,
                new_mc,
                new_error,
                now,
                new_ready_at,
                snapshot_id.strip(),
            ),
        )

    snapshot = get_snapshot(snapshot_id)
    assert snapshot is not None
    return snapshot
