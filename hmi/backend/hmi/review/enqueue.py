"""Enqueue clips into clip_label_review from clip-level or legacy frame labels."""

from __future__ import annotations

from typing import Any

from hmi.app_db import db_conn
from hmi.clip_facts import (
    is_clip_label_ready,
    list_clip_label_candidates,
    resolve_clip_labels_for_enqueue,
)
from hmi.local.clip_context import get_dim_clip
from hmi.review_db import get_or_create_review, get_review
from hmi.taxonomy_db import get_published_version


def list_enqueue_candidates(*, require_job3: bool = True) -> list[dict[str, str]]:
    candidates = list_clip_label_candidates()
    out: list[dict[str, str]] = []
    with db_conn() as conn:
        for item in candidates:
            clip_id = item["clip_id"]
            run_id = item["run_id"]
            exists = conn.execute(
                "SELECT 1 FROM clip_label_review WHERE clip_id=? AND run_id=?",
                (clip_id, run_id),
            ).fetchone()
            if exists:
                continue
            if require_job3 and not is_clip_label_ready(clip_id, run_id):
                continue
            out.append({"clip_id": clip_id, "run_id": run_id})
    return out


def enqueue_clip(
    clip_id: str,
    run_id: str | None = None,
    *,
    require_job3: bool = True,
) -> dict[str, Any]:
    clip_id = clip_id.strip()
    resolved_run = (run_id or "").strip()
    if not resolved_run:
        dim = get_dim_clip(clip_id)
        resolved_run = str(dim.get("active_run_id") or "").strip()
    if not resolved_run:
        raise ValueError(f"no run_id for clip {clip_id}")

    if require_job3 and not is_clip_label_ready(clip_id, resolved_run):
        raise ValueError(f"clip labels not ready for {clip_id}/{resolved_run}")

    existing = get_review(clip_id, resolved_run)
    if existing:
        return {"status": "skipped", "reason": "already_exists", "review": existing}

    payload = resolve_clip_labels_for_enqueue(clip_id, resolved_run)
    published = get_published_version()
    taxonomy_version_id = payload.get("taxonomy_version_id") or (
        published["id"] if published else None
    )

    review, created = get_or_create_review(
        clip_id,
        resolved_run,
        labels_json=payload["labels_json"],
        taxonomy_version_id=taxonomy_version_id,
        review_status="pending_review",
        ai_source_summary_json=payload["ai_source_summary_json"],
    )
    return {
        "status": "created" if created else "skipped",
        "reason": None if created else "already_exists",
        "review": review,
        "aggregation": payload["aggregation"],
    }


def enqueue_clips(
    clip_ids: list[str] | None = None,
    *,
    scan_unqueued: bool = False,
    require_job3: bool = True,
) -> list[dict[str, Any]]:
    targets: list[tuple[str, str | None]] = []
    if scan_unqueued:
        for item in list_enqueue_candidates(require_job3=require_job3):
            targets.append((item["clip_id"], item["run_id"]))
    if clip_ids:
        for clip_id in clip_ids:
            targets.append((clip_id.strip(), None))

    seen: set[tuple[str, str | None]] = set()
    results: list[dict[str, Any]] = []
    for clip_id, run_id in targets:
        key = (clip_id, run_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            results.append(
                enqueue_clip(clip_id, run_id, require_job3=require_job3)
            )
        except ValueError as exc:
            results.append(
                {
                    "status": "error",
                    "clip_id": clip_id,
                    "run_id": run_id,
                    "error": str(exc),
                }
            )
    return results
