"""Bag / clip pipeline status from MC (partition-safe, active run first)."""

from __future__ import annotations

import json
from typing import Any

from cachetools import TTLCache

from hmi.clip_context import (
    find_clip_id_by_bag_key,
    get_dim_clip,
    list_ds_partitions,
    resolve_ds_for_run,
)
from hmi.config import PIPELINE_STEP_ORDER, STEP_LABELS, get_settings, table_name
from hmi.db import normalize_pipeline_status, query, sql_quote
from hmi.oss_signer import _bucket

_bag_pipeline_cache: TTLCache = TTLCache(maxsize=32, ttl=60)
_bag_key_clip_cache: TTLCache = TTLCache(maxsize=64, ttl=120)
_dispatch_manifest_cache: TTLCache = TTLCache(maxsize=1, ttl=15)
DISPATCH_MANIFEST_KEY = "pipeline/dispatch/latest.json"


def bag_pipeline_cache_clear() -> None:
    _bag_pipeline_cache.clear()
    _bag_key_clip_cache.clear()
    _dispatch_manifest_cache.clear()


def _read_dispatch_manifest() -> dict[str, Any] | None:
    if "manifest" in _dispatch_manifest_cache:
        return _dispatch_manifest_cache["manifest"]
    try:
        raw = _bucket().get_object(DISPATCH_MANIFEST_KEY).read()
        loaded = json.loads(raw.decode("utf-8"))
        manifest = loaded if isinstance(loaded, dict) else None
    except Exception:
        manifest = None
    _dispatch_manifest_cache["manifest"] = manifest
    return manifest


def _resolve_from_manifest(oss_key: str) -> dict[str, str] | None:
    manifest = _read_dispatch_manifest()
    if not manifest or str(manifest.get("action") or "") != "run":
        return None
    bag_key = str(manifest.get("bag_oss_key") or "").strip()
    if bag_key != oss_key.strip():
        return None
    clip_id = str(manifest.get("clip_id") or "").strip()
    run_id = str(manifest.get("run_id") or "").strip()
    if not clip_id or not run_id:
        return None
    return {"clip_id": clip_id, "run_id": run_id}


def _pending_steps(*, include_job0: bool = True) -> list[dict[str, str]]:
    order = PIPELINE_STEP_ORDER if include_job0 else tuple(
        s for s in PIPELINE_STEP_ORDER if s != "job0_discover"
    )
    return [
        {"step_id": sid, "label": STEP_LABELS.get(sid, sid), "status": "pending"}
        for sid in order
    ]


def _clip_id_for_bag(oss_key: str) -> str | None:
    key = oss_key.strip()
    if key in _bag_key_clip_cache:
        return _bag_key_clip_cache[key]
    clip_id = find_clip_id_by_bag_key(key)
    if clip_id:
        _bag_key_clip_cache[key] = clip_id
    return clip_id


def _query_run_status(clip_id: str, run_id: str, ds: str) -> str:
    settings = get_settings()
    rows = query(
        f"SELECT status FROM {table_name(settings, 'pipeline_run')} "
        f"WHERE ds={sql_quote(ds)} AND clip_id={sql_quote(clip_id)} "
        f"AND run_id={sql_quote(run_id)} LIMIT 1",
        cache=False,
    )
    return str(rows[0]["status"]) if rows else "pending"


def resolve_run_for_clip(
    clip_id: str, active_run_id: str | None, *, max_partition_scans: int = 8
) -> dict[str, Any] | None:
    """Prefer active_run_id; fall back to newest run across recent ds partitions."""
    if active_run_id:
        try:
            ds = resolve_ds_for_run(clip_id, active_run_id)
            return {
                "run_id": active_run_id,
                "ds": ds,
                "run_status": _query_run_status(clip_id, active_run_id, ds),
                "started_at": "",
                "source": "active_run_id",
            }
        except ValueError:
            pass

    settings = get_settings()
    tbl = table_name(settings, "pipeline_run")
    best: dict[str, Any] | None = None
    for i, ds in enumerate(list_ds_partitions("pipeline_run")):
        if i >= max_partition_scans:
            break
        rows = query(
            f"SELECT run_id, status, started_at FROM {tbl} "
            f"WHERE ds={sql_quote(ds)} AND clip_id={sql_quote(clip_id)}",
            cache=False,
        )
        for r in rows:
            started = str(r.get("started_at") or "")
            if best is None or started > str(best.get("started_at") or ""):
                best = {
                    "run_id": str(r["run_id"]),
                    "ds": ds,
                    "run_status": str(r.get("status") or "pending"),
                    "started_at": started,
                    "source": "latest_partition_scan",
                }
    return best


