"""SQLite pipeline_run / pipeline_step helpers for local SDK worker."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hmi.config import sdk_pipeline_step_order

_SDK_STEP_IDS = sdk_pipeline_step_order(local=True)
from hmi.local import store


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def upsert_clip_row(
    *,
    clip_id: str,
    clip_dir_name: str,
    content_hash: str,
    bag_oss_key: str,
    active_run_id: str,
) -> None:
    store.execute(
        """
        INSERT OR REPLACE INTO dim_clip (
          clip_id, clip_dir_name, content_hash, bag_oss_key, active_run_id, created_at, updated_at
        ) VALUES (
          ?, ?, ?, ?, ?,
          COALESCE((SELECT created_at FROM dim_clip WHERE clip_id=?), datetime('now')),
          datetime('now')
        )
        """,
        (clip_id, clip_dir_name, content_hash, bag_oss_key, active_run_id, clip_id),
    )


def upsert_run(
    *,
    run_id: str,
    clip_id: str,
    ds: str,
    status: str,
    started_at: str | None = None,
    reset_started_at: bool = False,
) -> None:
    now = _utc_now()
    if reset_started_at or started_at:
        sa = started_at or now
        store.execute(
            """
            INSERT OR REPLACE INTO pipeline_run (
              run_id, clip_id, ds, status, label_granularity, started_at, updated_at, completed_at
            ) VALUES (
              ?, ?, ?, ?, 'clip', ?, ?,
              CASE WHEN ? IN ('completed', 'success') THEN ? ELSE NULL END
            )
            """,
            (run_id, clip_id, ds, status, sa, now, status, now),
        )
        return
    store.execute(
        """
        INSERT OR REPLACE INTO pipeline_run (
          run_id, clip_id, ds, status, label_granularity, started_at, updated_at, completed_at
        ) VALUES (
          ?, ?, ?, ?, 'clip',
          COALESCE((SELECT started_at FROM pipeline_run WHERE run_id=? AND clip_id=? AND ds=?), ?),
          ?,
          CASE WHEN ? IN ('completed', 'success') THEN ? ELSE NULL END
        )
        """,
        (run_id, clip_id, ds, status, run_id, clip_id, ds, now, now, status, now),
    )


def init_sdk_steps(*, run_id: str, clip_id: str, ds: str) -> None:
    store.execute(
        "DELETE FROM pipeline_step WHERE run_id=? AND clip_id=? AND ds=?",
        (run_id, clip_id, ds),
    )
    for step_id in sdk_pipeline_step_order(local=True):
        store.execute(
            """
            INSERT OR REPLACE INTO pipeline_step (
              run_id, clip_id, ds, step_id, status, started_at, finished_at, error_message
            )
            VALUES (?, ?, ?, ?, 'pending', NULL, NULL, NULL)
            """,
            (run_id, clip_id, ds, step_id),
        )


def set_step(
    *,
    run_id: str,
    clip_id: str,
    ds: str,
    step_id: str,
    status: str,
    error_message: str | None = None,
) -> None:
    now = _utc_now()
    started = now if status == "running" else None
    finished = now if status in {"success", "failed", "skipped"} else None
    store.execute(
        """
        UPDATE pipeline_step
        SET status=?, started_at=COALESCE(started_at, ?), finished_at=?, error_message=?
        WHERE run_id=? AND clip_id=? AND ds=? AND step_id=?
        """,
        (status, started, finished, error_message, run_id, clip_id, ds, step_id),
    )
    if store.query_one(
        "SELECT 1 FROM pipeline_step WHERE run_id=? AND clip_id=? AND ds=? AND step_id=?",
        (run_id, clip_id, ds, step_id),
    ) is None:
        store.execute(
            """
            INSERT INTO pipeline_step (
              run_id, clip_id, ds, step_id, status, started_at, finished_at, error_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, clip_id, ds, step_id, status, started, finished, error_message),
        )


