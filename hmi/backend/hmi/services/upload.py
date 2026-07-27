"""In-memory upload tasks + pipeline progress from MC."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

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


def list_upload_tasks() -> list[dict[str, Any]]:
    for task in _tasks.values():
        _refresh_pipeline(task)
    return sorted(_tasks.values(), key=lambda t: t["created_at"], reverse=True)


def _refresh_pipeline(task: dict[str, Any]) -> None:
    oss_key = task.get("oss_key")
    if not oss_key:
        return
    info = get_bag_pipeline(str(oss_key), refresh=True)
    task["clip_id"] = info.get("clip_id")
    task["run_id"] = info.get("run_id")
    task["pipeline_status"] = info.get("pipeline_status")
    task["pipeline_steps"] = info.get("pipeline_steps")
