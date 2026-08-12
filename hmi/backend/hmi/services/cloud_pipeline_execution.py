"""Cloud pipeline execution queue: upload OSS → DataWorks trigger → poll MC/dispatch/Dag."""

from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hmi.config import pipeline_step_label, sdk_pipeline_step_order
from hmi.data_source import LOCAL_ROOT, ensure_runtime_layout
from hmi.db import normalize_pipeline_status
from hmi.services import dataworks_trigger
from hmi.services.pipeline_status import get_bag_pipeline

logger = logging.getLogger(__name__)

_SH_TZ = ZoneInfo("Asia/Shanghai")
_LOCK = threading.Lock()
_STORE_NAME = "cloud_pipeline_jobs.json"
# Skip expensive Dag/MC refresh if this execution was refreshed recently
_EXECUTION_REFRESH_MIN_INTERVAL_SEC = 20
# Bumped on clear so in-flight list_executions won't rewrite wiped queue
_STORE_GENERATION = 0


def _utc_now_z() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _label_now() -> str:
    return datetime.now(_SH_TZ).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")


def _store_path() -> Path:
    ensure_runtime_layout()
    return LOCAL_ROOT / _STORE_NAME


def _read_all() -> list[dict[str, Any]]:
    path = _store_path()
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(raw, dict) and isinstance(raw.get("items"), list):
        return [x for x in raw["items"] if isinstance(x, dict)]
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    return []


def _write_all(items: list[dict[str, Any]]) -> None:
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": items, "updated_at": _utc_now_z()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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


def _pending_clip(bag_key: str, *, started_at: str, filename: str = "") -> dict[str, Any]:
    short = bag_key.replace("\\", "/").rstrip("/").split("/")[-2:]
    display = "/".join(short) if short else bag_key
    order = sdk_pipeline_step_order(local=False)
    steps = [
        {
            "step_id": sid,
            "label": pipeline_step_label(sid, local=False),
            "status": "pending",
            "error_message": None,
        }
        for sid in order
        if sid not in ("job0_discover", "sdk_discover")
    ]
    return {
        "clip_id": f"pending:{display}",
        "clip_dir_name": filename or display,
        "bag_oss_key": bag_key,
        "ds": "",
        "pipeline_status": "pending",
        "pipeline_created_at": started_at,
        "pipeline_updated_at": None,
        "steps": steps,
    }


def _refresh_clip(clip: dict[str, Any], *, dag_status: str | None) -> dict[str, Any]:
    bag_key = str(clip.get("bag_oss_key") or "").strip()
    if not bag_key:
        return clip
    try:
        # Use bag_pipeline TTL cache (60s); force-bypass only hurts list latency
        info = get_bag_pipeline(bag_key, refresh=False)
    except Exception as exc:
        logger.warning("get_bag_pipeline failed for %s: %s", bag_key[:48], exc)
        info = {}

    clip_id = str(info.get("clip_id") or "").strip()
    run_id = str(info.get("run_id") or info.get("active_run_id") or "").strip()
    ds = str(info.get("ds") or "").strip()
    pipe = str(info.get("pipeline_status") or "").strip().lower()
    steps_raw = info.get("pipeline_steps")
    steps: list[dict[str, Any]] = []
    if isinstance(steps_raw, list) and steps_raw:
        for s in steps_raw:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("step_id") or "")
            if sid in ("job0_discover", "sdk_discover"):
                continue
            steps.append(
                {
                    "step_id": sid,
                    "label": str(s.get("label") or pipeline_step_label(sid, local=False)),
                    "status": normalize_pipeline_status(str(s.get("status") or "pending")),
                    "error_message": s.get("error_message"),
                }
            )

    out = dict(clip)
    if clip_id:
        out["clip_id"] = clip_id
        out["clip_dir_name"] = clip_id[:48]
    if run_id:
        out["mc_run_id"] = run_id
    if ds:
        out["ds"] = ds
    if steps:
        out["steps"] = steps

    # Prefer MC/dispatch overall status; fall back to Dag
    if pipe in {"completed", "success"}:
        out["pipeline_status"] = "completed"
    elif pipe == "failed":
        out["pipeline_status"] = "failed"
    elif pipe == "running":
        out["pipeline_status"] = "running"
    elif pipe == "pending":
        out["pipeline_status"] = "pending"
    elif dag_status:
        out["pipeline_status"] = normalize_pipeline_status(dag_status)
    else:
        out["pipeline_status"] = "pending"

    if dag_status == "failed" and not clip_id:
        out["pipeline_status"] = "failed"
        for step in out.get("steps") or []:
            if step.get("status") == "pending":
                step["status"] = "failed"
                step["error_message"] = "DataWorks Dag FAILURE"
                break

    out["pipeline_updated_at"] = _utc_now_z()
    return out


