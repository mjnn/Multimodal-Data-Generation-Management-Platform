"""Dataset snapshot REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from hmi.audit import append_audit_log
from hmi.auth.deps import require_dataset_manager, require_dataset_read
from hmi.dataset.assemble import (
    MAX_CLIP_COUNT,
    assemble_snapshot_rows,
    count_dataset_ready_in_pool,
    normalize_filter,
    pool_preview_items,
    preview_skip_reasons,
    query_review_candidates,
    query_review_pool,
)
from hmi.dataset.build import enqueue_build, is_build_running
from hmi.dataset.aug_recipe_db import create_recipe, get_recipe, list_recipes, publish_recipe
from hmi.dataset.derive import derive_snapshot_from_parent, resolve_augmentation_mode
from hmi.dataset.lineage import get_snapshot_lineage_context
from hmi.dataset.distribution import embedding_summary
from hmi.dataset.export_advisor import build_export_recommendation
from hmi.dataset.taxonomy_hint import taxonomy_context_for_filter, taxonomy_context_for_snapshot
from hmi.taxonomy.insights import build_pool_taxonomy_distribution
from hmi.dataset_db import (
    DATASET_STATUSES,
    DEFAULT_FILTER,
    EXPORT_PRESETS,
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
    export_preset: str | None = None
    balance_by_label: str | None = None
    min_per_class: int | None = Field(default=None, ge=1)
    max_per_class: int | None = Field(default=None, ge=1)
    oversample_policy: str | None = None
    oversample_max_multiplier: int | None = Field(default=None, ge=1, le=100)
    include_parquet: bool = False
    export_label_ids: list[str] | None = None
    export_taxonomy_version_id: str | None = None


class CreateDatasetBody(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    filter_json: DatasetFilterBody | None = None
    export_preset: str | None = None
    aug_recipe_id: str | None = None


class PreviewDatasetBody(BaseModel):
    """Preview-only body; name optional (not persisted)."""

    name: str | None = None
    filter_json: DatasetFilterBody | None = None
    export_preset: str | None = None


class DeriveDatasetBody(BaseModel):
    name: str = Field(min_length=1)
    description: str | None = None
    filter_json: DatasetFilterBody | None = None
    taxonomy_crop_label_ids: list[str] | None = None
    aug_recipe_id: str | None = None


class CreateAugRecipeBody(BaseModel):
    recipe_code: str = Field(min_length=1)
    spec_json: dict[str, Any]
    version: int | None = Field(default=None, ge=1)


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


def _resolve_filter(body: CreateDatasetBody | DeriveDatasetBody | PreviewDatasetBody, *, user: dict[str, Any]) -> dict[str, Any]:
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
                        "message": "包含待校核 clip 需要管理员权限",
                    },
                )
            filt["include_pending_review"] = True
        filt.update(payload)
    export_preset = getattr(body, "export_preset", None)
    if export_preset:
        filt["export_preset"] = export_preset
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


def _preview_assembly(filter_json: dict[str, Any]) -> dict[str, Any]:
    try:
        assembly = assemble_snapshot_rows(filter_json, max_clips=MAX_CLIP_COUNT)
    except ValueError as exc:
        return {
            "estimated_line_count": 0,
            "estimated_clip_count": 0,
            "distribution_before": {},
            "distribution_after": {},
            "preview_error": str(exc),
            "label_column_count": 0,
            "embedding_summary": {},
        }
    dist = assembly.distribution_report or {}
    label_keys: set[str] = set()
    for row in assembly.rows:
        y = row.get("y_json")
        if isinstance(y, dict):
            label_keys.update(str(k) for k in y.keys())
    return {
        "estimated_line_count": assembly.line_count,
        "estimated_clip_count": assembly.clip_count,
        "distribution_before": dist.get("before", {}),
        "distribution_after": dist.get("after", {}),
        "label_column_count": len(label_keys),
        "embedding_summary": embedding_summary(assembly.rows),
    }


def _get_snapshot_or_404(snapshot_id: str) -> dict[str, Any]:
    snapshot = get_snapshot(snapshot_id.strip())
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "数据集快照不存在"},
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
    body: PreviewDatasetBody,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    filter_json = _resolve_filter(body, user=user)
    pool = query_review_pool(filter_json)
    candidates = query_review_candidates(filter_json)
    pool_items = pool_preview_items(pool)
    assembly_preview = _preview_assembly(filter_json)
    skipped_preview = preview_skip_reasons(filter_json)
    dataset_ready_count = count_dataset_ready_in_pool(pool)
    reviewed_count = len(pool)
    exceeds = len(candidates) > MAX_CLIP_COUNT
    export_recommendation = build_export_recommendation(
        filter_json=filter_json,
        estimated_clip_count=int(assembly_preview.get("estimated_clip_count") or len(candidates)),
        estimated_line_count=int(assembly_preview.get("estimated_line_count") or len(candidates)),
        label_column_count=int(assembly_preview.get("label_column_count") or 0),
        embedding_summary=assembly_preview.get("embedding_summary"),
        distribution_after=assembly_preview.get("distribution_after"),
        exceeds_clip_limit=exceeds,
        clip_limit=MAX_CLIP_COUNT,
        preview_error=assembly_preview.get("preview_error"),
    )
    return {
        "pool_count": len(pool),
        "candidate_count": len(candidates),
        "reviewed_count": reviewed_count,
        "dataset_ready_count": dataset_ready_count,
        "sample_size": filter_json.get("sample_size"),
        "export_preset": filter_json.get("export_preset"),
        "clip_ids": [str(c["clip_id"]) for c in candidates[:20]],
        "pool_items": pool_items,
        "pool_items_truncated": len(pool) > len(pool_items),
        "filter_json": filter_json,
        "skipped_preview": skipped_preview,
        "distribution_before": assembly_preview.get("distribution_before", {}),
        "distribution_after": assembly_preview.get("distribution_after", {}),
        "estimated_line_count": assembly_preview.get("estimated_line_count", len(candidates)),
        "estimated_clip_count": assembly_preview.get("estimated_clip_count", len(candidates)),
        "label_column_count": assembly_preview.get("label_column_count", 0),
        "embedding_summary": assembly_preview.get("embedding_summary", {}),
        "exceeds_clip_limit": exceeds,
        "clip_limit": MAX_CLIP_COUNT,
        "export_recommendation": export_recommendation,
        "taxonomy_version_distribution": build_pool_taxonomy_distribution(pool),
        **taxonomy_context_for_filter(filter_json),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def api_create_dataset(
    body: CreateDatasetBody,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    filter_json = _resolve_filter(body, user=user)
    _validate_candidate_count(filter_json)
    export_preset = str(filter_json.get("export_preset") or body.export_preset or "minimal")
    if export_preset not in EXPORT_PRESETS:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": f"invalid export_preset: {export_preset}"},
        )
    aug_recipe_id = body.aug_recipe_id
    if aug_recipe_id:
        from hmi.dataset.aug_recipe_db import get_published_recipe

        get_published_recipe(aug_recipe_id)
    augmentation_mode = resolve_augmentation_mode(
        balance_by_label=filter_json.get("balance_by_label"),
        aug_recipe_id=aug_recipe_id,
    )
    snapshot = create_snapshot(
        body.name.strip(),
        description=body.description,
        filter_json=filter_json,
        created_by=user["id"],
        export_preset=export_preset,
        augmentation_mode=augmentation_mode,
        aug_recipe_id=aug_recipe_id,
    )
    append_audit_log(
        actor_id=user["id"],
        action="dataset.create",
        resource_type="dataset_snapshot",
        resource_id=snapshot["id"],
        detail={
            "name": snapshot["name"],
            "filter_json": filter_json,
            "export_preset": export_preset,
            "augmentation_mode": augmentation_mode,
            "include_pending_review": bool(filter_json.get("include_pending_review")),
        },
    )
    enqueue_build(snapshot["id"])
    refreshed = get_snapshot(snapshot["id"])
    assert refreshed is not None
    return refreshed


@router.post("/{snapshot_id}/derive", status_code=status.HTTP_201_CREATED)
def api_derive_dataset(
    snapshot_id: str,
    body: DeriveDatasetBody,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    parent = _get_snapshot_or_404(snapshot_id)
    if parent["status"] != "ready":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "409_CONFLICT",
                "message": f"derive requires ready parent (current: {parent['status']})",
            },
        )
    filter_overrides: dict[str, Any] | None = None
    if body.filter_json:
        payload = body.filter_json.model_dump(exclude_none=True)
        include_pending = payload.pop("include_pending_review", None)
        if include_pending:
            roles = user.get("roles") or []
            if "admin" not in roles:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "code": "403_FORBIDDEN",
                        "message": "包含待校核 clip 需要管理员权限",
                    },
                )
        filter_overrides = payload
    try:
        derived = derive_snapshot_from_parent(
            snapshot_id,
            name=body.name,
            description=body.description,
            filter_overrides=filter_overrides,
            taxonomy_crop_label_ids=body.taxonomy_crop_label_ids,
            aug_recipe_id=body.aug_recipe_id,
            created_by=user["id"],
        )
    except ValueError as exc:
        raise _dataset_error(exc) from exc
    append_audit_log(
        actor_id=user["id"],
        action="dataset.derive",
        resource_type="dataset_snapshot",
        resource_id=derived["id"],
        detail={
            "parent_snapshot_id": snapshot_id,
            "name": derived["name"],
            "derivation_json": derived.get("derivation_json"),
        },
    )
    enqueue_build(derived["id"])
    refreshed = get_snapshot(derived["id"])
    assert refreshed is not None
    return refreshed


@router.get("/aug-recipes")
def api_list_aug_recipes(
    status: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user: dict = Depends(require_dataset_read),
) -> dict[str, Any]:
    try:
        items = list_recipes(status=status.strip() if status else None, limit=limit, offset=offset)
    except ValueError as exc:
        raise _dataset_error(exc) from exc
    return {"items": items, "limit": limit, "offset": offset}


@router.post("/aug-recipes", status_code=status.HTTP_201_CREATED)
def api_create_aug_recipe(
    body: CreateAugRecipeBody,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    try:
        recipe = create_recipe(
            body.recipe_code,
            body.spec_json,
            version=body.version,
            created_by=user["id"],
        )
    except ValueError as exc:
        raise _dataset_error(exc) from exc
    append_audit_log(
        actor_id=user["id"],
        action="aug_recipe.create",
        resource_type="aug_recipe",
        resource_id=recipe["id"],
        detail={"recipe_code": recipe["recipe_code"], "version": recipe["version"]},
    )
    return recipe


@router.post("/aug-recipes/{recipe_id}/publish")
def api_publish_aug_recipe(
    recipe_id: str,
    user: dict = Depends(require_dataset_manager),
) -> dict[str, Any]:
    try:
        recipe = publish_recipe(recipe_id)
    except ValueError as exc:
        raise _dataset_error(exc) from exc
    append_audit_log(
        actor_id=user["id"],
        action="aug_recipe.publish",
        resource_type="aug_recipe",
        resource_id=recipe_id,
        detail={"recipe_code": recipe["recipe_code"], "version": recipe["version"]},
    )
    return recipe


@router.get("/{snapshot_id}")
def api_get_dataset(
    snapshot_id: str,
    _user: dict = Depends(require_dataset_read),
) -> dict[str, Any]:
    snapshot = _get_snapshot_or_404(snapshot_id)
    payload = dict(snapshot)
    payload["build_running"] = is_build_running(snapshot_id)
    payload["build_report"] = snapshot.get("build_report")
    if snapshot.get("parent_snapshot_id"):
        parent = get_snapshot(str(snapshot["parent_snapshot_id"]))
        if parent:
            payload["parent_snapshot"] = {
                "id": parent["id"],
                "name": parent["name"],
                "status": parent["status"],
            }
    try:
        payload["lineage"] = get_snapshot_lineage_context(snapshot_id)
    except ValueError:
        payload["lineage"] = None
    if snapshot.get("aug_recipe_id"):
        recipe = get_recipe(str(snapshot["aug_recipe_id"]))
        if recipe:
            payload["aug_recipe"] = {
                "id": recipe["id"],
                "recipe_code": recipe["recipe_code"],
                "version": recipe["version"],
                "status": recipe["status"],
            }
    payload.update(taxonomy_context_for_snapshot(snapshot))
    br = snapshot.get("build_report") or {}
    payload["parquet_available"] = bool(br.get("parquet_available"))
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
        "line_count": snapshot.get("line_count"),
        "export_preset": snapshot.get("export_preset"),
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
