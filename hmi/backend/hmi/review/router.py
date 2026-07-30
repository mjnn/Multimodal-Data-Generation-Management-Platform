"""Clip label review REST API."""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hmi.auth.deps import get_current_user, require_admin, require_reviewer
from hmi.audit import append_audit_log
from hmi.labels_util import labels_preview, match_label_filters, parse_labels_json
from hmi.review.candidates import list_review_task_candidates, parse_label_filters_param
from hmi.review.enqueue import enqueue_clip, enqueue_clips
from hmi.review.field_review_db import delete_field_reviews
from hmi.review.oss_export import export_review_to_oss
from hmi.review_db import (
    REVIEW_STATUSES,
    count_reviews,
    get_review,
    list_reviews,
    list_reviews_by_clip,
    update_review,
)

router = APIRouter(prefix="/api/review", tags=["review"])


class SaveReviewBody(BaseModel):
    labels_json: dict[str, Any] = Field(default_factory=dict)
    review_status: str
    updated_at: str = Field(min_length=1)
    run_id: str | None = None


class ReopenReviewBody(BaseModel):
    run_id: str | None = None


class EnqueueReviewBody(BaseModel):
    clip_ids: list[str] | None = None
    scan_unqueued: bool = False
    require_job3: bool = True


class EnsureReviewBody(BaseModel):
    run_id: str | None = None


def _enrich_review_item(item: dict[str, Any]) -> dict[str, Any]:
    from hmi.ai_label_hints import load_ai_label_hints_local
    from hmi.review.field_review_db import list_field_review_label_ids

    labels = item.get("labels_json") or {}
    preview = labels_preview(parse_labels_json(labels)) if labels else ""
    clip_id = str(item.get("clip_id") or "")
    run_id = str(item.get("run_id") or "")
    hints = load_ai_label_hints_local(clip_id, run_id) if clip_id and run_id else {}
    field_reviewed = (
        list_field_review_label_ids(clip_id, run_id) if clip_id and run_id else []
    )
    return {
        **item,
        "label_preview": preview,
        "ai_label_hints": hints,
        "field_reviewed_label_ids": field_reviewed,
    }


def _filter_reviews_by_labels(
    items: list[dict[str, Any]],
    label_filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not label_filters:
        return items
    return [r for r in items if match_label_filters(r.get("labels_json"), label_filters)]


def _review_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "conflict" in message:
        return HTTPException(
            status_code=409,
            detail={"code": "409_CONFLICT", "message": message},
        )
    if "not found" in message:
        return HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": message},
        )
    return HTTPException(
        status_code=422,
        detail={"code": "422_VALIDATION", "message": message},
    )


def _resolve_run_id(clip_id: str, run_id: str | None) -> str:
    if run_id and run_id.strip():
        return run_id.strip()
    try:
        from hmi.local.clip_context import get_dim_clip

        dim = get_dim_clip(clip_id.strip())
        active = str(dim.get("active_run_id") or "").strip()
        if active:
            return active
    except ValueError:
        pass
    rows = list_reviews_by_clip(clip_id)
    if len(rows) == 1:
        return str(rows[0]["run_id"])
    if not rows:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": "run_id required"},
        )
    raise HTTPException(
        status_code=422,
        detail={
            "code": "422_VALIDATION",
            "message": "multiple reviews for clip; specify run_id",
        },
    )


