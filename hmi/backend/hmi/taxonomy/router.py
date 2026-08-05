"""Taxonomy version tree REST API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from hmi.auth.deps import require_clip_explorer_access, require_taxonomy_manager
from hmi.audit import append_audit_log
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
from hmi.taxonomy_import import import_taxonomy_from_yaml, import_taxonomy_from_yaml_content
from hmi.taxonomy.insights import build_coverage, build_taxonomy_context
from hmi.taxonomy.diff import diff_versions
from hmi.taxonomy.impact import build_version_impact
from hmi.taxonomy.lineage import build_version_lineage
from hmi.taxonomy.node_usage import build_node_usage
from hmi.taxonomy.proposal_workflow import (
    TREE_REVISION_TYPE,
    approve_proposal_to_draft,
    materialize_proposal_version,
    reject_proposal_with_version,
    _require_evidence,
)
from hmi.taxonomy_proposal_db import (
    create_proposal,
    get_open_proposal_for_version,
    get_proposal,
    list_proposals,
    update_proposal_status,
)

router = APIRouter(prefix="/api/taxonomy", tags=["taxonomy"])


class CreateVersionBody(BaseModel):
    version_code: str | None = Field(default=None, min_length=1)
    import_yaml: bool = False


class ImportYamlVersionBody(BaseModel):
    version_code: str = Field(min_length=1)
    yaml_content: str = Field(min_length=1)


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
    if draft_conflict or "not draft" in message or "already exists" in message:
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
        if node.get("is_active") is False:
            continue
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
    include_archived: bool = False,
    _user: dict = Depends(require_clip_explorer_access),
) -> list[dict[str, Any]]:
    return [
        _version_payload(v)
        for v in list_versions(include_archived=include_archived)
    ]


@router.post("/versions", status_code=201)
def api_create_taxonomy_version(
    body: CreateVersionBody,
    user: dict = Depends(require_taxonomy_manager),
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


@router.post("/versions/import-yaml", status_code=201)
def api_import_taxonomy_yaml(
    body: ImportYamlVersionBody,
    user: dict = Depends(require_taxonomy_manager),
) -> dict[str, Any]:
    try:
        result = import_taxonomy_from_yaml_content(
            body.yaml_content,
            version_code=body.version_code.strip(),
            created_by=user["id"],
        )
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    version = get_version(result.version_id)
    assert version is not None
    return _version_payload(version)


@router.post("/versions/{version_id}/clone", status_code=201)
def api_clone_taxonomy_version(
    version_id: str,
    body: CloneVersionBody,
    user: dict = Depends(require_taxonomy_manager),
) -> dict[str, Any]:
    try:
        version = clone_version(version_id, body.version_code, created_by=user["id"])
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    return _version_payload(version)


@router.get("/versions/{version_id}/tree")
def api_get_taxonomy_tree(
    version_id: str,
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    version = _get_version_or_404(version_id)
    nodes = list_nodes(version_id)
    linked_proposal = get_open_proposal_for_version(version_id)
    return {
        "version": _version_payload(version),
        "nodes": nodes,
        "tree": _nodes_to_tree(nodes),
        "linked_proposal": linked_proposal,
    }


@router.put("/versions/{version_id}/nodes")
def api_replace_taxonomy_nodes(
    version_id: str,
    body: ReplaceNodesBody,
    _admin: dict = Depends(require_taxonomy_manager),
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
    _admin: dict = Depends(require_taxonomy_manager),
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
    _admin: dict = Depends(require_taxonomy_manager),
) -> dict[str, Any]:
    try:
        version = archive_version(version_id)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    return _version_payload(version)


class CreateProposalBody(BaseModel):
    title: str = Field(min_length=1)
    base_version_id: str = Field(min_length=1)
    evidence: dict[str, Any]
    nodes: list[TaxonomyNodeInput] = Field(min_length=1)
    version_code: str | None = Field(default=None, min_length=1)


class PatchProposalBody(BaseModel):
    status: str = Field(min_length=1)
    merged_version_id: str | None = None


@router.get("/context")
def api_taxonomy_context(
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    return build_taxonomy_context()


@router.get("/versions/{version_id}/coverage")
def api_taxonomy_coverage(
    version_id: str,
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    try:
        return build_coverage(version_id)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc


@router.get("/versions/{version_id}/diff")
def api_taxonomy_diff(
    version_id: str,
    against: str,
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    try:
        return diff_versions(version_id, against)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc


@router.get("/versions/{version_id}/impact")
def api_taxonomy_impact(
    version_id: str,
    _admin: dict = Depends(require_taxonomy_manager),
) -> dict[str, Any]:
    try:
        return build_version_impact(version_id)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc


@router.get("/versions/{version_id}/lineage")
def api_taxonomy_lineage(
    version_id: str,
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    try:
        return build_version_lineage(version_id)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc


@router.get("/nodes/{label_id}/usage")
def api_taxonomy_node_usage(
    label_id: str,
    version_id: str | None = None,
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    try:
        return build_node_usage(label_id, taxonomy_version_id=version_id)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc


@router.get("/proposals")
def api_list_taxonomy_proposals(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    items, total = list_proposals(status=status, limit=min(limit, 200), offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/proposals", status_code=201)
def api_create_taxonomy_proposal(
    body: CreateProposalBody,
    user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    try:
        evidence = _require_evidence(body.evidence)
        node_payload = [node.model_dump() for node in body.nodes]
        version_id, base_id = materialize_proposal_version(
            base_version_id=body.base_version_id,
            nodes=node_payload,
            created_by=user["id"],
            title=body.title,
            version_code=body.version_code,
        )
        proposal = create_proposal(
            title=body.title,
            proposal_type=TREE_REVISION_TYPE,
            evidence=evidence,
            created_by=user["id"],
            target_label_id=None,
            suggested_patch_json={
                "base_version_id": base_id,
                "node_count": len(node_payload),
            },
            taxonomy_version_id=version_id,
        )
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    append_audit_log(
        actor_id=user["id"],
        action="taxonomy.proposal.create",
        resource_type="taxonomy_proposal",
        resource_id=proposal["id"],
        detail={
            "title": body.title,
            "proposal_type": TREE_REVISION_TYPE,
            "base_version_id": body.base_version_id,
            "taxonomy_version_id": proposal.get("taxonomy_version_id"),
            "node_count": len(body.nodes),
        },
    )
    return proposal


@router.get("/proposals/{proposal_id}")
def api_get_taxonomy_proposal(
    proposal_id: str,
    _user: dict = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    proposal = get_proposal(proposal_id)
    if proposal is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "proposal not found"},
        )
    return proposal


@router.post("/proposals/{proposal_id}/approve-draft")
def api_approve_proposal_to_draft(
    proposal_id: str,
    user: dict = Depends(require_taxonomy_manager),
) -> dict[str, Any]:
    try:
        proposal = approve_proposal_to_draft(proposal_id)
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    append_audit_log(
        actor_id=user["id"],
        action="taxonomy.proposal.approve_draft",
        resource_type="taxonomy_proposal",
        resource_id=proposal_id,
        detail={
            "merged_version_id": proposal.get("merged_version_id"),
            "taxonomy_version_id": proposal.get("taxonomy_version_id"),
        },
    )
    version = get_version(proposal["merged_version_id"]) if proposal.get("merged_version_id") else None
    return {
        "proposal": proposal,
        "version": _version_payload(version) if version else None,
    }


@router.patch("/proposals/{proposal_id}")
def api_patch_taxonomy_proposal(
    proposal_id: str,
    body: PatchProposalBody,
    user: dict = Depends(require_taxonomy_manager),
) -> dict[str, Any]:
    try:
        if body.status == "rejected":
            proposal = reject_proposal_with_version(proposal_id)
        elif body.status == "merged":
            if body.merged_version_id:
                proposal = update_proposal_status(
                    proposal_id,
                    status="merged",
                    merged_version_id=body.merged_version_id,
                )
            else:
                proposal = approve_proposal_to_draft(proposal_id)
        else:
            proposal = update_proposal_status(
                proposal_id,
                status=body.status,
                merged_version_id=body.merged_version_id,
            )
    except ValueError as exc:
        raise _taxonomy_error(exc) from exc
    append_audit_log(
        actor_id=user["id"],
        action="taxonomy.proposal.update",
        resource_type="taxonomy_proposal",
        resource_id=proposal_id,
        detail={"status": body.status, "merged_version_id": body.merged_version_id},
    )
    return proposal