def mark_run_from_steps(*, run_id: str, clip_id: str, ds: str) -> str:
    if is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        return "cancelled"
    rows = store.query(
        "SELECT step_id, status FROM pipeline_step WHERE run_id=? AND clip_id=? AND ds=?",
        (run_id, clip_id, ds),
    )
    statuses = {str(r["step_id"]): str(r["status"]) for r in rows}
    if any(statuses.get(sid) == "failed" for sid in _SDK_STEP_IDS):
        run_status = "failed"
    elif any(statuses.get(sid) == "running" for sid in _SDK_STEP_IDS):
        run_status = "running"
    elif all(statuses.get(sid) in {"success", "skipped"} for sid in _SDK_STEP_IDS):
        run_status = "completed"
    else:
        run_status = "running"
    upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status=run_status)
    return run_status


def is_run_cancelled(*, run_id: str, clip_id: str, ds: str) -> bool:
    row = store.query_one(
        "SELECT status FROM pipeline_run WHERE run_id=? AND clip_id=? AND ds=?",
        (run_id, clip_id, ds),
    )
    if row is None:
        return False
    return str(row.get("status") or "").lower() == "cancelled"


def list_runs_needing_sdk(*, limit: int = 4) -> list[dict[str, Any]]:
    rows = store.query(
        """
        SELECT c.clip_id, c.clip_dir_name, c.bag_oss_key, c.active_run_id AS run_id, r.ds, r.status
        FROM dim_clip c
        JOIN pipeline_run r ON r.clip_id = c.clip_id AND r.run_id = c.active_run_id
        JOIN pipeline_step si ON si.run_id = r.run_id AND si.clip_id = r.clip_id AND si.ds = r.ds
          AND si.step_id = 'sdk_infer' AND si.status = 'pending'
        WHERE r.status IN ('pending', 'running')
          AND c.bag_oss_key LIKE 'local://rosbags/%'
        ORDER BY
          COALESCE(
            (SELECT e.started_at FROM pipeline_execution e WHERE e.run_id = r.run_id),
            r.started_at
          ) DESC,
          r.started_at ASC
        LIMIT ?
        """,
        (limit,),
    )
    return [dict(row) for row in rows]


def try_claim_sdk_infer(*, run_id: str, clip_id: str, ds: str) -> bool:
    """Atomically mark sdk_infer running so parallel poller ticks do not double-start."""
    now = _utc_now()
    n = store.execute_rowcount(
        """
        UPDATE pipeline_step
        SET status='running', started_at=?, finished_at=NULL, error_message=NULL
        WHERE run_id=? AND clip_id=? AND ds=? AND step_id='sdk_infer' AND status='pending'
        """,
        (now, run_id, clip_id, ds),
    )
    if n != 1:
        return False
    upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="running")
    return True


def reset_stale_sdk_infer_jobs(*, stale_minutes: int = 120) -> int:
    """Re-queue infer jobs stuck in running (crashed worker / hung API)."""
    if stale_minutes < 1:
        stale_minutes = 1
    rows = store.query(
        """
        SELECT run_id, clip_id, ds, started_at
        FROM pipeline_step
        WHERE step_id='sdk_infer' AND status='running' AND started_at IS NOT NULL
          AND datetime(replace(replace(started_at, 'T', ' '), 'Z', '')) <
              datetime('now', ?)
          AND run_id IN (SELECT run_id FROM pipeline_run WHERE status IN ('pending', 'running'))
        """,
        (f"-{int(stale_minutes)} minutes",),
    )
    reset = 0
    for row in rows:
        rid = str(row["run_id"])
        cid = str(row["clip_id"])
        ds = str(row["ds"])
        store.execute(
            """
            UPDATE pipeline_step
            SET status='pending', started_at=NULL, finished_at=NULL,
                error_message='stale running reset by poller'
            WHERE run_id=? AND clip_id=? AND ds=? AND step_id='sdk_infer' AND status='running'
            """,
            (rid, cid, ds),
        )
        upsert_run(run_id=rid, clip_id=cid, ds=ds, status="pending")
        reset += 1
    return reset