@router.get("/queue")
def api_review_queue(
    status: str | None = Query(default=None, alias="status"),
    label_filters: str | None = Query(default=None, description="JSON object label_id -> value"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    review_status = status.strip() if status else None
    if review_status and review_status not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": f"invalid status: {review_status}"},
        )
    try:
        parsed_filters = parse_label_filters_param(label_filters)
        if parsed_filters:
            all_items = list_reviews(review_status=review_status, limit=10_000, offset=0)
            filtered = _filter_reviews_by_labels(all_items, parsed_filters)
            total = len(filtered)
            items = [_enrich_review_item(r) for r in filtered[offset : offset + limit]]
        else:
            items = [_enrich_review_item(r) for r in list_reviews(review_status=review_status, limit=limit, offset=offset)]
            total = count_reviews(review_status=review_status)
    except ValueError as exc:
        raise _review_error(exc) from exc
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/candidates")
def api_review_candidates(
    label_filters: str = Query(..., min_length=2, description="JSON object label_id -> value"),
    review_scope: str = Query(default="unreviewed"),
    disputes_only: bool = Query(default=False),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        parsed_filters = parse_label_filters_param(label_filters)
        if not parsed_filters:
            raise ValueError("label_filters required")
        items, total = list_review_task_candidates(
            label_filters=parsed_filters,
            review_scope=review_scope.strip() or "all",
            disputes_only=disputes_only,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise _review_error(exc) from exc
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/clips/{clip_id}/ensure")
def api_review_ensure(
    clip_id: str,
    body: EnsureReviewBody | None = None,
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    run_id = body.run_id if body else None
    resolved_run = _resolve_run_id(clip_id, run_id)
    existing = get_review(clip_id, resolved_run)
    if existing:
        return _enrich_review_item(existing)
    try:
        result = enqueue_clip(clip_id, resolved_run, require_job3=False)
    except ValueError as exc:
        if "already exists" in str(exc):
            existing = get_review(clip_id, resolved_run)
            if existing:
                return _enrich_review_item(existing)
        raise _review_error(exc) from exc
    review = result.get("review")
    if not review and result.get("reason") == "already_exists":
        review = get_review(clip_id, resolved_run)
    if not review:
        raise HTTPException(
            status_code=500,
            detail={"code": "500_INTERNAL", "message": "failed to ensure review record"},
        )
    return _enrich_review_item(review)


@router.get("/clips/{clip_id}")
def api_review_detail(
    clip_id: str,
    run_id: str | None = Query(default=None),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    resolved_run = _resolve_run_id(clip_id, run_id)
    review = get_review(clip_id, resolved_run)
    if review is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "review not found"},
        )
    return _enrich_review_item(review)


@router.put("/clips/{clip_id}")
def api_review_save(
    clip_id: str,
    body: SaveReviewBody,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    if body.review_status not in REVIEW_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": f"invalid review_status: {body.review_status}"},
        )
    resolved_run = _resolve_run_id(clip_id, body.run_id)
    existing = get_review(clip_id, resolved_run)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "review not found"},
        )
    try:
        review = update_review(
            clip_id,
            resolved_run,
            labels_json=body.labels_json,
            review_status=body.review_status,
            reviewer_id=user["id"] if body.review_status == "reviewed" else None,
            expected_updated_at=body.updated_at,
        )
    except ValueError as exc:
        raise _review_error(exc) from exc
    try:
        from hmi.services.clips_local import label_map_cache_clear

        label_map_cache_clear()
    except Exception:
        pass
    if body.review_status == "reviewed":
        try:
            export_review_to_oss(review, reviewer_id=user["id"])
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("review OSS export failed: %s", exc)
    append_audit_log(
        actor_id=user["id"],
        action="clip.review",
        resource_type="clip_label_review",
        resource_id=review["id"],
        detail={
            "clip_id": clip_id,
            "run_id": resolved_run,
            "previous_status": existing["review_status"],
            "review_status": review["review_status"],
        },
    )
    return review


@router.post("/clips/{clip_id}/reopen")
def api_review_reopen(
    clip_id: str,
    body: ReopenReviewBody | None = None,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    run_id = body.run_id if body else None
    resolved_run = _resolve_run_id(clip_id, run_id)
    existing = get_review(clip_id, resolved_run)
    if existing is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "review not found"},
        )
    if existing["review_status"] != "reviewed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "409_CONFLICT",
                "message": "only reviewed clips can be reopened",
            },
        )
    try:
        review = update_review(
            clip_id,
            resolved_run,
            review_status="pending_review",
            expected_updated_at=existing["updated_at"],
        )
    except ValueError as exc:
        raise _review_error(exc) from exc
    cleared = delete_field_reviews(clip_id, resolved_run)
    append_audit_log(
        actor_id=user["id"],
        action="clip.reopen",
        resource_type="clip_label_review",
        resource_id=review["id"],
        detail={
            "clip_id": clip_id,
            "run_id": resolved_run,
            "previous_status": "reviewed",
            "review_status": review["review_status"],
            "cleared_field_reviews": cleared,
        },
    )
    return review


@router.post("/enqueue")
def api_review_enqueue(
    body: EnqueueReviewBody,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    if not body.scan_unqueued and not body.clip_ids:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "422_VALIDATION",
                "message": "clip_ids or scan_unqueued required",
            },
        )
    results = enqueue_clips(
        clip_ids=body.clip_ids,
        scan_unqueued=body.scan_unqueued,
        require_job3=body.require_job3,
    )
    created = sum(1 for r in results if r.get("status") == "created")
    skipped = sum(1 for r in results if r.get("status") == "skipped")
    errors = sum(1 for r in results if r.get("status") == "error")
    return {
        "results": results,
        "summary": {"created": created, "skipped": skipped, "errors": errors},
    }
