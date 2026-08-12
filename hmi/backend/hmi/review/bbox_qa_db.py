"""Clip-level BBox quality marks (sidecar; never merges into labels_json)."""

from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Literal

from hmi.app_db import _utc_now_iso, db_conn

BboxQaStatus = Literal["bbox_ok", "bbox_bad", "bbox_skip"]
BBOX_QA_STATUSES = frozenset({"bbox_ok", "bbox_bad", "bbox_skip"})

_BBOX_QA_SCHEMA = """
CREATE TABLE IF NOT EXISTS clip_bbox_qa (
  id TEXT PRIMARY KEY,
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('bbox_ok','bbox_bad','bbox_skip')),
  note TEXT,
  reviewer_id TEXT REFERENCES app_user(id),
  reviewed_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(clip_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_clip_bbox_qa_clip
  ON clip_bbox_qa (clip_id, run_id);

CREATE INDEX IF NOT EXISTS idx_clip_bbox_qa_status
  ON clip_bbox_qa (status, updated_at DESC);
"""


def ensure_bbox_qa_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_BBOX_QA_SCHEMA)
        conn.commit()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "clip_id": row["clip_id"],
        "run_id": row["run_id"],
        "status": row["status"],
        "note": row["note"],
        "reviewer_id": row["reviewer_id"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def get_bbox_qa(clip_id: str, run_id: str) -> dict[str, Any] | None:
    clip_id = clip_id.strip()
    run_id = run_id.strip()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM clip_bbox_qa WHERE clip_id = ? AND run_id = ?",
            (clip_id, run_id),
        ).fetchone()
        return _row(row) if row else None


def upsert_bbox_qa(
    clip_id: str,
    run_id: str,
    *,
    status: str,
    note: str | None,
    reviewer_id: str,
    reviewed_at: str | None = None,
) -> dict[str, Any]:
    clip_id = clip_id.strip()
    run_id = run_id.strip()
    status = status.strip()
    if status not in BBOX_QA_STATUSES:
        raise ValueError(f"invalid bbox_qa status: {status}")
    note_val = (note or "").strip() or None
    now = reviewed_at or _utc_now_iso()
    with db_conn() as conn:
        existing = conn.execute(
            "SELECT id, created_at FROM clip_bbox_qa WHERE clip_id = ? AND run_id = ?",
            (clip_id, run_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE clip_bbox_qa
                SET status = ?, note = ?, reviewer_id = ?, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, note_val, reviewer_id, now, now, existing["id"]),
            )
            row_id = existing["id"]
        else:
            row_id = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO clip_bbox_qa (
                  id, clip_id, run_id, status, note, reviewer_id,
                  reviewed_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (row_id, clip_id, run_id, status, note_val, reviewer_id, now, now, now),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM clip_bbox_qa WHERE id = ?", (row_id,)).fetchone()
        assert row is not None
        return _row(row)


def bbox_qa_map_for_clips(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Batch lookup for clip cards; empty input → empty map."""
    if not pairs:
        return {}
    wanted = {(c.strip(), r.strip()) for c, r in pairs if c and r}
    if not wanted:
        return {}
    clip_ids = list({c for c, _ in wanted})
    placeholders = ",".join("?" * len(clip_ids))
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM clip_bbox_qa WHERE clip_id IN ({placeholders})",
            clip_ids,
        ).fetchall()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["clip_id"], row["run_id"])
        if key in wanted:
            out[key] = _row(row)
    return out
