"""Clip label review persistence (SQLite app.db)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

REVIEW_STATUSES = frozenset({"pending_review", "reviewed"})

_REVIEW_SCHEMA = """
CREATE TABLE IF NOT EXISTS clip_label_review (
  id TEXT PRIMARY KEY,
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  taxonomy_version_id TEXT REFERENCES label_taxonomy_version(id),
  labels_json TEXT NOT NULL,
  review_status TEXT NOT NULL CHECK (review_status IN ('pending_review','reviewed')),
  ai_source_summary_json TEXT,
  reviewer_id TEXT REFERENCES app_user(id),
  reviewed_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(clip_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_clip_label_review_status
  ON clip_label_review (review_status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_clip_label_review_clip
  ON clip_label_review (clip_id);

CREATE TABLE IF NOT EXISTS audit_log (
  id TEXT PRIMARY KEY,
  actor_id TEXT REFERENCES app_user(id),
  action TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  detail_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_resource
  ON audit_log (resource_type, resource_id, created_at DESC);
"""


def ensure_review_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_REVIEW_SCHEMA)
        conn.commit()
    from hmi.review.field_review_db import ensure_field_review_schema

    ensure_field_review_schema()
    from hmi.review.assignment_db import ensure_assignment_schema

    ensure_assignment_schema()


def _review_row(row: sqlite3.Row) -> dict[str, Any]:
    labels_json = None
    raw_labels = row["labels_json"]
    if raw_labels:
        try:
            labels_json = json.loads(raw_labels)
        except json.JSONDecodeError:
            labels_json = raw_labels

    ai_summary = None
    raw_summary = row["ai_source_summary_json"]
    if raw_summary:
        try:
            ai_summary = json.loads(raw_summary)
        except json.JSONDecodeError:
            ai_summary = raw_summary

    return {
        "id": row["id"],
        "clip_id": row["clip_id"],
        "run_id": row["run_id"],
        "taxonomy_version_id": row["taxonomy_version_id"],
        "labels_json": labels_json,
        "review_status": row["review_status"],
        "ai_source_summary_json": ai_summary,
        "reviewer_id": row["reviewer_id"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dump_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def create_review(
    clip_id: str,
    run_id: str,
    *,
    labels_json: dict[str, Any] | list[Any] | str,
    taxonomy_version_id: str | None = None,
    review_status: str = "pending_review",
    ai_source_summary_json: dict[str, Any] | list[Any] | str | None = None,
    reviewer_id: str | None = None,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    clip_id = clip_id.strip()
    run_id = run_id.strip()
    if not clip_id or not run_id:
        raise ValueError("clip_id and run_id required")
    if review_status not in REVIEW_STATUSES:
        raise ValueError(f"invalid review_status: {review_status}")

    review_id = str(uuid.uuid4())
    now = _utc_now_iso()
    with db_conn() as conn:
        dup = conn.execute(
            "SELECT 1 FROM clip_label_review WHERE clip_id = ? AND run_id = ?",
            (clip_id, run_id),
        ).fetchone()
        if dup:
            raise ValueError(f"review already exists: {clip_id}/{run_id}")

        conn.execute(
            """
            INSERT INTO clip_label_review (
              id, clip_id, run_id, taxonomy_version_id, labels_json, review_status,
              ai_source_summary_json, reviewer_id, reviewed_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                review_id,
                clip_id,
                run_id,
                taxonomy_version_id,
                _dump_json(labels_json),
                review_status,
                _dump_json(ai_source_summary_json) if ai_source_summary_json is not None else None,
                reviewer_id,
                reviewed_at,
                now,
                now,
            ),
        )

    review = get_review(clip_id, run_id)
    assert review is not None
    return review


def get_or_create_review(
    clip_id: str,
    run_id: str,
    *,
    labels_json: dict[str, Any] | list[Any] | str,
    taxonomy_version_id: str | None = None,
    review_status: str = "pending_review",
    ai_source_summary_json: dict[str, Any] | list[Any] | str | None = None,
    reviewer_id: str | None = None,
    reviewed_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Return (review, created). Idempotent when (clip_id, run_id) already exists."""
    existing = get_review(clip_id, run_id)
    if existing:
        return existing, False
    try:
        review = create_review(
            clip_id,
            run_id,
            labels_json=labels_json,
            taxonomy_version_id=taxonomy_version_id,
            review_status=review_status,
            ai_source_summary_json=ai_source_summary_json,
            reviewer_id=reviewer_id,
            reviewed_at=reviewed_at,
        )
        return review, True
    except ValueError as exc:
        if "already exists" not in str(exc):
            raise
        existing = get_review(clip_id, run_id)
        if existing:
            return existing, False
        raise


def get_review(clip_id: str, run_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM clip_label_review
            WHERE clip_id = ? AND run_id = ?
            """,
            (clip_id.strip(), run_id.strip()),
        ).fetchone()
        return _review_row(row) if row else None


def get_review_by_id(review_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM clip_label_review WHERE id = ?",
            (review_id,),
        ).fetchone()
        return _review_row(row) if row else None


def list_reviews(
    *,
    review_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with db_conn() as conn:
        if review_status:
            if review_status not in REVIEW_STATUSES:
                raise ValueError(f"invalid review_status: {review_status}")
            rows = conn.execute(
                """
                SELECT * FROM clip_label_review
                WHERE review_status = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (review_status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM clip_label_review
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [_review_row(r) for r in rows]


def count_reviews(*, review_status: str | None = None) -> int:
    with db_conn() as conn:
        if review_status:
            if review_status not in REVIEW_STATUSES:
                raise ValueError(f"invalid review_status: {review_status}")
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM clip_label_review WHERE review_status = ?",
                (review_status,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM clip_label_review").fetchone()
    return int(row["cnt"]) if row else 0


def list_reviews_by_clip(clip_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM clip_label_review
            WHERE clip_id = ?
            ORDER BY updated_at DESC
            """,
            (clip_id.strip(),),
        ).fetchall()
    return [_review_row(r) for r in rows]


def update_review(
    clip_id: str,
    run_id: str,
    *,
    labels_json: dict[str, Any] | list[Any] | str | None = None,
    review_status: str | None = None,
    reviewer_id: str | None = None,
    reviewed_at: str | None = None,
    expected_updated_at: str | None = None,
) -> dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM clip_label_review
            WHERE clip_id = ? AND run_id = ?
            """,
            (clip_id.strip(), run_id.strip()),
        ).fetchone()
        if row is None:
            raise ValueError(f"review not found: {clip_id}/{run_id}")

        if expected_updated_at is not None and row["updated_at"] != expected_updated_at:
            raise ValueError("review updated_at conflict")

        if review_status is not None and review_status not in REVIEW_STATUSES:
            raise ValueError(f"invalid review_status: {review_status}")

        now = _utc_now_iso()
        new_labels = _dump_json(labels_json) if labels_json is not None else row["labels_json"]
        new_status = review_status if review_status is not None else row["review_status"]
        new_reviewer = reviewer_id if reviewer_id is not None else row["reviewer_id"]
        if reviewed_at is not None:
            new_reviewed_at = reviewed_at
        elif review_status == "reviewed" and row["review_status"] != "reviewed":
            new_reviewed_at = now
        else:
            new_reviewed_at = row["reviewed_at"]

        conn.execute(
            """
            UPDATE clip_label_review
            SET labels_json = ?, review_status = ?, reviewer_id = ?,
                reviewed_at = ?, updated_at = ?
            WHERE clip_id = ? AND run_id = ?
            """,
            (
                new_labels,
                new_status,
                new_reviewer,
                new_reviewed_at,
                now,
                clip_id.strip(),
                run_id.strip(),
            ),
        )

    review = get_review(clip_id, run_id)
    assert review is not None
    return review
