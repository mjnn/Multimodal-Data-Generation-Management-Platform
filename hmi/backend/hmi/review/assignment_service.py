"""Expand and filter v2 tasks for assignment batches."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hmi.review.assignment_db import create_batch, get_batch, list_batch_assignee_summaries, list_batches
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
    batch_kind = "assigned" if assignee_id else "public_pool"
    return create_batch(
        name=name,
        label_ids=label_ids,
        queue_limit=queue_limit,
        assignee_id=assignee_id or None,
        created_by=created_by,
        items=items,
        batch_kind=batch_kind,
    )


def claim_low_confidence_batch(
    *,
    assignee_id: str,
    limit: int,
    created_by: str,
) -> dict[str, Any]:
    tasks = build_pending_tasks("confidence")[:limit]
    if not tasks:
        raise ValueError("当前没有可领取的低置信度校核条目")
    label_ids = sorted({str(t["label_id"]) for t in tasks})
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    name = f"低置信度校核 {stamp}"
    return create_batch(
        name=name,
        label_ids=label_ids,
        queue_limit=len(tasks),
        assignee_id=assignee_id,
        created_by=created_by,
        items=tasks,
        batch_kind="low_confidence",
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


def _enrich_assignee_summaries(batch: dict[str, Any]) -> dict[str, Any]:
    from hmi.app_db import get_user_by_id

    summaries = list_batch_assignee_summaries(batch["id"])
    enriched: list[dict[str, Any]] = []
    for row in summaries:
        user = get_user_by_id(str(row["assignee_id"]))
        enriched.append(
            {
                **row,
                "username": user["username"] if user else None,
                "display_name": user["display_name"] if user else str(row["assignee_id"])[:8],
            }
        )
    batch["assignee_summaries"] = enriched
    return batch


def list_all_batches() -> list[dict[str, Any]]:
    batches = list_batches()
    for batch in batches:
        _enrich_assignee_summaries(batch)
    return batches
