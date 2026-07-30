"""Review v2 REST API — task queue (next/prev/stats)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hmi.audit import append_audit_log
from hmi.auth.deps import get_current_user, require_reviewer
from hmi.review.field_review_db import FIELD_REVIEW_ACTIONS
from hmi.review.merge import apply_field_review
from hmi.review.v2_tasks import (
    advance_session,
    build_pending_tasks,
    get_or_reset_session,
    list_label_options,
    normalize_review_v2_mode,
    parse_query_value,
    pick_next_task,
    prev_session_task,
    session_snapshot,
    task_stats,
)

router = APIRouter(prefix="/api/review/v2", tags=["review-v2"])


class SubmitReviewV2Body(BaseModel):
    clip_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    label_id: str = Field(min_length=1)
    action: Literal["confirm", "correct", "uncertain"]
    value: Any | None = None
    clip_updated_at: str | None = None
    assignment_batch_id: str | None = None


def _validation_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "422_VALIDATION", "message": message},
    )


def _review_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "conflict" in message:
        return HTTPException(
            status_code=409,
            detail={"code": "409_CONFLICT", "message": message},
        )
    return _validation_error(message)


def _parse_mode(mode: str) -> str:
    try:
        return normalize_review_v2_mode(mode)
    except ValueError:
        raise _validation_error(
            f"invalid mode: {mode}; expected confidence (or legacy ai_dispute) or comprehensive"
        ) from None


def _parse_comprehensive_params(
    mode: str,
    label_id: str | None,
    value: str | None,
    dtype: str | None = None,
) -> tuple[str | None, Any | None]:
    if mode != "comprehensive":
        return None, None
    lid = (label_id or "").strip()
    if not lid:
        raise _validation_error("label_id required for comprehensive mode")
    if value is None or value.strip() == "":
        raise _validation_error("value required for comprehensive mode")
    return lid, parse_query_value(value, dtype=dtype)


@router.get("/session")
def api_review_v2_session(
    mode: str = Query(...),
    label_id: str | None = Query(default=None),
    value: str | None = Query(default=None),
    dtype: str | None = Query(default=None),
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    mode = _parse_mode(mode)
    lid, filter_value = _parse_comprehensive_params(mode, label_id, value, dtype=dtype)
    session = get_or_reset_session(user["id"], mode, label_id=lid, filter_value=filter_value)
    stats = task_stats(mode, label_id=lid, filter_value=filter_value)
    return {
        "session": session_snapshot(session),
        "stats": stats,
    }


@router.get("/tasks/stats")
def api_review_v2_stats(
    mode: str = Query(...),
    label_id: str | None = Query(default=None),
    value: str | None = Query(default=None),
    dtype: str | None = Query(default=None),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    mode = _parse_mode(mode)
    lid, filter_value = _parse_comprehensive_params(mode, label_id, value, dtype=dtype)
    return task_stats(mode, label_id=lid, filter_value=filter_value)


@router.get("/next")
def api_review_v2_next(
    mode: str = Query(...),
    label_id: str | None = Query(default=None),
    value: str | None = Query(default=None),
    dtype: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    mode = _parse_mode(mode)
    lid, filter_value = _parse_comprehensive_params(mode, label_id, value, dtype=dtype)
    session = get_or_reset_session(user["id"], mode, label_id=lid, filter_value=filter_value)
    try:
        task = pick_next_task(
            mode,
            label_id=lid,
            filter_value=filter_value,
            cursor=cursor,
        )
    except ValueError as exc:
        raise _validation_error(str(exc)) from exc
    if task is None:
        return {"task": None, "session": session_snapshot(session)}
    advance_session(session, task)
    return {"task": task, "session": session_snapshot(session)}


@router.get("/prev")
def api_review_v2_prev(
    mode: str = Query(...),
    label_id: str | None = Query(default=None),
    value: str | None = Query(default=None),
    dtype: str | None = Query(default=None),
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    mode = _parse_mode(mode)
    lid, filter_value = _parse_comprehensive_params(mode, label_id, value, dtype=dtype)
    session = get_or_reset_session(user["id"], mode, label_id=lid, filter_value=filter_value)
    task = prev_session_task(session)
    return {"task": task, "session": session_snapshot(session)}


@router.get("/label-options")
def api_review_v2_label_options(
    keyword: str = Query(default=""),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    items = list_label_options(keyword)
    return {"items": items, "total": len(items)}


@router.get("/tasks")
def api_review_v2_tasks(
    mode: str = Query(...),
    label_id: str | None = Query(default=None),
    value: str | None = Query(default=None),
    dtype: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Debug/list endpoint — paginated pending tasks."""
    mode = _parse_mode(mode)
    lid, filter_value = _parse_comprehensive_params(mode, label_id, value, dtype=dtype)
    try:
        tasks = build_pending_tasks(mode, label_id=lid, filter_value=filter_value)
    except ValueError as exc:
        raise _validation_error(str(exc)) from exc
    page = tasks[offset : offset + limit]
    return {
        "items": page,
        "total": len(tasks),
        "limit": limit,
        "offset": offset,
    }


@router.post("/submit")
def api_review_v2_submit(
    body: SubmitReviewV2Body,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    action = body.action.strip()
    if action not in FIELD_REVIEW_ACTIONS:
        raise _validation_error(f"invalid action: {action}")

    if action == "correct" and body.value is None:
        raise _validation_error("value required for correct action")

    try:
        result = apply_field_review(
            clip_id=body.clip_id.strip(),
            run_id=body.run_id.strip(),
            label_id=body.label_id.strip(),
            action=action,
            reviewer_id=user["id"],
            value=body.value,
            expected_clip_updated_at=body.clip_updated_at,
        )
    except ValueError as exc:
        raise _review_error(exc) from exc

    try:
        from hmi.services.clips_local import label_map_cache_clear

        label_map_cache_clear()
    except Exception:
        pass

    field_review = result["field_review"]
    clip_review = result["clip_review"]
    rolled_up = bool(result.get("rolled_up_to_reviewed"))

    if rolled_up:
        try:
            from hmi.review.oss_export import export_review_to_oss

            export_review_to_oss(clip_review, reviewer_id=user["id"])
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("review v2 OSS export failed: %s", exc)

    append_audit_log(
        actor_id=user["id"],
        action="clip.label_field_review",
        resource_type="clip_label_field_review",
        resource_id=field_review["id"],
        detail={
            "clip_id": body.clip_id.strip(),
            "run_id": body.run_id.strip(),
            "label_id": body.label_id.strip(),
            "action": action,
            "human_doubtful": field_review.get("human_doubtful"),
            "value": field_review.get("value_json"),
            "review_status": clip_review.get("review_status"),
            "rolled_up_to_reviewed": rolled_up,
        },
    )

    assignment_item_done = False
    try:
        from hmi.review.assignment_db import mark_item_done

        assignment_item_done = mark_item_done(
            body.clip_id.strip(),
            body.run_id.strip(),
            body.label_id.strip(),
            user["id"],
            batch_id=(body.assignment_batch_id or "").strip() or None,
        )
    except Exception:
        assignment_item_done = False

    return {
        "field_review": field_review,
        "clip_review": clip_review,
        "rolled_up_to_reviewed": rolled_up,
        "assignment_item_done": assignment_item_done,
    }
