"""Review assignment batches — admin dispatch + reviewer claim."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

BATCH_STATUSES = frozenset({"open", "closed"})
ITEM_STATUSES = frozenset({"pending", "claimed", "done"})
BATCH_KINDS = frozenset({"low_confidence", "assigned", "public_pool"})

_ASSIGNMENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS review_assignment_batch (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  label_ids_json TEXT NOT NULL,
  queue_limit INTEGER NOT NULL,
  assignee_id TEXT REFERENCES app_user(id),
  status TEXT NOT NULL CHECK (status IN ('open','closed')),
  created_by TEXT REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_assignment_batch_status
  ON review_assignment_batch (status, created_at DESC);

CREATE TABLE IF NOT EXISTS review_assignment_item (
  id TEXT PRIMARY KEY,
  batch_id TEXT NOT NULL REFERENCES review_assignment_batch(id) ON DELETE CASCADE,
  clip_id TEXT NOT NULL,
  run_id TEXT NOT NULL,
  label_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending','claimed','done')),
  assignee_id TEXT REFERENCES app_user(id),
  claimed_at TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(batch_id, clip_id, run_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_review_assignment_item_batch
  ON review_assignment_item (batch_id, status, sort_order);

CREATE INDEX IF NOT EXISTS idx_review_assignment_item_assignee
  ON review_assignment_item (assignee_id, status, batch_id);

CREATE TABLE IF NOT EXISTS review_workbench_session (
  batch_id TEXT NOT NULL REFERENCES review_assignment_batch(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
  staged_json TEXT NOT NULL DEFAULT '{}',
  current_index INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (batch_id, user_id)
);
"""


def _ensure_batch_kind_column(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(review_assignment_batch)").fetchall()}
    if "batch_kind" not in cols:
        conn.execute(
            """
            ALTER TABLE review_assignment_batch
            ADD COLUMN batch_kind TEXT NOT NULL DEFAULT 'public_pool'
            """
        )


def ensure_assignment_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_ASSIGNMENT_SCHEMA)
        _ensure_batch_kind_column(conn)
        conn.commit()


def _parse_label_ids(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(x) for x in parsed if str(x).strip()]


