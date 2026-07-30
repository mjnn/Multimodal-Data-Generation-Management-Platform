"""Review assignment REST API — admin dispatch + reviewer claim."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hmi.app_db import get_user_by_id, list_users
from hmi.audit import append_audit_log
from hmi.auth.deps import get_current_user, require_admin, require_reviewer
from hmi.review.assignment_db import (
    claim_items,
    clear_workbench_session,
    close_batch,
    get_batch,
    get_workbench_session,
    list_batch_items,
    list_reviewer_batches,
    save_workbench_session,
)
from hmi.review.assignment_service import (
    claim_low_confidence_batch,
    dispatch_assignment_batch,
    filter_tasks_for_batch,
    list_all_batches,
    preview_assignment_items,
)
from hmi.review.v2_tasks import build_pending_tasks

router = APIRouter(prefix="/api/review/assignments", tags=["review-assignments"])


class CreateBatchBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    label_ids: list[str] = Field(min_length=1)
    queue_limit: int = Field(ge=1, le=500)
    assignee_id: str | None = None


class PreviewBatchBody(BaseModel):
    label_ids: list[str] = Field(min_length=1)
    queue_limit: int = Field(ge=1, le=500)


class ClaimBody(BaseModel):
    batch_id: str = Field(min_length=1)
    limit: int = Field(default=50, ge=1, le=500)


class ClaimLowConfidenceBody(BaseModel):
    limit: int = Field(default=20, ge=1, le=500)


class SaveWorkbenchSessionBody(BaseModel):
    staged: dict[str, dict[str, Any]] = Field(default_factory=dict)
    current_index: int = Field(default=0, ge=0)


def _validation_error(message: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "422_VALIDATION", "message": message},
    )


def _not_found(message: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "404_NOT_FOUND", "message": message},
    )


@router.get("/reviewers")
def api_list_reviewers(_admin: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    users = list_users()
    return [
        {
            "id": u["id"],
            "username": u["username"],
            "display_name": u["display_name"],
            "roles": u.get("roles") or [],
        }
        for u in users
        if u.get("is_active") and ("reviewer" in (u.get("roles") or []) or "admin" in (u.get("roles") or []))
    ]


@router.post("/preview")
def api_preview_batch(
    body: PreviewBatchBody,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    items = preview_assignment_items(body.label_ids, body.queue_limit)
    return {"count": len(items), "items": items[:20]}


@router.post("/batches")
def api_create_batch(
    body: CreateBatchBody,
    admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    if body.assignee_id:
        user = get_user_by_id(body.assignee_id)
        if not user or not user.get("is_active"):
            raise _validation_error("指定的校核员不存在或已停用")
        roles = user.get("roles") or []
        if "reviewer" not in roles and "admin" not in roles:
            raise _validation_error("指定用户不是校核员")
    try:
        batch = dispatch_assignment_batch(
            name=body.name,
            label_ids=body.label_ids,
            queue_limit=body.queue_limit,
            assignee_id=body.assignee_id,
            created_by=admin["id"],
        )
    except ValueError as exc:
        raise _validation_error(str(exc)) from exc

    append_audit_log(
        actor_id=admin["id"],
        action="review.assignment.create",
        resource_type="review_assignment_batch",
        resource_id=batch["id"],
        detail={
            "name": body.name,
            "label_ids": body.label_ids,
            "queue_limit": body.queue_limit,
            "assignee_id": body.assignee_id,
            "item_total": batch.get("item_total"),
        },
    )
    return batch


@router.get("/batches")
def api_list_batches(
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    batches = list_all_batches()
    return {"items": batches, "total": len(batches)}


@router.get("/batches/{batch_id}")
def api_get_batch(
    batch_id: str,
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    batch = get_batch(batch_id)
    if not batch:
        raise _not_found("任务不存在")
    return batch


@router.get("/batches/{batch_id}/items")
def api_list_batch_items(
    batch_id: str,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    from hmi.app_db import get_user_by_id

    if not get_batch(batch_id):
        raise _not_found("任务不存在")
    items = list_batch_items(batch_id)
    for item in items:
        aid = item.get("assignee_id")
        if aid:
            user = get_user_by_id(str(aid))
            item["assignee_username"] = user["username"] if user else None
            item["assignee_display_name"] = user["display_name"] if user else str(aid)[:8]
    return {"items": items, "total": len(items)}


@router.post("/batches/{batch_id}/close")
def api_close_batch(
    batch_id: str,
    admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    batch = close_batch(batch_id)
    if not batch:
        raise _not_found("任务不存在")
    append_audit_log(
        actor_id=admin["id"],
        action="review.assignment.close",
        resource_type="review_assignment_batch",
        resource_id=batch_id,
        detail={},
    )
    return batch


@router.get("/mine")
def api_my_assignments(
    user: dict = Depends(require_reviewer),
    view: str = Query("all", pattern="^(active|completed|all)$"),
) -> dict[str, Any]:
    batches = list_reviewer_batches(user["id"], view=view)
    return {"items": batches, "total": len(batches)}


@router.post("/claim")
def api_claim_batch(
    body: ClaimBody,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    try:
        claimed = claim_items(
            batch_id=body.batch_id,
            assignee_id=user["id"],
            limit=body.limit,
        )
    except ValueError as exc:
        raise _validation_error(str(exc)) from exc
    if not claimed:
        raise _validation_error("没有可领取的条目（可能已被领完或已指定给其他校核员）")
    append_audit_log(
        actor_id=user["id"],
        action="review.assignment.claim",
        resource_type="review_assignment_batch",
        resource_id=body.batch_id,
        detail={"count": len(claimed)},
    )
    return {"items": claimed, "count": len(claimed)}


@router.post("/claim-low-confidence", status_code=201)
def api_claim_low_confidence(
    body: ClaimLowConfidenceBody,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    try:
        batch = claim_low_confidence_batch(
            assignee_id=user["id"],
            limit=body.limit,
            created_by=user["id"],
        )
    except ValueError as exc:
        raise _validation_error(str(exc)) from exc
    append_audit_log(
        actor_id=user["id"],
        action="review.assignment.claim_low_confidence",
        resource_type="review_assignment_batch",
        resource_id=batch["id"],
        detail={"limit": body.limit, "item_total": batch.get("item_total")},
    )
    return batch


@router.get("/batches/{batch_id}/work-queue")
def api_batch_work_queue(
    batch_id: str,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    batch = get_batch(batch_id)
    if not batch:
        raise _not_found("任务不存在")
    all_tasks = build_pending_tasks("confidence")
    tasks = filter_tasks_for_batch(all_tasks, batch_id=batch_id, assignee_id=user["id"])
    return {
        "batch": batch,
        "items": tasks,
        "total": len(tasks),
    }


@router.get("/batches/{batch_id}/session")
def api_get_workbench_session(
    batch_id: str,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    if not get_batch(batch_id):
        raise _not_found("任务不存在")
    session = get_workbench_session(batch_id, user["id"])
    if not session:
        return {
            "batch_id": batch_id,
            "staged": {},
            "current_index": 0,
            "updated_at": None,
        }
    return session


@router.put("/batches/{batch_id}/session")
def api_save_workbench_session(
    batch_id: str,
    body: SaveWorkbenchSessionBody,
    user: dict = Depends(require_reviewer),
) -> dict[str, Any]:
    if not get_batch(batch_id):
        raise _not_found("任务不存在")
    session = save_workbench_session(
        batch_id=batch_id,
        user_id=user["id"],
        staged=body.staged,
        current_index=body.current_index,
    )
    return session


@router.delete("/batches/{batch_id}/session")
def api_clear_workbench_session(
    batch_id: str,
    user: dict = Depends(require_reviewer),
) -> dict[str, bool]:
    if not get_batch(batch_id):
        raise _not_found("任务不存在")
    clear_workbench_session(batch_id, user["id"])
    return {"ok": True}