def query_pipeline_steps(run_id: str, ds: str) -> list[dict[str, Any]]:
    settings = get_settings()
    w = f"run_id={sql_quote(run_id)} AND ds={sql_quote(ds)}"
    step_rows = query(
        f"SELECT step_id, status FROM {table_name(settings, 'pipeline_step')} WHERE {w}",
        cache=False,
    )
    step_map = {
        str(r["step_id"]): normalize_pipeline_status(str(r["status"])) for r in step_rows
    }
    return [
        {
            "step_id": sid,
            "label": STEP_LABELS.get(sid, sid),
            "status": step_map.get(sid, "pending"),
        }
        for sid in PIPELINE_STEP_ORDER
    ]


def _apply_job0_infer(steps: list[dict[str, Any]], *, clip_discovered: bool) -> list[dict[str, Any]]:
    """Job0 does not write pipeline_step; infer from dim_clip or downstream success."""
    if not clip_discovered:
        return steps
    job0_pending = True
    for s in steps:
        if s["step_id"] == "job0_discover":
            job0_pending = s["status"] == "pending"
            break
    if not job0_pending:
        return steps
    later_ok = any(
        s["status"] == "success"
        for s in steps
        if s["step_id"] not in {"job0_discover"}
    )
    if later_ok or clip_discovered:
        out = []
        for s in steps:
            if s["step_id"] == "job0_discover":
                out.append({**s, "status": "success"})
            else:
                out.append(s)
        return out
    return steps


def compute_overall_status(
    steps: list[dict[str, Any]], *, run_status: str = "pending"
) -> str:
    work = [s for s in steps if s["step_id"] != "job0_discover"]
    if any(s["status"] == "failed" for s in work):
        return "failed"
    if work and all(s["status"] == "success" for s in work):
        return "completed"
    if any(s["status"] == "running" for s in work):
        return "running"
    if any(s["status"] == "success" for s in work):
        return "running"
    rs = (run_status or "").strip().lower()
    if rs in {"running", "pending"}:
        return "running"
    return "idle"


def get_bag_pipeline(oss_key: str, *, refresh: bool = False) -> dict[str, Any]:
    cache_key = oss_key.strip()
    if not refresh and cache_key in _bag_pipeline_cache:
        return _bag_pipeline_cache[cache_key]

    out: dict[str, Any] = {
        "oss_key": oss_key,
        "clip_id": None,
        "run_id": None,
        "active_run_id": None,
        "is_active_run": False,
        "ds": None,
        "run_status": None,
        "pipeline_status": "not_discovered",
        "pipeline_steps": _pending_steps(),
        "message": "Job0 discover 尚未写入 dim_clip，请运行 discover 工作流",
    }

    manifest_hit = _resolve_from_manifest(oss_key)
    clip_id: str | None = manifest_hit["clip_id"] if manifest_hit else _clip_id_for_bag(oss_key)
    if not clip_id:
        _bag_pipeline_cache[cache_key] = out
        return out

    active_run_id: str | None = None
    if manifest_hit:
        active_run_id = manifest_hit["run_id"]
        out["clip_id"] = clip_id
        out["active_run_id"] = active_run_id
        try:
            dim = get_dim_clip(clip_id)
            dim_active = str(dim.get("active_run_id") or "") or None
            if dim_active:
                out["active_run_id"] = dim_active
                active_run_id = dim_active
        except ValueError:
            pass
    else:
        dim = get_dim_clip(clip_id)
        active_run_id = str(dim.get("active_run_id") or "") or None
        out["clip_id"] = clip_id
        out["active_run_id"] = active_run_id

    run_info = resolve_run_for_clip(clip_id, active_run_id)
    if not run_info:
        out.update(
            {
                "pipeline_status": "idle",
                "pipeline_steps": _apply_job0_infer(_pending_steps(), clip_discovered=True),
                "message": "已在 dim_clip 登记，尚无 pipeline_run 记录",
            }
        )
        _bag_pipeline_cache[cache_key] = out
        return out

    run_id = str(run_info["run_id"])
    ds = str(run_info["ds"])
    run_status = str(run_info["run_status"])
    steps = _apply_job0_infer(
        query_pipeline_steps(run_id, ds), clip_discovered=True
    )
    pipeline_status = compute_overall_status(steps, run_status=run_status)

    out.update(
        {
            "run_id": run_id,
            "ds": ds,
            "run_status": run_status,
            "is_active_run": bool(active_run_id and run_id == active_run_id),
            "pipeline_status": pipeline_status,
            "pipeline_steps": steps,
            "message": None
            if pipeline_status != "idle"
            else "管线尚未开始或步骤未写入 MC",
        }
    )
    if active_run_id and run_id != active_run_id:
        out["message"] = (
            f"展示的是最新 run（{run_id[:8]}…）；当前生效 active_run_id 为 {active_run_id[:8]}…"
        )

    _bag_pipeline_cache[cache_key] = out
    return out
