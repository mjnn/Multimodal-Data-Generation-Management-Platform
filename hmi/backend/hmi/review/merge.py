"""Merge per-label field reviews into clip_label_review.labels_json."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hmi.clip_facts import get_clip_label_row, get_clip_label_view, resolve_clip_labels_for_enqueue
from hmi.labels_util import labels_to_clip_dict
from hmi.local.clip_context import resolve_ds_for_run
from hmi.review.field_review_db import (
    FIELD_REVIEW_ACTIONS,
    list_field_review_label_ids,
    upsert_field_review,
)
from hmi.review_db import get_or_create_review, get_review, update_review
from hmi.taxonomy_db import get_published_version


def _flatten_label_id_map(raw: Any) -> dict[str, Any]:
    if not raw or not isinstance(raw, dict):
        return {}
    flat = labels_to_clip_dict(raw)
    if flat:
        return flat
    return {str(k): v for k, v in raw.items() if str(k) not in ("values",)}


def get_ai_label_ids(clip_id: str, run_id: str) -> list[str]:
    """Label keys from AI clip label view (rollup scope)."""
    try:
        ds = resolve_ds_for_run(clip_id, run_id)
    except ValueError:
        return []
    flat: dict[str, Any] = {}
    view = get_clip_label_view(clip_id, run_id, ds=ds)
    if view.get("clip_label_ready"):
        flat = _flatten_label_id_map(view.get("labels_json"))
        if not flat:
            row = get_clip_label_row(clip_id, run_id, ds=ds)
            if row:
                flat = _flatten_label_id_map(row.get("labels_json"))
    if not flat:
        review = get_review(clip_id, run_id)
        if review:
            flat = _flatten_label_id_map(review.get("labels_json"))
    return sorted(str(k) for k in flat.keys())


def get_ai_label_value(clip_id: str, run_id: str, label_id: str) -> Any:
    try:
        ds = resolve_ds_for_run(clip_id, run_id)
    except ValueError:
        return None
    view = get_clip_label_view(clip_id, run_id, ds=ds)
    labels = view.get("labels_json") or {}
    if not isinstance(labels, dict):
        return None
    return labels.get(label_id)


def merge_label_into_clip_dict(
    labels_json: dict[str, Any],
    label_id: str,
    value: Any,
) -> dict[str, Any]:
    merged = deepcopy(labels_json)
    merged[label_id] = value
    return merged


def all_ai_labels_field_reviewed(clip_id: str, run_id: str) -> bool:
    ai_ids = get_ai_label_ids(clip_id, run_id)
    if not ai_ids:
        return False
    reviewed = set(list_field_review_label_ids(clip_id, run_id))
    return all(label_id in reviewed for label_id in ai_ids)


def resolve_field_review_value(
    *,
    action: str,
    ai_value: Any,
    value: Any | None = None,
) -> tuple[Any, bool]:
    """Return (stored_value, human_doubtful)."""
    if action not in FIELD_REVIEW_ACTIONS:
        raise ValueError(f"invalid action: {action}")
    if action == "confirm":
        return ai_value, False
    if action == "uncertain":
        return None, True
    if action == "correct":
        return value, False
    raise ValueError(f"unsupported action: {action}")


def ensure_clip_review_for_field_merge(clip_id: str, run_id: str) -> dict[str, Any]:
    """Ensure clip_label_review exists before merging field reviews."""
    existing = get_review(clip_id, run_id)
    if existing:
        return existing

    payload = resolve_clip_labels_for_enqueue(clip_id, run_id)
    published = get_published_version()
    taxonomy_version_id = payload.get("taxonomy_version_id") or (
        published["id"] if published else None
    )
    review, _created = get_or_create_review(
        clip_id,
        run_id,
        labels_json=payload["labels_json"],
        taxonomy_version_id=taxonomy_version_id,
        review_status="pending_review",
        ai_source_summary_json=payload.get("ai_source_summary_json"),
    )
    return review


def apply_field_review(
    *,
    clip_id: str,
    run_id: str,
    label_id: str,
    action: str,
    reviewer_id: str,
    value: Any | None = None,
    ai_value: Any | None = None,
    taxonomy_version_id: str | None = None,
    expected_clip_updated_at: str | None = None,
) -> dict[str, Any]:
    """
    Upsert field review, merge into clip_label_review.labels_json, rollup status.

    Returns field_review, clip_review, rolled_up_to_reviewed.
    """
    clip_id = clip_id.strip()
    run_id = run_id.strip()
    label_id = label_id.strip()
    if not clip_id or not run_id or not label_id:
        raise ValueError("clip_id, run_id, and label_id required")

    if ai_value is None:
        ai_value = get_ai_label_value(clip_id, run_id, label_id)

    stored_value, human_doubtful = resolve_field_review_value(
        action=action,
        ai_value=ai_value,
        value=value,
    )

    if taxonomy_version_id is None:
        published = get_published_version()
        taxonomy_version_id = published["id"] if published else None

    clip_review = ensure_clip_review_for_field_merge(clip_id, run_id)
    if expected_clip_updated_at and clip_review["updated_at"] != expected_clip_updated_at:
        raise ValueError("review updated_at conflict")

    field_review = upsert_field_review(
        clip_id,
        run_id,
        label_id,
        action=action,
        value=stored_value,
        human_doubtful=human_doubtful,
        ai_value=ai_value,
        taxonomy_version_id=taxonomy_version_id,
        reviewer_id=reviewer_id,
    )

    labels_json = clip_review.get("labels_json") or {}
    if not isinstance(labels_json, dict):
        labels_json = {}
    merged_labels = merge_label_into_clip_dict(labels_json, label_id, stored_value)

    rolled_up = all_ai_labels_field_reviewed(clip_id, run_id)
    new_status = "reviewed" if rolled_up else "pending_review"

    clip_review = update_review(
        clip_id,
        run_id,
        labels_json=merged_labels,
        review_status=new_status,
        reviewer_id=reviewer_id if rolled_up else clip_review.get("reviewer_id"),
        expected_updated_at=clip_review["updated_at"],
    )

    return {
        "field_review": field_review,
        "clip_review": clip_review,
        "rolled_up_to_reviewed": rolled_up,
    }
