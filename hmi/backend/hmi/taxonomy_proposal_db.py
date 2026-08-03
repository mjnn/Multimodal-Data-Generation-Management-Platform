"""Taxonomy improvement proposals (M10)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

PROPOSAL_TYPES = frozenset(
    {"new_node", "extend_enum", "deprecate_node", "scene_cluster", "other"}
)
PROPOSAL_STATUSES = frozenset({"open", "merged", "rejected"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS taxonomy_proposal (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  proposal_type TEXT NOT NULL CHECK (proposal_type IN (
    'new_node','extend_enum','deprecate_node','scene_cluster','other'
  )),
  target_label_id TEXT,
  suggested_patch_json TEXT,
  evidence_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','merged','rejected')),
  taxonomy_version_id TEXT REFERENCES label_taxonomy_version(id),
  merged_version_id TEXT REFERENCES label_taxonomy_version(id),
  created_by TEXT REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_taxonomy_proposal_status
  ON taxonomy_proposal (status, created_at DESC);
"""


def ensure_taxonomy_proposal_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_SCHEMA)
        conn.commit()


def _row_to_proposal(row: sqlite3.Row) -> dict[str, Any]:
    evidence = row["evidence_json"]
    patch = row["suggested_patch_json"]
    return {
        "id": row["id"],
        "title": row["title"],
        "proposal_type": row["proposal_type"],
        "target_label_id": row["target_label_id"],
        "suggested_patch_json": json.loads(patch) if patch else None,
        "evidence": json.loads(evidence) if evidence else {},
        "status": row["status"],
        "taxonomy_version_id": row["taxonomy_version_id"],
        "merged_version_id": row["merged_version_id"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_proposal(
    *,
    title: str,
    proposal_type: str,
    evidence: dict[str, Any],
    created_by: str,
    target_label_id: str | None = None,
    suggested_patch_json: dict[str, Any] | None = None,
    taxonomy_version_id: str | None = None,
) -> dict[str, Any]:
    ensure_taxonomy_proposal_schema()
    ptype = str(proposal_type).strip()
    if ptype not in PROPOSAL_TYPES:
        raise ValueError(f"invalid proposal_type: {ptype}")
    pid = str(uuid.uuid4())
    now = _utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO taxonomy_proposal (
              id, title, proposal_type, target_label_id, suggested_patch_json,
              evidence_json, status, taxonomy_version_id, merged_version_id,
              created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, NULL, ?, ?, ?)
            """,
            (
                pid,
                title.strip(),
                ptype,
                target_label_id,
                json.dumps(suggested_patch_json, ensure_ascii=False)
                if suggested_patch_json
                else None,
                json.dumps(evidence, ensure_ascii=False),
                taxonomy_version_id,
                created_by,
                now,
                now,
            ),
        )
        row = conn.execute(
            "SELECT * FROM taxonomy_proposal WHERE id = ?", (pid,)
        ).fetchone()
    assert row is not None
    return _row_to_proposal(row)


def list_proposals(*, status: str | None = None, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
    ensure_taxonomy_proposal_schema()
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with db_conn() as conn:
        total = int(
            conn.execute(f"SELECT COUNT(*) AS cnt FROM taxonomy_proposal {where}", params).fetchone()["cnt"]
        )
        rows = conn.execute(
            f"""
            SELECT * FROM taxonomy_proposal {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()
    return [_row_to_proposal(r) for r in rows], total


def get_proposal(proposal_id: str) -> dict[str, Any] | None:
    ensure_taxonomy_proposal_schema()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM taxonomy_proposal WHERE id = ?", (proposal_id,)
        ).fetchone()
    return _row_to_proposal(row) if row else None


def update_proposal_status(
    proposal_id: str,
    *,
    status: str,
    merged_version_id: str | None = None,
) -> dict[str, Any]:
    ensure_taxonomy_proposal_schema()
    st = str(status).strip()
    if st not in PROPOSAL_STATUSES:
        raise ValueError(f"invalid status: {st}")
    now = _utc_now_iso()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM taxonomy_proposal WHERE id = ?", (proposal_id,)
        ).fetchone()
        if row is None:
            raise ValueError("proposal not found")
        conn.execute(
            """
            UPDATE taxonomy_proposal
            SET status = ?, merged_version_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (st, merged_version_id, now, proposal_id),
        )
        updated = conn.execute(
            "SELECT * FROM taxonomy_proposal WHERE id = ?", (proposal_id,)
        ).fetchone()
    assert updated is not None
    return _row_to_proposal(updated)
