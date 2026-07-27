"""Expand and filter v2 tasks for assignment batches."""

from __future__ import annotations

from typing import Any

from hmi.review.assignment_db import create_batch, get_batch, list_batches
from hmi.review.v2_tasks import build_pending_tasks


def preview_assignment_items(label_ids: list[str], queue_limit: int) -> list[dict[str, Any]]:
    label_set = set(label_ids)
    tasks = build_pending_tasks("confidence")
    filtered = [t for t in tasks if t["label_id"] in label_set]
    return filtered[:queue_limit]


def dispatch_assignment_batch(
    *,
    name: str,
    label_ids: list[str],
    queue_limit: int,
    assignee_id: str | None,
    created_by: str,
) -> dict[str, Any]:
    items = preview_assignment_items(label_ids, queue_limit)
    return create_batch(
        name=name,
        label_ids=label_ids,
        queue_limit=queue_limit,
        assignee_id=assignee_id or None,
        created_by=created_by,
        items=items,
    )


def filter_tasks_for_batch(
    tasks: list[dict[str, Any]],
    *,
    batch_id: str,
    assignee_id: str,
) -> list[dict[str, Any]]:
    from hmi.review.assignment_db import get_work_item_keys

    keys = set(get_work_item_keys(batch_id, assignee_id))
    if not keys:
        return []
    filtered = [t for t in tasks if (t["clip_id"], t["run_id"], t["label_id"]) in keys]
    key_order = {k: i for i, k in enumerate(keys)}
    filtered.sort(key=lambda t: key_order.get((t["clip_id"], t["run_id"], t["label_id"]), 9999))
    total = len(filtered)
    out: list[dict[str, Any]] = []
    for idx, task in enumerate(filtered):
        t = dict(task)
        t["position"] = {"index": idx + 1, "total": total}
        out.append(t)
    return out


def list_all_batches() -> list[dict[str, Any]]:
    return list_batches()
