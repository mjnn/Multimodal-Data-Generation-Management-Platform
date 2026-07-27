"""Resolve clip context from local SQLite."""

from __future__ import annotations

from dataclasses import dataclass

from hmi.local import store


@dataclass
class LocalClipContext:
    clip_id: str
    run_id: str
    ds: str
    bag_oss_key: str
    clip_dir_name: str
    start_time_ns: int
    end_time_ns: int
    duration_sec: float


def get_dim_clip(clip_id: str) -> dict:
    row = store.query_one("SELECT * FROM dim_clip WHERE clip_id=?", (clip_id,))
    if not row:
        raise ValueError(f"clip not found: {clip_id}")
    return row


def resolve_ds_for_run(clip_id: str, run_id: str) -> str:
    row = store.query_one(
        "SELECT ds FROM pipeline_run WHERE clip_id=? AND run_id=? ORDER BY ds DESC LIMIT 1",
        (clip_id, run_id),
    )
    if row and row.get("ds"):
        return str(row["ds"])
    row = store.query_one(
        "SELECT ds FROM pipeline_step WHERE run_id=? ORDER BY ds DESC LIMIT 1",
        (run_id,),
    )
    if row and row.get("ds"):
        return str(row["ds"])
    raise ValueError(f"No ds for clip={clip_id} run={run_id}")


def resolve_clip_context(clip_id: str, run_id: str | None = None) -> LocalClipContext:
    dim = get_dim_clip(clip_id)
    resolved_run = run_id or str(dim.get("active_run_id") or "")
    if not resolved_run:
        raise ValueError(f"No active_run_id for clip_id={clip_id}")
    ds = resolve_ds_for_run(clip_id, resolved_run)
    summary = store.query_one(
        "SELECT start_time_ns, end_time_ns, duration_sec FROM clip_parse_summary "
        "WHERE clip_id=? AND run_id=? AND ds=? LIMIT 1",
        (clip_id, resolved_run, ds),
    )
    if summary:
        start_ns = int(summary["start_time_ns"] or 0)
        end_ns = int(summary["end_time_ns"] or 0)
        duration = float(summary["duration_sec"] or 0.0)
    else:
        start_ns, end_ns, duration = 0, 0, 0.0
    return LocalClipContext(
        clip_id=clip_id,
        run_id=resolved_run,
        ds=ds,
        bag_oss_key=str(dim.get("bag_oss_key") or ""),
        clip_dir_name=str(dim.get("clip_dir_name") or clip_id[:24]),
        start_time_ns=start_ns,
        end_time_ns=end_ns,
        duration_sec=duration,
    )
