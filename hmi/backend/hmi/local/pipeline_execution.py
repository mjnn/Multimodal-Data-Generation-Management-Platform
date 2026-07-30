"""Batch pipeline execution queue (one run_id, many clips)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from hmi.local import bag_upload, pipeline_run as pr, store

_SH_TZ = ZoneInfo("Asia/Shanghai")


def _utc_now_z() -> str:
    return datetime.now(ZoneInfo("UTC")).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def execution_label_now() -> str:
    return datetime.now(_SH_TZ).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def create_execution_record(*, run_id: str, label: str, started_at: str) -> None:
    store.execute(
        """
        INSERT OR REPLACE INTO pipeline_execution (run_id, label, started_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (run_id, label, started_at, started_at),
    )


def enqueue_rosbags_batch(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    if not files:
        raise ValueError("at least one .bag file required")

    run_id = str(uuid.uuid4())
    started_at = _utc_now_z()
    label = execution_label_now()
    create_execution_record(run_id=run_id, label=label, started_at=started_at)

    ds = datetime.now(ZoneInfo("UTC")).strftime("%Y%m%d")
    clips: list[dict[str, Any]] = []

    for filename, data in files:
        saved = bag_upload.save_uploaded_rosbag(
            filename,
            data,
            run_id=run_id,
            ds=ds,
            execution_started_at=started_at,
        )
        clips.append(
            {
                "clip_id": saved["clip_id"],
                "oss_key": saved["oss_key"],
                "bag_oss_key": saved["bag_oss_key"],
                "local_path": saved.get("local_path"),
                "size_bytes": saved.get("size_bytes"),
            }
        )

    return {
        "run_id": run_id,
        "label": label,
        "started_at": started_at,
        "ds": ds,
        "clips": clips,
    }


def _aggregate_status(statuses: list[str]) -> str:
    if not statuses:
        return "pending"
    norm = [str(s or "pending").lower() for s in statuses]
    if any(s == "failed" for s in norm):
        return "failed"
    if any(s == "running" for s in norm):
        return "running"
    if any(s == "pending" for s in norm):
        return "pending"
    if all(s in {"completed", "success"} for s in norm):
        return "completed"
    if all(s == "cancelled" for s in norm):
        return "cancelled"
    if any(s == "cancelled" for s in norm):
        return "cancelled"
    return "running"


def cancel_execution(run_id: str) -> dict[str, Any]:
    """Stop pending/running clips in a batch; completed/failed clips are left unchanged."""
    run_id = run_id.strip()
    if not run_id:
        raise ValueError("run_id required")

    exec_row = store.query_one(
        "SELECT run_id FROM pipeline_execution WHERE run_id=?",
        (run_id,),
    )
    if exec_row is None:
        raise ValueError(f"execution not found: {run_id}")

    runs = store.query(
        "SELECT clip_id, ds, status FROM pipeline_run WHERE run_id=?",
        (run_id,),
    )
    if not runs:
        raise ValueError(f"no clips for execution: {run_id}")

    cancel_msg = "用户中止执行"
    now = _utc_now_z()
    cancelled = 0
    unchanged = 0

    for row in runs:
        clip_id = str(row["clip_id"])
        ds = str(row["ds"])
        status = str(row.get("status") or "pending").lower()
        if status in {"completed", "success", "failed", "cancelled"}:
            unchanged += 1
            continue
        store.execute(
            """
            UPDATE pipeline_step
            SET status='skipped', finished_at=?, error_message=?
            WHERE run_id=? AND clip_id=? AND ds=?
              AND status IN ('pending', 'running')
            """,
            (now, cancel_msg, run_id, clip_id, ds),
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="cancelled")
        cancelled += 1

    if cancelled == 0 and unchanged == len(runs):
        raise ValueError("该批次已全部结束，无法中止")

    from hmi.db import cache_clear

    cache_clear()
    return {
        "run_id": run_id,
        "cancelled_clips": cancelled,
        "unchanged_clips": unchanged,
    }


def list_executions(*, page: int = 1, page_size: int = 10) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size

    total_row = store.query_one("SELECT COUNT(*) AS n FROM pipeline_execution")
    total = int(total_row["n"]) if total_row else 0

    rows = store.query(
        """
        SELECT run_id, label, started_at, created_at
        FROM pipeline_execution
        ORDER BY started_at DESC
        LIMIT ? OFFSET ?
        """,
        (page_size, offset),
    )

    from hmi.config import pipeline_step_label, sdk_pipeline_step_order
    from hmi.db import normalize_pipeline_status

    items: list[dict[str, Any]] = []
    for row in rows:
        run_id = str(row["run_id"])
        run_rows = store.query(
            """
            SELECT r.clip_id, r.ds, r.status, r.started_at, r.updated_at, c.clip_dir_name
            FROM pipeline_run r
            JOIN dim_clip c ON c.clip_id = r.clip_id
            WHERE r.run_id=?
            ORDER BY r.started_at ASC, c.clip_dir_name ASC
            """,
            (run_id,),
        )
        clip_items: list[dict[str, Any]] = []
        statuses: list[str] = []
        for rr in run_rows:
            clip_id = str(rr["clip_id"])
            ds = str(rr["ds"])
            status = str(rr.get("status") or "pending")
            statuses.append(status)
            step_rows = store.query(
                """
                SELECT step_id, status, error_message FROM pipeline_step
                WHERE run_id=? AND clip_id=? AND ds=?
                """,
                (run_id, clip_id, ds),
            )
            step_map = {str(s["step_id"]): s for s in step_rows}
            order = sdk_pipeline_step_order(local=True)
            steps = [
                {
                    "step_id": sid,
                    "label": pipeline_step_label(sid, local=True),
                    "status": normalize_pipeline_status(
                        str((step_map.get(sid) or {}).get("status") or "pending")
                    ),
                    "error_message": str((step_map.get(sid) or {}).get("error_message") or "").strip()
                    or None,
                }
                for sid in order
                if sid not in ("job0_discover", "sdk_discover")
            ]
            clip_items.append(
                {
                    "clip_id": clip_id,
                    "clip_dir_name": str(rr.get("clip_dir_name") or clip_id[:24]),
                    "ds": ds,
                    "pipeline_status": normalize_pipeline_status(status),
                    "pipeline_created_at": str(rr.get("started_at") or row.get("started_at") or ""),
                    "pipeline_updated_at": str(rr.get("updated_at") or "") or None,
                    "steps": steps,
                }
            )

        items.append(
            {
                "run_id": run_id,
                "label": str(row.get("label") or ""),
                "started_at": str(row.get("started_at") or ""),
                "created_at": str(row.get("created_at") or ""),
                "pipeline_status": _aggregate_status(statuses),
                "clip_count": len(clip_items),
                "clips": clip_items,
            }
        )

    return {"items": items, "total": total, "page": page, "page_size": page_size}


def backfill_executions_from_runs(conn) -> None:
    """One-time migration: create execution rows for legacy runs."""
    conn.execute(
        """
        INSERT OR IGNORE INTO pipeline_execution (run_id, label, started_at, created_at)
        SELECT run_id,
               COALESCE(MIN(started_at), datetime('now')),
               COALESCE(MIN(started_at), datetime('now')),
               COALESCE(MIN(started_at), datetime('now'))
        FROM pipeline_run
        GROUP BY run_id
        """
    )
