"""Dataset snapshot REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from hmi.audit import append_audit_log
from hmi.auth.deps import require_dataset_manager, require_dataset_read
from hmi.dataset.assemble import MAX_CLIP_COUNT, normalize_filter, pool_preview_items, query_review_candidates, query_review_pool
from hmi.dataset.build import enqueue_build, is_build_running
from hmi.dataset_db import (
    DATASET_STATUSES,
    DEFAULT_FILTER,
    count_snapshots,
    create_snapshot,
    get_snapshot,
    list_snapshots,
    update_snapshot,
)
from hmi.dataset.export import ensure_dataset_package_on_oss
from hmi.oss_signer import sign_key

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


class DatasetFilterBody(BaseModel):
    review_status: str | None = None
    include_pending_review: bool = False
    clip_ids: list[str] | None = None
    taxonomy_version_id: str | None = None
    label_filters: dict[str, Any] | None = None
    sample_size: int | None = Field(default=None, ge=1, le=MAX_CLIP_COUNT)


class CreateDatasetBody(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    filter_json: DatasetFilterBody | None = None


def _dataset_error(exc: ValueError) -> HTTPException:
    message = str(exc)
    if "not found" in message:
        return HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": message},
        )
    return HTTPException(
        status_code=422,
        detail={"code": "422_VALIDATION", "message": message},
    )


def _resolve_filter(body: CreateDatasetBody, *, user: dict[str, Any]) -> dict[str, Any]:
    filt = dict(DEFAULT_FILTER)
    if body.filter_json:
        payload = body.filter_json.model_dump(exclude_none=True)
        include_pending = bool(payload.pop("include_pending_review", False))
        if include_pending:
            roles = user.get("roles") or []
            if "admin" not in roles:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "403_FORBIDDEN",
                        "message": "include_pending_review requires admin role",
                    },
                )
            filt["include_pending_review"] = True
        filt.update(payload)
    return normalize_filter(filt)


def _validate_candidate_count(filter_json: dict[str, Any]) -> None:
    pool = query_review_pool(filter_json)
    if not pool:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "422_VALIDATION",
                "message": "没有符合条件的 Clip：请先完成校核，或在本地模式下确保 clip 已导入 AI 标签与向量；管理员可开启「包含待校核 clip」",
            },
        )
    sample_size = filter_json.get("sample_size")
    effective = min(len(pool), int(sample_size)) if sample_size else len(pool)
    if effective > MAX_CLIP_COUNT:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "422_VALIDATION",
                "message": f"clip count {effective} exceeds limit {MAX_CLIP_COUNT}",
            },
        )


def _get_snapshot_or_404(snapshot_id: str) -> dict[str, Any]:
    snapshot = get_snapshot(snapshot_id.strip())
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "dataset snapshot not found"},
        )
    return snapshot


@router.get("")
def api_list_datasets(
    status: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(require_dataset_read),
) -> dict[str, Any]:
    dataset_status = status.strip() if status else None
    if dataset_status and dataset_status not in DATASET_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": f"invalid status: {dataset_status}"},
        )
    try:
        items = list_snapshots(status=dataset_status, limit=limit, offset=offset)
        total = count_snapshots(status=dataset_status)
    except ValueError as exc:
        raise _dataset_error(exc) from exc
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/preview")
def api_preview_dataset(
    body: CreateDatasetBody,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    filter_json = _resolve_filter(body, user=user)
    pool = query_review_pool(filter_json)
    candidates = query_review_candidates(filter_json)
    pool_items = pool_preview_items(pool)
    return {
        "pool_count": len(pool),
        "candidate_count": len(candidates),
        "sample_size": filter_json.get("sample_size"),
        "clip_ids": [str(c["clip_id"]) for c in candidates[:20]],
        "pool_items": pool_items,
        "pool_items_truncated": len(pool) > len(pool_items),
        "filter_json": filter_json,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def api_create_dataset(
    body: CreateDatasetBody,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    filter_json = _resolve_filter(body, user=user)
    _validate_candidate_count(filter_json)
    snapshot = create_snapshot(
        body.name.strip(),
        description=body.description,
        filter_json=filter_json,
        created_by=user["id"],
    )
    append_audit_log(
        actor_id=user["id"],
        action="dataset.create",
        resource_type="dataset_snapshot",
        resource_id=snapshot["id"],
        detail={
            "name": snapshot["name"],
            "filter_json": filter_json,
            "include_pending_review": bool(filter_json.get("include_pending_review")),
        },
    )
    enqueue_build(snapshot["id"])
    refreshed = get_snapshot(snapshot["id"])
    assert refreshed is not None
    return refreshed


@router.get("/{snapshot_id}")
def api_get_dataset(
    snapshot_id: str,
    _user: dict = Depends(require_dataset_read),
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_404(snapshot_id)
    payload = dict(snapshot)
    payload["build_running"] = is_build_running(snapshot_id)
    return payload


@router.get("/{snapshot_id}/download")
def api_download_dataset(
    snapshot_id: str,
    expires: int = Query(3600, ge=60, le=86400),
    _user: dict = Depends(require_dataset_read),
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_404(snapshot_id)
    if snapshot["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "409_CONFLICT",
                "message": f"dataset not ready: {snapshot['status']}",
            },
        )
    x_key = snapshot.get("oss_x_uri")
    y_key = snapshot.get("oss_y_uri")
    if not x_key or not y_key:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "特征/目标产物不可用"},
        )
    try:
        package_key = ensure_dataset_package_on_oss(
            snapshot_id,
            snapshot_name=snapshot.get("name"),
            x_key=x_key,
            y_key=y_key,
            existing_package_key=snapshot.get("oss_manifest_uri"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": str(exc)},
        ) from exc
    filename = f"dataset-{snapshot.get('name') or snapshot_id}.zip".replace("/", "_")
    return {
        "snapshot_id": snapshot_id,
        "package_key": package_key,
        "package_url": sign_key(
            package_key,
            expires=expires,
            params={"response-content-disposition": f'attachment; filename="{filename}"'},
        ),
        "filename": filename,
        "clip_count": snapshot.get("clip_count"),
        "expires_in": expires,
        "x_key": x_key,
        "y_key": y_key,
        "x_url": sign_key(x_key, expires=expires),
        "y_url": sign_key(y_key, expires=expires),
    }


@router.post("/{snapshot_id}/retry")
def api_retry_dataset(
    snapshot_id: str,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_404(snapshot_id)
    if snapshot["status"] != "failed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "409_CONFLICT",
                "message": f"retry only allowed for failed snapshots (current: {snapshot['status']})",
            },
        )
    if is_build_running(snapshot_id):
        raise HTTPException(
            status_code=409,
            detail={"code": "409_CONFLICT", "message": "build already running"},
        )
    try:
        update_snapshot(snapshot_id, status="building", clear_error=True)
    except ValueError as exc:
        raise _dataset_error(exc) from exc
    enqueue_build(snapshot_id)
    refreshed = get_snapshot(snapshot_id)
    assert refreshed is not None
    return refreshed


@router.delete("/{snapshot_id}")
def api_delete_dataset(
    snapshot_id: str,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_404(snapshot_id)
    if snapshot["status"] == "archived":
        return snapshot
    try:
        archived = update_snapshot(snapshot_id, status="archived")
    except ValueError as exc:
        raise _dataset_error(exc) from exc
    append_audit_log(
        actor_id=user["id"],
        action="dataset.delete",
        resource_type="dataset_snapshot",
        resource_id=snapshot_id,
        detail={
            "name": snapshot["name"],
            "previous_status": snapshot["status"],
            "status": archived["status"],
        },
    )
    return archived
