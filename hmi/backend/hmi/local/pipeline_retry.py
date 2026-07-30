"""Reset a failed local SDK pipeline run to post–rosbag-upload state."""

from __future__ import annotations

import json
import shutil
from typing import Any

from hmi.data_source import LOCAL_ROOT, artifacts_dir, is_local_mode
from hmi.local import pipeline_run as pr
from hmi.local.bag_upload import resolve_local_bag_path
from hmi.local.clip_context import resolve_clip_context
from hmi.local.oss_publish import clip_run_oss_dir
from hmi.local import store
from hmi.services.pipeline_status import DISPATCH_MANIFEST_KEY, bag_pipeline_cache_clear
from hmi.data_source import oss_key_path


_RUN_FACT_TABLES = (
    "clip_parse_summary",
    "fact_frame",
    "fact_event",
    "fact_audio_segment",
    "fact_image_label",
    "fact_embedding",
    "fact_clip_label",
    "fact_clip_embedding",
    "fact_sample_sync_group",
)


def _clear_dispatch_if_points_to(*, clip_id: str, run_id: str) -> None:
    path = oss_key_path(DISPATCH_MANIFEST_KEY)
    if not path.is_file():
        return
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    if not isinstance(doc, dict):
        return
    if str(doc.get("clip_id") or "") == clip_id and str(doc.get("run_id") or "") == run_id:
        path.unlink(missing_ok=True)


def _purge_run_sqlite(*, clip_id: str, run_id: str, ds: str) -> None:
    for tbl in _RUN_FACT_TABLES:
        store.execute(
            f"DELETE FROM {tbl} WHERE clip_id=? AND run_id=? AND ds=?",
            (clip_id, run_id, ds),
        )


def _purge_run_files(*, clip_id: str, run_id: str, clip_dir_name: str) -> None:
    art = artifacts_dir(clip_id, run_id)
    if art.is_dir():
        shutil.rmtree(art, ignore_errors=True)
    oss_run = clip_run_oss_dir(clip_id, run_id)
    if oss_run.is_dir():
        shutil.rmtree(oss_run, ignore_errors=True)
    work = LOCAL_ROOT / "work" / "sdk_runs" / clip_dir_name
    if work.is_dir():
        shutil.rmtree(work, ignore_errors=True)


def reset_local_pipeline_to_post_upload(*, clip_id: str, run_id: str | None = None) -> dict[str, Any]:
    if not is_local_mode():
        raise ValueError("pipeline retry is only available in local mode")

    ctx = resolve_clip_context(clip_id, run_id)
    cid, rid, ds = ctx.clip_id, ctx.run_id, ctx.ds

    run_row = store.query_one(
        "SELECT status FROM pipeline_run WHERE clip_id=? AND run_id=? AND ds=? LIMIT 1",
        (cid, rid, ds),
    )
    if not run_row:
        raise ValueError("pipeline run not found")
    run_status = str(run_row.get("status") or "")
    if run_status not in ("failed", "cancelled"):
        raise ValueError(f"retry only allowed for failed or cancelled runs (current: {run_status})")

    dim = store.query_one("SELECT active_run_id, bag_oss_key FROM dim_clip WHERE clip_id=?", (cid,))
    if not dim:
        raise ValueError("clip not found")
    if str(dim.get("active_run_id") or "") != rid:
        raise ValueError("retry only supported for the clip active_run_id")

    bag_key = str(dim.get("bag_oss_key") or "")
    if not resolve_local_bag_path(bag_key):
        raise ValueError("rosbag file missing on disk; re-upload the .bag file")

    _purge_run_files(clip_id=cid, run_id=rid, clip_dir_name=ctx.clip_dir_name)
    _purge_run_sqlite(clip_id=cid, run_id=rid, ds=ds)
    _clear_dispatch_if_points_to(clip_id=cid, run_id=rid)

    pr.upsert_run(run_id=rid, clip_id=cid, ds=ds, status="pending", reset_started_at=True)
    pr.init_sdk_steps(run_id=rid, clip_id=cid, ds=ds)
    pr.set_step(run_id=rid, clip_id=cid, ds=ds, step_id="sdk_discover", status="success")

    bag_pipeline_cache_clear()
    from hmi.db import cache_clear
    from hmi.services.clips_local import get_clip_overview

    cache_clear()
    overview = get_clip_overview(cid, rid)
    return {
        "ok": True,
        "clip_id": cid,
        "run_id": rid,
        "ds": ds,
        "pipeline_status": overview.get("pipeline_status"),
        "steps": overview.get("steps"),
    }
