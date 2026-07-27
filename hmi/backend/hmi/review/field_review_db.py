"""Per-label field review persistence (SQLite app.db)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

FIELD_REVIEW_ACTIONS = frozenset({"confirm", "correct", "uncertain"})

_FIELD_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS clip_label_field_review (
  id TEXT PRIMARY KEY,
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  label_id TEXT NOT NULL,
  taxonomy_version_id TEXT REFERENCES label_taxonomy_version(id),
  action TEXT NOT NULL CHECK (action IN ('confirm','correct','uncertain')),
  value_json TEXT,
  human_doubtful INTEGER NOT NULL DEFAULT 0,
  ai_value_json TEXT,
  reviewer_id TEXT REFERENCES app_user(id),
  reviewed_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(clip_id, run_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_clip_label_field_review_clip
  ON clip_label_field_review (clip_id, run_id);

CREATE INDEX IF NOT EXISTS idx_clip_label_field_review_label
  ON clip_label_field_review (label_id, reviewed_at DESC);
"""


def ensure_field_review_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_FIELD_REVIEW_SCHEMA)
        conn.commit()


def _parse_json_column(raw: Any) -> Any:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _field_review_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "clip_id": row["clip_id"],
        "run_id": row["run_id"],
        "label_id": row["label_id"],
        "taxonomy_version_id": row["taxonomy_version_id"],
        "action": row["action"],
        "value_json": _parse_json_column(row["value_json"]),
        "human_doubtful": bool(row["human_doubtful"]),
        "ai_value_json": _parse_json_column(row["ai_value_json"]),
        "reviewer_id": row["reviewer_id"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dump_json(value: Any) -> str | None:
    if value is None:
        return json.dumps(None)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def upsert_field_review(
    clip_id: str,
    run_id: str,
    label_id: str,
    *,
    action: str,
    value: Any,
    human_doubtful: bool,
    ai_value: Any | None,
    taxonomy_version_id: str | None,
    reviewer_id: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    clip_id = clip_id.strip()
    run_id = run_id.strip()
    label_id = label_id.strip()
    if not clip_id or not run_id or not label_id:
        raise ValueError("clip_id, run_id, and label_id required")
    if action not in FIELD_REVIEW_ACTIONS:
        raise ValueError(f"invalid action: {action}")
    if not reviewer_id:
        raise ValueError("reviewer_id required")

    now = reviewed_at or _utc_now_iso()
    with db_conn() as conn:
        existing = conn.execute(
            """
            SELECT id, created_at FROM clip_label_field_review
            WHERE clip_id = ? AND run_id = ? AND label_id = ?
            """,
            (clip_id, run_id, label_id),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE clip_label_field_review
                SET taxonomy_version_id = ?, action = ?, value_json = ?,
                    human_doubtful = ?, ai_value_json = ?, reviewer_id = ?,
                    reviewed_at = ?, updated_at = ?
                WHERE clip_id = ? AND run_id = ? AND label_id = ?
                """,
                (
                    taxonomy_version_id,
                    action,
                    _dump_json(value),
                    1 if human_doubtful else 0,
                    _dump_json(ai_value),
                    reviewer_id,
                    now,
                    now,
                    clip_id,
                    run_id,
                    label_id,
                ),
            )
        else:
            review_id = str(uuid.uuid4())
            created_at = _utc_now_iso()
            conn.execute(
                """
                INSERT INTO clip_label_field_review (
                  id, clip_id, run_id, label_id, taxonomy_version_id, action,
                  value_json, human_doubtful, ai_value_json, reviewer_id,
                  reviewed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review_id,
                    clip_id,
                    run_id,
                    label_id,
                    taxonomy_version_id,
                    action,
                    _dump_json(value),
                    1 if human_doubtful else 0,
                    _dump_json(ai_value),
                    reviewer_id,
                    now,
                    created_at,
                    now,
                ),
            )

    row = get_field_review(clip_id, run_id, label_id)
    assert row is not None
    return row


def get_field_review(clip_id: str, run_id: str, label_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM clip_label_field_review
            WHERE clip_id = ? AND run_id = ? AND label_id = ?
            """,
            (clip_id.strip(), run_id.strip(), label_id.strip()),
        ).fetchone()
        return _field_review_row(row) if row else None


def list_field_reviews(clip_id: str, run_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM clip_label_field_review
            WHERE clip_id = ? AND run_id = ?
            ORDER BY label_id ASC
            """,
            (clip_id.strip(), run_id.strip()),
        ).fetchall()
    return [_field_review_row(r) for r in rows]


def list_field_review_label_ids(clip_id: str, run_id: str) -> list[str]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT label_id FROM clip_label_field_review
            WHERE clip_id = ? AND run_id = ?
            ORDER BY label_id ASC
            """,
            (clip_id.strip(), run_id.strip()),
        ).fetchall()
    return [str(r["label_id"]) for r in rows]


def count_field_reviews(clip_id: str, run_id: str) -> int:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM clip_label_field_review
            WHERE clip_id = ? AND run_id = ?
            """,
            (clip_id.strip(), run_id.strip()),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def delete_field_reviews(clip_id: str, run_id: str) -> int:
    with db_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM clip_label_field_review
            WHERE clip_id = ? AND run_id = ?
            """,
            (clip_id.strip(), run_id.strip()),
        )
        return int(cur.rowcount or 0)


def field_review_key_set() -> set[tuple[str, str, str]]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT clip_id, run_id, label_id FROM clip_label_field_review"
        ).fetchall()
    return {(str(r["clip_id"]), str(r["run_id"]), str(r["label_id"])) for r in rows}