def _execution_recently_refreshed(ex: dict[str, Any]) -> bool:
    raw = str(ex.get("_refreshed_at") or "").strip()
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
    return age < _EXECUTION_REFRESH_MIN_INTERVAL_SEC


def _refresh_execution(ex: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    if not force and _execution_recently_refreshed(ex):
        return ex

    dag_id = str(ex.get("dag_id") or "").strip()
    dag_status: str | None = None
    if dag_id and not dataworks_trigger.is_throttle_circuit_open():
        try:
            dag_info = dataworks_trigger.get_dag_status(dag_id)
            dag_status = dag_info.get("pipeline_status")
            ex = dict(ex)
            ex["dag_raw_status"] = dag_info.get("raw_status")
        except dataworks_trigger.DataWorksConfigError:
            pass
        except Exception as exc:
            logger.warning("dag status refresh failed: %s", exc)
    elif dag_id and dataworks_trigger.is_throttle_circuit_open():
        # Keep last known dag_raw_status; still refresh MC/OSS side via clips
        pass

    clips = [_refresh_clip(c, dag_status=dag_status) for c in (ex.get("clips") or []) if isinstance(c, dict)]
    statuses = [str(c.get("pipeline_status") or "pending") for c in clips]
    # If all clips still pending but Dag completed, keep completed only when MC says so
    agg = _aggregate_status(statuses)
    if dag_status == "failed" and agg in {"pending", "running"}:
        agg = "failed"
    if dag_status == "running" and agg == "pending":
        agg = "running"
    has_real_clip = any(
        (cid := str(c.get("clip_id") or "")) and not cid.startswith("pending:") for c in clips
    )
    if dag_status == "completed" and agg == "pending" and not has_real_clip:
        # Dag success but MC/dispatch not yet visible — keep polling
        agg = "running"

    out = dict(ex)
    out["clips"] = clips
    out["clip_count"] = len(clips)
    out["pipeline_status"] = agg
    out["_refreshed_at"] = _utc_now_z()
    return out


def known_bag_oss_keys() -> set[str]:
    """All bag keys already recorded in cloud execution history (any status)."""
    keys: set[str] = set()
    with _LOCK:
        for ex in _read_all():
            for k in ex.get("bag_oss_keys") or []:
                kk = str(k).strip().lstrip("/")
                if kk:
                    keys.add(kk)
            for c in ex.get("clips") or []:
                if not isinstance(c, dict):
                    continue
                kk = str(c.get("bag_oss_key") or "").strip().lstrip("/")
                if kk:
                    keys.add(kk)
    return keys


def record_triggered_bags(
    bag_oss_keys: list[str],
    *,
    dag_id: str | None,
    label: str | None = None,
    source: str = "poller",
) -> dict[str, Any]:
    """Persist a cloud execution row after OSS upload (optional DataWorks trigger)."""
    keys = [k.strip().lstrip("/") for k in bag_oss_keys if k and str(k).strip()]
    if not keys:
        raise ValueError("bag_oss_keys required")
    started_at = _utc_now_z()
    execution_id = str(uuid.uuid4())
    ds = datetime.now(timezone.utc).strftime("%Y%m%d")
    clip_stubs = [
        _pending_clip(k, started_at=started_at, filename=k.rsplit("/", 1)[-1]) for k in keys
    ]
    record = {
        "run_id": execution_id,
        "label": label or f"{_label_now()} ({source})",
        "started_at": started_at,
        "created_at": started_at,
        "ds": ds,
        "dag_id": str(dag_id) if dag_id else None,
        "bag_oss_keys": keys,
        "pipeline_status": "pending",
        "clip_count": len(clip_stubs),
        "clips": clip_stubs,
        "source": source,
        "await_schedule": dag_id is None,
    }
    with _LOCK:
        items = _read_all()
        items.insert(0, record)
        _write_all(items)
    return record


def enqueue_rosbags_cloud(
    files: list[tuple[str, bytes]],
    *,
    trigger: bool = True,
) -> dict[str, Any]:
    """Upload bags to OSS; optionally trigger DataWorks OpenAPI.

    ``trigger=False``: OSS only — for periodic DataWorks schedules that discover
    new bags under ``rosbags/`` without HMI calling CreateDagTest.
    """
    if not files:
        raise ValueError("at least one .bag file required")

    if trigger:
        # Fail fast on missing DW config before uploading large bags
        dataworks_trigger.require_dataworks_config()

    from hmi.oss_signer import upload_rosbag_bytes

    bag_keys: list[str] = []
    for filename, data in files:
        if not filename.lower().endswith(".bag"):
            raise ValueError(f"only .bag files are accepted: {filename}")
        oss_key = upload_rosbag_bytes(filename, data)
        bag_keys.append(oss_key)

    ds = datetime.now(timezone.utc).strftime("%Y%m%d")
    dag_id: str | None = None
    flow_name: str | None = None
    source = "api"
    label = _label_now()

    if trigger:
        trigger_result = dataworks_trigger.trigger_sdk_pipeline(bag_keys, ds=ds)
        dag_id = str(trigger_result["dag_id"])
        flow_name = trigger_result.get("flow_name")
        source = "api"
    else:
        source = "upload_only"
        label = f"{_label_now()}（仅上传）"

    record = record_triggered_bags(
        bag_keys,
        dag_id=dag_id,
        label=label,
        source=source,
    )
    with _LOCK:
        items = _read_all()
        if items and items[0].get("run_id") == record["run_id"]:
            if flow_name is not None:
                items[0]["flow_name"] = flow_name
            items[0]["ds"] = ds
            items[0]["await_schedule"] = not trigger
            _write_all(items)
            record = items[0]

    return {
        "run_id": record["run_id"],
        "label": record["label"],
        "started_at": record["started_at"],
        "ds": ds,
        "dag_id": dag_id,
        "trigger": trigger,
        "await_schedule": not trigger,
        "clips": [
            {
                "clip_id": c["clip_id"],
                "oss_key": c["bag_oss_key"],
                "bag_oss_key": c["bag_oss_key"],
                "size_bytes": None,
            }
            for c in record.get("clips") or []
        ],
    }


def clear_all_executions() -> int:
    """Wipe cloud execution queue; return previous item count.

    Writes an empty store (instead of only unlinking) and bumps generation so an
    in-flight ``list_executions`` refresh cannot resurrect old rows.
    """
    global _STORE_GENERATION
    with _LOCK:
        items = _read_all()
        _STORE_GENERATION += 1
        _write_all([])
        return len(items)


def list_executions(*, page: int = 1, page_size: int = 10, refresh: bool = False) -> dict[str, Any]:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    terminal = {"completed", "failed", "cancelled", "success"}

    with _LOCK:
        gen = _STORE_GENERATION
        items = _read_all()
        refreshed: list[dict[str, Any]] = []
        dirty = False
        for ex in items:
            status = str(ex.get("pipeline_status") or "").strip().lower()
            # Skip expensive Dag/MC refresh for finished rows — list is polled often.
            if status in terminal:
                refreshed.append(ex)
                continue
            try:
                new_ex = _refresh_execution(ex, force=refresh)
            except Exception:
                logger.exception("cloud execution refresh failed")
                new_ex = ex
            if new_ex != ex:
                dirty = True
            refreshed.append(new_ex)
        # Don't resurrect a queue that was cleared while we were refreshing
        if gen != _STORE_GENERATION:
            items = _read_all()
        else:
            if dirty:
                _write_all(refreshed)
            items = refreshed

    total = len(items)
    offset = (page - 1) * page_size
    page_items = items[offset : offset + page_size]
    # Shape for API (strip internal-only noise optional)
    out_items = []
    for ex in page_items:
        out_items.append(
            {
                "run_id": ex.get("run_id"),
                "label": ex.get("label") or "",
                "started_at": ex.get("started_at") or "",
                "created_at": ex.get("created_at") or "",
                "pipeline_status": ex.get("pipeline_status") or "pending",
                "clip_count": int(ex.get("clip_count") or len(ex.get("clips") or [])),
                "clips": [
                    {
                        "clip_id": c.get("clip_id"),
                        "clip_dir_name": c.get("clip_dir_name") or c.get("clip_id"),
                        "ds": c.get("ds") or "",
                        "pipeline_status": c.get("pipeline_status") or "pending",
                        "pipeline_created_at": c.get("pipeline_created_at") or ex.get("started_at") or "",
                        "pipeline_updated_at": c.get("pipeline_updated_at"),
                        "steps": c.get("steps") or [],
                        "bag_oss_key": c.get("bag_oss_key"),
                        "mc_run_id": c.get("mc_run_id"),
                    }
                    for c in (ex.get("clips") or [])
                    if isinstance(c, dict)
                ],
                "dag_id": ex.get("dag_id"),
            }
        )

    return {"items": out_items, "total": total, "page": page, "page_size": page_size}