def _batch_row(row: sqlite3.Row, *, stats: dict[str, int] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "name": row["name"],
        "label_ids": _parse_label_ids(row["label_ids_json"]),
        "queue_limit": int(row["queue_limit"]),
        "assignee_id": row["assignee_id"],
        "batch_kind": row["batch_kind"] if "batch_kind" in row.keys() else "public_pool",
        "status": row["status"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if stats:
        out.update(stats)
    return out


def create_batch(
    *,
    name: str,
    label_ids: list[str],
    queue_limit: int,
    assignee_id: str | None,
    created_by: str,
    items: list[dict[str, Any]],
    batch_kind: str = "public_pool",
) -> dict[str, Any]:
    if batch_kind not in BATCH_KINDS:
        raise ValueError(f"无效任务类型: {batch_kind}")
    if not label_ids:
        raise ValueError("至少选择一个标签")
    if queue_limit < 1:
        raise ValueError("队列数量至少为 1")
    if not items:
        raise ValueError("当前标签范围内没有可派发的校核条目")

    batch_id = str(uuid.uuid4())
    now = _utc_now_iso()
    initial_status = "claimed" if assignee_id else "pending"

    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO review_assignment_batch (
              id, name, label_ids_json, queue_limit, assignee_id, batch_kind, status,
              created_by, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (
                batch_id,
                name.strip(),
                json.dumps(label_ids, ensure_ascii=False),
                queue_limit,
                assignee_id,
                batch_kind,
                created_by,
                now,
                now,
            ),
        )
        for idx, item in enumerate(items):
            conn.execute(
                """
                INSERT INTO review_assignment_item (
                  id, batch_id, clip_id, run_id, label_id, status, assignee_id,
                  claimed_at, sort_order, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    batch_id,
                    item["clip_id"],
                    item["run_id"],
                    item["label_id"],
                    initial_status,
                    assignee_id,
                    now if assignee_id else None,
                    idx,
                    now,
                    now,
                ),
            )
    batch = get_batch(batch_id)
    assert batch is not None
    return batch


def get_batch(batch_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM review_assignment_batch WHERE id=?",
            (batch_id,),
        ).fetchone()
        if not row:
            return None
        stats = _batch_stats(conn, batch_id)
        return _batch_row(row, stats=stats)


def list_batches(*, status: str | None = None) -> list[dict[str, Any]]:
    with db_conn() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM review_assignment_batch
                WHERE status=?
                ORDER BY created_at DESC
                """,
                (status,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM review_assignment_batch ORDER BY created_at DESC"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            stats = _batch_stats(conn, row["id"])
            out.append(_batch_row(row, stats=stats))
        return out


def _batch_stats(conn: sqlite3.Connection, batch_id: str) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT status, assignee_id FROM review_assignment_item WHERE batch_id=?
        """,
        (batch_id,),
    ).fetchall()
    total = len(rows)
    pending = sum(1 for r in rows if r["status"] == "pending" and r["assignee_id"] is None)
    claimed = sum(1 for r in rows if r["status"] == "claimed")
    done = sum(1 for r in rows if r["status"] == "done")
    return {
        "item_total": total,
        "item_pending": pending,
        "item_claimed": claimed,
        "item_done": done,
    }


def list_batch_items(batch_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM review_assignment_item
            WHERE batch_id=?
            ORDER BY sort_order ASC, label_id ASC
            """,
            (batch_id,),
        ).fetchall()
        return [_item_row(r) for r in rows]


def _item_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "batch_id": row["batch_id"],
        "clip_id": row["clip_id"],
        "run_id": row["run_id"],
        "label_id": row["label_id"],
        "status": row["status"],
        "assignee_id": row["assignee_id"],
        "claimed_at": row["claimed_at"],
        "sort_order": int(row["sort_order"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def claim_items(
    *,
    batch_id: str,
    assignee_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("领取数量至少为 1")
    now = _utc_now_iso()
    with db_conn() as conn:
        batch = conn.execute(
            "SELECT id, status, batch_kind FROM review_assignment_batch WHERE id=?",
            (batch_id,),
        ).fetchone()
        if not batch:
            raise ValueError("任务不存在")
        if batch["status"] != "open":
            raise ValueError("任务已关闭，无法领取")
        kind = batch["batch_kind"] if "batch_kind" in batch.keys() else "public_pool"
        if kind != "public_pool":
            raise ValueError("仅「任务池公开领取」类型可在此领取条目")

        rows = conn.execute(
            """
            SELECT id FROM review_assignment_item
            WHERE batch_id=? AND status='pending' AND assignee_id IS NULL
            ORDER BY sort_order ASC
            LIMIT ?
            """,
            (batch_id, limit),
        ).fetchall()
        if not rows:
            return []

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"""
            UPDATE review_assignment_item
            SET status='claimed', assignee_id=?, claimed_at=?, updated_at=?
            WHERE id IN ({placeholders})
            """,
            (assignee_id, now, now, *ids),
        )
        conn.execute(
            "UPDATE review_assignment_batch SET updated_at=? WHERE id=?",
            (now, batch_id),
        )

        claimed = conn.execute(
            f"""
            SELECT * FROM review_assignment_item WHERE id IN ({placeholders})
            ORDER BY sort_order ASC
            """,
            tuple(ids),
        ).fetchall()
        return [_item_row(r) for r in claimed]


def list_batch_assignee_summaries(batch_id: str) -> list[dict[str, Any]]:
    """Per-reviewer claim/done counts for admin reporting (public pool & multi-claim batches)."""
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT
              assignee_id,
              SUM(CASE WHEN status='claimed' THEN 1 ELSE 0 END) AS in_progress,
              SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done,
              MIN(claimed_at) AS first_claimed_at,
              MAX(updated_at) AS last_activity_at
            FROM review_assignment_item
            WHERE batch_id=? AND assignee_id IS NOT NULL
            GROUP BY assignee_id
            ORDER BY first_claimed_at ASC
            """,
            (batch_id,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            done = int(row["done"] or 0)
            in_progress = int(row["in_progress"] or 0)
            out.append(
                {
                    "assignee_id": row["assignee_id"],
                    "done": done,
                    "in_progress": in_progress,
                    "claimed_total": done + in_progress,
                    "first_claimed_at": row["first_claimed_at"],
                    "last_activity_at": row["last_activity_at"],
                }
            )
        return out


def list_reviewer_batches(assignee_id: str, *, view: str = "all") -> list[dict[str, Any]]:
    """Batches visible to reviewer: open pool, pre-assigned, or with their claim/done history."""
    if view not in ("active", "completed", "all"):
        view = "all"
    with db_conn() as conn:
        batch_ids: set[str] = set()

        for r in conn.execute(
            """
            SELECT DISTINCT batch_id FROM review_assignment_item WHERE assignee_id=?
            """,
            (assignee_id,),
        ).fetchall():
            batch_ids.add(r["batch_id"])

        for r in conn.execute(
            """
            SELECT id FROM review_assignment_batch
            WHERE status='open' AND assignee_id=?
            """,
            (assignee_id,),
        ).fetchall():
            batch_ids.add(r["id"])

        for r in conn.execute(
            """
            SELECT DISTINCT i.batch_id FROM review_assignment_item i
            JOIN review_assignment_batch b ON b.id = i.batch_id
            WHERE i.status='pending' AND i.assignee_id IS NULL
              AND b.status='open' AND b.assignee_id IS NULL
            """
        ).fetchall():
            batch_ids.add(r["batch_id"])

        out: list[dict[str, Any]] = []
        for batch_id in batch_ids:
            row = conn.execute(
                "SELECT * FROM review_assignment_batch WHERE id=?",
                (batch_id,),
            ).fetchone()
            if not row:
                continue
            stats = _batch_stats(conn, batch_id)
            mine = conn.execute(
                """
                SELECT status, COUNT(*) AS cnt FROM review_assignment_item
                WHERE batch_id=? AND assignee_id=?
                GROUP BY status
                """,
                (batch_id, assignee_id),
            ).fetchall()
            mine_map = {r["status"]: int(r["cnt"]) for r in mine}
            my_claimed = mine_map.get("claimed", 0)
            my_done = mine_map.get("done", 0)
            batch = _batch_row(row, stats=stats)
            batch["my_claimed"] = my_claimed
            batch["my_done"] = my_done
            session = get_workbench_session(batch_id, assignee_id)
            batch["my_staged_count"] = len(session.get("staged") or {}) if session else 0
            batch["my_session_updated_at"] = session.get("updated_at") if session else None

            kind = batch.get("batch_kind") or "public_pool"
            batch_open = batch["status"] == "open"
            can_claim = (
                kind == "public_pool"
                and batch_open
                and (batch.get("item_pending") or 0) > 0
            )
            my_pending = my_claimed
            has_staged = (batch.get("my_staged_count") or 0) > 0
            is_active = my_pending > 0 or has_staged or can_claim
            is_completed = my_done > 0 and my_pending == 0

            if view == "active" and not is_active:
                continue
            if view == "completed" and not is_completed:
                continue

            out.append(batch)
        out.sort(key=lambda b: b["updated_at"], reverse=True)
        return out


def get_work_item_keys(batch_id: str, assignee_id: str) -> list[tuple[str, str, str]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT clip_id, run_id, label_id FROM review_assignment_item
            WHERE batch_id=? AND assignee_id=? AND status='claimed'
            ORDER BY sort_order ASC
            """,
            (batch_id, assignee_id),
        ).fetchall()
        return [(r["clip_id"], r["run_id"], r["label_id"]) for r in rows]


def _maybe_close_batch(conn: sqlite3.Connection, batch_id: str) -> bool:
    row = conn.execute(
        "SELECT status FROM review_assignment_batch WHERE id=?",
        (batch_id,),
    ).fetchone()
    if not row or row["status"] != "open":
        return False
    stats = _batch_stats(conn, batch_id)
    if stats["item_total"] <= 0:
        return False
    if stats["item_pending"] > 0 or stats["item_claimed"] > 0:
        return False
    now = _utc_now_iso()
    conn.execute(
        "UPDATE review_assignment_batch SET status='closed', updated_at=? WHERE id=?",
        (now, batch_id),
    )
    return True


def mark_item_done(
    clip_id: str,
    run_id: str,
    label_id: str,
    assignee_id: str,
    *,
    batch_id: str | None = None,
) -> bool:
    """Mark assignment item done; auto-close batch when all items are finished."""
    now = _utc_now_iso()
    with db_conn() as conn:
        if batch_id:
            rows = conn.execute(
                """
                SELECT batch_id FROM review_assignment_item
                WHERE batch_id=? AND clip_id=? AND run_id=? AND label_id=?
                  AND assignee_id=? AND status='claimed'
                """,
                (batch_id, clip_id, run_id, label_id, assignee_id),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT batch_id FROM review_assignment_item
                WHERE clip_id=? AND run_id=? AND label_id=? AND assignee_id=?
                  AND status='claimed'
                """,
                (clip_id, run_id, label_id, assignee_id),
            ).fetchall()
        if not rows:
            return False
        if batch_id:
            conn.execute(
                """
                UPDATE review_assignment_item
                SET status='done', updated_at=?
                WHERE batch_id=? AND clip_id=? AND run_id=? AND label_id=?
                  AND assignee_id=? AND status='claimed'
                """,
                (now, batch_id, clip_id, run_id, label_id, assignee_id),
            )
        else:
            conn.execute(
                """
                UPDATE review_assignment_item
                SET status='done', updated_at=?
                WHERE clip_id=? AND run_id=? AND label_id=? AND assignee_id=?
                  AND status='claimed'
                """,
                (now, clip_id, run_id, label_id, assignee_id),
            )
        closed_any = False
        for row in rows:
            if _maybe_close_batch(conn, row["batch_id"]):
                closed_any = True
        return closed_any or bool(rows)


def close_batch(batch_id: str) -> dict[str, Any] | None:
    now = _utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            "UPDATE review_assignment_batch SET status='closed', updated_at=? WHERE id=?",
            (now, batch_id),
        )
    return get_batch(batch_id)


def _task_key(clip_id: str, run_id: str, label_id: str) -> str:
    return f"{clip_id}\0{run_id}\0{label_id}"


def get_workbench_session(batch_id: str, user_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT staged_json, current_index, updated_at
            FROM review_workbench_session
            WHERE batch_id=? AND user_id=?
            """,
            (batch_id, user_id),
        ).fetchone()
        if not row:
            return None
        try:
            staged = json.loads(row["staged_json"])
        except json.JSONDecodeError:
            staged = {}
        if not isinstance(staged, dict):
            staged = {}
        return {
            "batch_id": batch_id,
            "user_id": user_id,
            "staged": staged,
            "current_index": int(row["current_index"]),
            "updated_at": row["updated_at"],
        }


def save_workbench_session(
    *,
    batch_id: str,
    user_id: str,
    staged: dict[str, Any],
    current_index: int,
) -> dict[str, Any]:
    allowed_keys = {
        _task_key(c, r, l) for c, r, l in get_work_item_keys(batch_id, user_id)
    }
    filtered = {k: v for k, v in staged.items() if k in allowed_keys and isinstance(v, dict)}
    now = _utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO review_workbench_session (
              batch_id, user_id, staged_json, current_index, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(batch_id, user_id) DO UPDATE SET
              staged_json=excluded.staged_json,
              current_index=excluded.current_index,
              updated_at=excluded.updated_at
            """,
            (
                batch_id,
                user_id,
                json.dumps(filtered, ensure_ascii=False),
                max(0, int(current_index)),
                now,
            ),
        )
    session = get_workbench_session(batch_id, user_id)
    assert session is not None
    return session


def clear_workbench_session(batch_id: str, user_id: str) -> None:
    with db_conn() as conn:
        conn.execute(
            "DELETE FROM review_workbench_session WHERE batch_id=? AND user_id=?",
            (batch_id, user_id),
        )
