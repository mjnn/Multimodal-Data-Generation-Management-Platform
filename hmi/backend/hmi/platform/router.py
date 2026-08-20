"""Platform kernel REST: operators, DataTypes, lake, samples, preflight, lineage."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hmi.auth.deps import require_admin, require_overview_access, require_pipeline_write
from hmi.data_source import is_local_mode
from hmi.platform.operators import list_operators
from hmi.platform.preflight import preflight
from hmi.platform.store import (
    TEXT_SCHEMAS,
    create_run,
    create_run_from_sources,
    create_sample,
    get_data_type,
    lineage_for_product,
    lineage_for_source,
    list_data_types,
    list_sources,
    lookup_or_record_product,
    preflight_sample,
    put_source,
    upsert_data_type,
)
from hmi.platform.views import list_view_templates

router = APIRouter(prefix="/api/platform", tags=["platform"])


class SourceIn(BaseModel):
    kind: str
    content_b64: str | None = None
    filename: str | None = None
    text_schema_id: str | None = None
    text: str | None = None
    collection_id: str | None = None


class SampleIn(BaseModel):
    source_ids: list[str]
    sample_id: str | None = None


class PreflightIn(BaseModel):
    data_type_id: str
    sample_id: str | None = None
    source_kinds: list[str] | None = None
    source_ids: list[str] | None = None


class RunIn(BaseModel):
    data_type_id: str
    sample_id: str | None = None
    source_ids: list[str] | None = None


class ProductLookupIn(BaseModel):
    input_ids: list[str]
    op_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    artifact_path: str | None = None
    run_id: str | None = None


@router.get("/operators")
def api_list_operators(_user: dict[str, Any] = Depends(require_overview_access)) -> dict[str, Any]:
    return {"operators": list_operators(), "views": list_view_templates(), "text_schemas": list(TEXT_SCHEMAS)}


@router.get("/data-types")
def api_list_data_types(_user: dict[str, Any] = Depends(require_overview_access)) -> dict[str, Any]:
    return {"items": list_data_types()}


@router.get("/data-types/{data_type_id}")
def api_get_data_type(
    data_type_id: str,
    _user: dict[str, Any] = Depends(require_overview_access),
) -> dict[str, Any]:
    rec = get_data_type(data_type_id)
    if rec is None:
        raise HTTPException(404, detail={"code": "UNKNOWN_DATA_TYPE", "message": data_type_id})
    return rec


@router.put("/data-types/{data_type_id}")
def api_put_data_type(
    data_type_id: str,
    body: dict[str, Any],
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    payload = dict(body)
    payload["id"] = data_type_id
    try:
        return upsert_data_type(payload)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "INVALID_RECIPE", "message": str(exc)}) from exc


@router.get("/sources")
def api_list_sources(
    limit: int = 100,
    eligible_for: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(require_overview_access),
) -> dict[str, Any]:
    """List persisted lake sources; optional ``eligible_for`` filters by DataType slots."""
    try:
        return {"items": list_sources(limit=limit, eligible_for=eligible_for)}
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/sources")
def api_put_source(
    body: SourceIn,
    _user: dict[str, Any] = Depends(require_pipeline_write),
) -> dict[str, Any]:
    if not is_local_mode():
        raise HTTPException(400, detail="platform source lake upload is only available in local mode")
    if body.text is not None:
        content = body.text.encode("utf-8")
    elif body.content_b64:
        import base64

        content = base64.b64decode(body.content_b64)
    else:
        raise HTTPException(400, detail="text or content_b64 required")
    try:
        return put_source(
            content=content,
            kind=body.kind,
            filename=body.filename,
            text_schema_id=body.text_schema_id,
            collection_id=body.collection_id,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/samples")
def api_create_sample(
    body: SampleIn,
    _user: dict[str, Any] = Depends(require_pipeline_write),
) -> dict[str, Any]:
    """Internal / advanced: prefer POST /runs with source_ids for the main path."""
    try:
        return create_sample(body.source_ids, sample_id=body.sample_id)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/runs/preflight")
def api_preflight(
    body: PreflightIn,
    _user: dict[str, Any] = Depends(require_pipeline_write),
) -> dict[str, Any]:
    try:
        if body.sample_id:
            return preflight_sample(body.sample_id, body.data_type_id)
        recipe = get_data_type(body.data_type_id)
        if recipe is None:
            raise ValueError(f"unknown data_type_id={body.data_type_id}")
        kinds = list(body.source_kinds or [])
        if body.source_ids:
            from hmi.app_db import db_conn

            with db_conn() as conn:
                for sid in body.source_ids:
                    row = conn.execute(
                        "SELECT kind FROM platform_source WHERE source_id = ?",
                        (sid,),
                    ).fetchone()
                    if row is None:
                        raise ValueError(f"unknown source_id={sid}")
                    kinds.append(str(row["kind"]))
        result = preflight(recipe, kinds)
        result["source_kinds"] = kinds
        return result
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/runs")
def api_create_run(
    body: RunIn,
    _user: dict[str, Any] = Depends(require_pipeline_write),
) -> dict[str, Any]:
    try:
        if body.source_ids:
            return create_run_from_sources(body.source_ids, body.data_type_id)
        if not body.sample_id:
            raise ValueError("sample_id or source_ids required")
        return create_run(body.sample_id, body.data_type_id)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc


@router.post("/products/lookup")
def api_product_lookup(
    body: ProductLookupIn,
    _user: dict[str, Any] = Depends(require_pipeline_write),
) -> dict[str, Any]:
    return lookup_or_record_product(
        input_ids=body.input_ids,
        op_id=body.op_id,
        params=body.params,
        artifact_path=body.artifact_path,
        run_id=body.run_id,
    )


@router.get("/lineage")
def api_lineage(
    source_id: str | None = Query(default=None),
    product_key: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(require_overview_access),
) -> dict[str, Any]:
    try:
        if source_id:
            return lineage_for_source(source_id)
        if product_key:
            return lineage_for_product(product_key)
        raise ValueError("source_id or product_key required")
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc
