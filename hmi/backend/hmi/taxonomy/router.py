"""Taxonomy version tree REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hmi.auth.deps import get_current_user, require_admin
from hmi.taxonomy_db import (
    archive_version,
    clone_version,
    count_nodes,
    create_version,
    get_version,
    list_nodes,
    list_versions,
    publish_version,
    replace_nodes,
)
from hmi.taxonomy.export import export_published_taxonomy
from hmi.taxonomy_import import import_taxonomy_from_yaml

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])


class CreateVersionBody(BaseModel):
    version_code: str | None = Field(default=None, min_length=1)
    import_yaml: bool = False


class CloneVersionBody(BaseModel):
    version_code: str = Field(min_length=1)


class TaxonomyNodeInput(BaseModel):
    label_id: str = Field(min_length=1)
    level_code: str = "other"
    level_name: str | None = None
    name: str | None = None
    definition: str | None = None
    dtype: str | None = None
    value_schema: dict[str, Any] | list[Any] | None = None
    sort_order: int | None = None
    is_active: bool = True


class ReplaceNodesBody(BaseModel):
    nodes: list[TaxonomyNodeInput] = Field(min_length=1)


def _taxonomy_error(exc: ValueError, *, draft_conflict: bool = False) -> HTTPException:
    message = str(exc)
    if draft_conflict or "not draft" in message:
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


def _version_payload(version: dict[str, Any]) -> dict[str, Any]:
    return {
        **version,
        "node_count": count_nodes(version["id"]),
    }


def _nodes_to_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_level: dict[str, dict[str, Any]] = {}
    for node in nodes:
        level_code = str(node.get("level_code") or "other")
        level_name = str(node.get("level_name") or level_code)
        if level_code not in by_level:
            by_level[level_code] = {
                "id": level_code,
                "name": level_name,
                "children": [],
            }
        by_level[level_code]["children"].append(
            {
                "id": node["label_id"],
                "name": node["name"],
                "definition": node.get("definition"),
                "dtype": node.get("dtype"),
                "value_schema": node.get("value_schema"),
            }
        )
    return list(by_level.values())


def _get_version_or_404(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "taxonomy version not found"},
        )
    return version


@router.get("/versions")
def api_list_taxonomy_versions(
    _user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    return [_version_payload(v) for v in list_versions()]


@router.post("/versions", status_code=201)
def api_create_taxonomy_version(
    body: CreateVersionBody,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    if body.import_yaml:
        if not body.version_code:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "422_VALIDATION",
                    "message": "version_code required when import_yaml is true",
                },
            )
        try:
            result = import_taxonomy_from_yaml(
                version_code=body.version_code,
                created_by=user["id"],
            )
        except (FileNotFoundError, ValueError) as exc:
            raise _taxonomy_error(
                ValueError(str(exc)),
            ) from exc
        version = get_version(result.version_id)
        assert version is not None
        return _version_payload(version)

    if not body.version_code:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": "version_code required"},
        )
    try:
        version = create_version(body.version_code, created_by=user["id"])
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    return _version_payload(version)


@router.post("/versions/{version_id}/clone", status_code=201)
def api_clone_taxonomy_version(
    version_id: str,
    body: CloneVersionBody,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    try:
        version = clone_version(version_id, body.version_code, created_by=user["id"])
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    return _version_payload(version)


@router.get("/versions/{version_id}/tree")
def api_get_taxonomy_tree(
    version_id: str,
    _user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    version = _get_version_or_404(version_id)
    nodes = list_nodes(version_id)
    return {
        "version": _version_payload(version),
        "nodes": nodes,
        "tree": _nodes_to_tree(nodes),
    }


@router.put("/versions/{version_id}/nodes")
def api_replace_taxonomy_nodes(
    version_id: str,
    body: ReplaceNodesBody,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    payload = [node.model_dump() for node in body.nodes]
    try:
        replaced = replace_nodes(version_id, payload)
    except ValueError as exc:
        raise _taxonomy_error(exc, draft_conflict=True) from exc
    version = _get_version_or_404(version_id)
    return {
        "version": _version_payload(version),
        "replaced": replaced,
    }


@router.post("/versions/{version_id}/publish")
def api_publish_taxonomy_version(
    version_id: str,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    try:
        version = publish_version(version_id)
        export_info = export_published_taxonomy(version_id)
    except ValueError as exc:
        raise _taxonomy_error(exc, draft_conflict=True) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "500_EXPORT_FAILED", "message": str(exc)},
        ) from exc
    return {**_version_payload(version), "export": export_info}


@router.post("/versions/{version_id}/archive")
def api_archive_taxonomy_version(
    version_id: str,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    try:
        version = archive_version(version_id)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    return _version_payload(version)
