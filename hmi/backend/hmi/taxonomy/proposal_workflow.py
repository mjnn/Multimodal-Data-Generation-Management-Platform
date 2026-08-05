"""Materialize taxonomy proposals as proposal-status versions and promote to draft.

流程：选已发布 base → 提交整棵树（tree_revision）→ 生成 status=proposal 版本 →
审核通过后 promote 为 draft。

``version_code`` 可选：空则 ``proposal-{8hex}``，有值则用用户指定（须全局唯一）。
血缘：``source_import=clone:{base_id}``，与 clone_version 一致，lineage 父节点为 base。
"""

from __future__ import annotations

import uuid
from typing import Any

from hmi.taxonomy_db import (
    archive_version,
    create_version,
    get_version,
    list_nodes,
    promote_proposal_to_draft,
    replace_nodes,
)
from hmi.taxonomy_proposal_db import get_proposal, update_proposal_status

TREE_REVISION_TYPE = "tree_revision"


def _node_payload(node: dict[str, Any], *, idx: int) -> dict[str, Any]:
    label_id = str(node.get("label_id") or "").strip()
    if not label_id:
        raise ValueError("each node requires label_id")
    return {
        "parent_id": node.get("parent_id"),
        "level_code": str(node.get("level_code") or "other"),
        "level_name": node.get("level_name"),
        "label_id": label_id,
        "name": str(node.get("name") or label_id),
        "definition": node.get("definition"),
        "dtype": node.get("dtype"),
        "value_schema": node.get("value_schema"),
        "sort_order": int(node.get("sort_order", idx)),
        "is_active": bool(node.get("is_active", True)),
    }


def _require_evidence(evidence: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise ValueError("evidence is required")
    note = str(evidence.get("note") or evidence.get("text") or "").strip()
    if not note:
        raise ValueError("evidence note is required")
    out = dict(evidence)
    out["note"] = note
    return out


def _resolve_base_version(base_version_id: str) -> dict[str, Any]:
    vid = str(base_version_id or "").strip()
    if not vid:
        raise ValueError("base_version_id is required")
    version = get_version(vid)
    if version is None:
        raise ValueError(f"taxonomy version not found: {vid}")
    status = str(version.get("status") or "")
    reason = version.get("archive_reason")
    released = status == "published" or (status == "archived" and reason == "superseded")
    if not released:
        raise ValueError("base version must be a published (or historically published) taxonomy")
    return version


def materialize_proposal_version(
    *,
    base_version_id: str,
    nodes: list[dict[str, Any]],
    created_by: str,
    title: str | None = None,
    version_code: str | None = None,
) -> tuple[str, str]:
    """Create a proposal-status version from base + full node tree.

    ``version_code`` is optional: blank/None → ``proposal-{8hex}``; otherwise use
    the caller-supplied code (must be unique).

    Returns (proposal_version_id, base_version_id).
    """
    base = _resolve_base_version(base_version_id)
    if not nodes:
        raise ValueError("proposal nodes must not be empty")
    payload = [_node_payload(n, idx=i) for i, n in enumerate(nodes)]
    label_ids = [n["label_id"] for n in payload]
    if len(set(label_ids)) != len(label_ids):
        raise ValueError("duplicate label_id in proposal nodes")

    code = (version_code or "").strip()
    if not code:
        code = f"proposal-{uuid.uuid4().hex[:8]}"
    # Same lineage convention as clone_version → parent_version_id = base id
    source = f"clone:{base['id']}"
    version = create_version(
        code,
        status="proposal",
        created_by=created_by,
        source_import=source,
    )
    replace_nodes(version["id"], payload)
    return version["id"], base["id"]


def clone_base_nodes_for_edit(base_version_id: str) -> list[dict[str, Any]]:
    """Return node payloads cloned from a published base (for UI bootstrap)."""
    base = _resolve_base_version(base_version_id)
    return [_node_payload(n, idx=i) for i, n in enumerate(list_nodes(base["id"], active_only=False))]


def approve_proposal_to_draft(proposal_id: str) -> dict[str, Any]:
    proposal = get_proposal(proposal_id)
    if proposal is None:
        raise ValueError("proposal not found")
    if proposal["status"] != "open":
        raise ValueError(f"proposal is not open: {proposal['status']}")
    version_id = proposal.get("taxonomy_version_id")
    if not version_id:
        raise ValueError("proposal has no materialized taxonomy version")
    version = get_version(version_id)
    if version is None:
        raise ValueError("linked taxonomy version not found")
    if version["status"] != "proposal":
        raise ValueError(f"linked taxonomy version is not proposal: {version['status']}")
    promote_proposal_to_draft(version_id)
    return update_proposal_status(
        proposal_id,
        status="merged",
        merged_version_id=version_id,
    )


def reject_proposal_with_version(proposal_id: str) -> dict[str, Any]:
    proposal = get_proposal(proposal_id)
    if proposal is None:
        raise ValueError("proposal not found")
    if proposal["status"] != "open":
        raise ValueError(f"proposal is not open: {proposal['status']}")
    version_id = proposal.get("taxonomy_version_id")
    if version_id:
        version = get_version(version_id)
        if version is not None and version["status"] == "proposal":
            archive_version(version_id)
    return update_proposal_status(proposal_id, status="rejected")
