"""Expand and filter v2 tasks for assignment batches."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hmi.review.assignment_db import (
    BBOX_SENTINEL_LABEL_ID,
    create_batch,
    get_batch,
    list_batch_assignee_summaries,
    list_batches,
    normalize_review_targets,
)
from hmi.review.v2_tasks import build_low_confidence_claim_tasks, build_pending_tasks


def preview_assignment_items(
    label_ids: list[str],
    queue_limit: int,
    *,
    review_targets: list[str] | None = None,
) -> list[dict[str, Any]]:
    targets = normalize_review_targets(review_targets)
    if targets == ["bboxes"]:
        return preview_bbox_only_items(queue_limit)
    label_set = set(label_ids)
    tasks = build_pending_tasks("confidence")
    filtered = [t for t in tasks if t["label_id"] in label_set]
    return filtered[:queue_limit]


def preview_bbox_only_items(queue_limit: int) -> list[dict[str, Any]]:
    """One work item per clip/run for bbox frame review."""
    tasks = build_pending_tasks("confidence")
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for t in tasks:
        key = (str(t["clip_id"]), str(t["run_id"]))
        if key in seen:
            continue
        seen.add(key)
        item = dict(t)
        item["label_id"] = BBOX_SENTINEL_LABEL_ID
        item["label_name"] = "识别框"
        item["dtype"] = "bbox"
        out.append(item)
        if len(out) >= queue_limit:
            break
    return out


def dispatch_assignment_batch(
    *,
    name: str,
    label_ids: list[str],
    queue_limit: int,
    assignee_id: str | None,
    created_by: str,
    review_targets: list[str] | None = None,
) -> dict[str, Any]:
    targets = normalize_review_targets(review_targets)
    items = preview_assignment_items(label_ids, queue_limit, review_targets=targets)
    batch_kind = "assigned" if assignee_id else "public_pool"
    return create_batch(
        name=name,
        label_ids=label_ids if "labels" in targets else [],
        queue_limit=queue_limit,
        assignee_id=assignee_id or None,
        created_by=created_by,
        items=items,
        batch_kind=batch_kind,
        review_targets=targets,
    )


def claim_low_confidence_batch(
    *,
    assignee_id: str,
    limit: int,
    created_by: str,
    review_targets: list[str] | None = None,
) -> dict[str, Any]:
    targets = normalize_review_targets(review_targets)
    if targets == ["bboxes"]:
        tasks = preview_bbox_only_items(limit)
        label_ids: list[str] = []
    else:
        tasks = build_low_confidence_claim_tasks(limit)
        if "bboxes" in targets and "labels" not in targets:
            # already handled
            pass
        label_ids = sorted({str(t["label_id"]) for t in tasks})
    if not tasks:
        raise ValueError("当前没有可领取的空值或低置信度校核条目")
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
        review_targets=targets,
    )


def filter_tasks_for_batch(
    tasks: list[dict[str, Any]],
    *,
    batch_id: str,
    assignee_id: str,
) -> list[dict[str, Any]]:
    from hmi.review.assignment_db import get_work_item_keys
    from hmi.review.v2_tasks import _build_clip_card

    keys = set(get_work_item_keys(batch_id, assignee_id))
    if not keys:
        return []
    by_key = {(t["clip_id"], t["run_id"], t["label_id"]): t for t in tasks}
    key_order = {k: i for i, k in enumerate(keys)}
    filtered: list[dict[str, Any]] = []
    for clip_id, run_id, label_id in keys:
        t = by_key.get((clip_id, run_id, label_id))
        if t is None and label_id == BBOX_SENTINEL_LABEL_ID:
            # Synthesize a clip-level bbox review task
            from hmi.clip_facts import get_clip_label_view

            try:
                view = get_clip_label_view(clip_id, run_id)
            except Exception:
                view = {"clip_id": clip_id, "run_id": run_id, "labels_json": {}}
            if not isinstance(view, dict):
                view = {"clip_id": clip_id, "run_id": run_id, "labels_json": {}}
            try:
                clip_card = _build_clip_card(clip_id, run_id, view)
            except Exception:
                clip_card = {
                    "clip_id": clip_id,
                    "run_id": run_id,
                    "has_bbox_preview": False,
                }
            t = {
                "clip_id": clip_id,
                "run_id": run_id,
                "label_id": BBOX_SENTINEL_LABEL_ID,
                "label_name": "识别框",
                "dtype": "bbox",
                "ai_value": None,
                "ai_confidence": None,
                "clip_card": clip_card,
            }
        if t is None:
            continue
        filtered.append(dict(t))
    filtered.sort(key=lambda t: key_order.get((t["clip_id"], t["run_id"], t["label_id"]), 9999))
    total = len(filtered)
    out: list[dict[str, Any]] = []
    for idx, task in enumerate(filtered):
        t = dict(task)
        t["queue_index"] = idx
        t["queue_total"] = total
        out.append(t)
    return out


def list_all_batches() -> list[dict[str, Any]]:
    batches = list_batches()
    for b in batches:
        b["assignee_summaries"] = list_batch_assignee_summaries(b["id"])
    return batches
