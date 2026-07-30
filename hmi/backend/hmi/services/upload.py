"""In-memory upload tasks + pipeline progress from MC / local SQLite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from hmi.data_source import is_local_mode
from hmi.services.pipeline_status import get_bag_pipeline

_tasks: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_upload_task(filename: str, size_bytes: int, oss_key: str) -> dict[str, Any]:
    task_id = f"up-{uuid.uuid4().hex[:12]}"
    task = {
        "task_id": task_id,
        "filename": filename,
        "size_bytes": size_bytes,
        "progress": 100,
        "status": "success",
        "oss_key": oss_key,
        "clip_id": None,
        "run_id": None,
        "pipeline_status": "idle",
        "pipeline_steps": None,
        "created_at": _utc_now(),
    }
    _tasks[task_id] = task
    return task


def create_local_upload_task(
    filename: str,
    size_bytes: int,
    *,
    oss_key: str,
    bag_oss_key: str,
    clip_id: str,
    run_id: str,
) -> dict[str, Any]:
    task = create_upload_task(filename, size_bytes, oss_key)
    task["clip_id"] = clip_id
    task["run_id"] = run_id
    task["pipeline_status"] = "pending"
    task["bag_oss_key"] = bag_oss_key
    _refresh_pipeline(task)
    return task


def list_upload_tasks() -> list[dict[str, Any]]:
    for task in _tasks.values():
        _refresh_pipeline(task)
    return sorted(_tasks.values(), key=lambda t: t["created_at"], reverse=True)


def clear_upload_tasks() -> int:
    n = len(_tasks)
    _tasks.clear()
    return n


def _refresh_pipeline(task: dict[str, Any]) -> None:
    if is_local_mode():
        bag_key = str(task.get("bag_oss_key") or "")
        if not bag_key and task.get("oss_key"):
            bag_key = f"local://{task['oss_key']}"
        if not bag_key:
            return
        info = get_bag_pipeline(bag_key, refresh=True)
    else:
        oss_key = task.get("oss_key")
        if not oss_key:
            return
        info = get_bag_pipeline(str(oss_key), refresh=True)
    task["clip_id"] = info.get("clip_id")
    task["run_id"] = info.get("run_id")
    task["pipeline_status"] = info.get("pipeline_status")
    task["pipeline_steps"] = info.get("pipeline_steps")
