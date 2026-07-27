"""Per-clip review progress for overview and dataset eligibility hints."""

from __future__ import annotations

from typing import Any

from hmi.app_db import db_conn
from hmi.clip_facts import get_clip_label_view
from hmi.local.clip_context import resolve_ds_for_run
from hmi.review.merge import all_ai_labels_field_reviewed, get_ai_label_ids
from hmi.review_db import get_review


def get_clip_review_summary(clip_id: str, run_id: str) -> dict[str, Any]:
    """Label-level review stats for one clip run."""
    label_total = 0
    dispute_count = 0
    try:
        ds = resolve_ds_for_run(clip_id, run_id)
        view = get_clip_label_view(clip_id, run_id, ds=ds)
        dispute_count = int(view.get("dispute_count") or 0)
    except ValueError:
        pass

    ai_ids = get_ai_label_ids(clip_id, run_id)
    label_total = len(ai_ids)

    from hmi.review.field_review_db import count_field_reviews

    field_reviewed = count_field_reviews(clip_id, run_id)
    review = get_review(clip_id, run_id)
    review_status = review.get("review_status") if review else None

    complete = bool(ai_ids) and all_ai_labels_field_reviewed(clip_id, run_id)
    if review_status == "reviewed" and label_total > 0:
        complete = True
        field_reviewed = max(field_reviewed, label_total)

    progress_pct = round(100.0 * field_reviewed / label_total, 1) if label_total > 0 else 0.0
    if complete and label_total > 0:
        progress_pct = 100.0

    dataset_ready = label_total > 0 and complete

    return {
        "label_total": label_total,
        "dispute_count": dispute_count,
        "field_reviewed_count": field_reviewed,
        "review_progress_pct": progress_pct,
        "review_complete": complete,
        "dataset_ready": dataset_ready,
        "review_status": review_status,
    }


def _batch_field_review_counts() -> dict[tuple[str, str], int]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT clip_id, run_id, COUNT(*) AS cnt
            FROM clip_label_field_review
            GROUP BY clip_id, run_id
            """
        ).fetchall()
    return {(str(r["clip_id"]), str(r["run_id"])): int(r["cnt"]) for r in rows}


def _batch_review_statuses() -> dict[tuple[str, str], str]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT clip_id, run_id, review_status FROM clip_label_review"
        ).fetchall()
    return {(str(r["clip_id"]), str(r["run_id"])): str(r["review_status"]) for r in rows}


def batch_clip_review_summaries(
    clip_runs: list[tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """Batch summaries keyed by clip_id (uses active run_id per entry)."""
    if not clip_runs:
        return {}

    field_counts = _batch_field_review_counts()
    review_statuses = _batch_review_statuses()
    out: dict[str, dict[str, Any]] = {}

    for clip_id, run_id in clip_runs:
        label_total = 0
        dispute_count = 0
        try:
            ds = resolve_ds_for_run(clip_id, run_id)
            view = get_clip_label_view(clip_id, run_id, ds=ds)
            dispute_count = int(view.get("dispute_count") or 0)
        except ValueError:
            pass

        ai_ids = get_ai_label_ids(clip_id, run_id)
        label_total = len(ai_ids)
        field_reviewed = field_counts.get((clip_id, run_id), 0)
        review_status = review_statuses.get((clip_id, run_id))

        complete = label_total > 0 and field_reviewed >= label_total
        if review_status == "reviewed" and label_total > 0:
            complete = True
            field_reviewed = max(field_reviewed, label_total)

        progress_pct = round(100.0 * field_reviewed / label_total, 1) if label_total > 0 else 0.0
        if complete and label_total > 0:
            progress_pct = 100.0

        out[clip_id] = {
            "label_total": label_total,
            "dispute_count": dispute_count,
            "field_reviewed_count": field_reviewed,
            "review_progress_pct": progress_pct,
            "review_complete": complete,
            "dataset_ready": label_total > 0 and complete,
            "review_status": review_status,
        }
    return out
