"""Create draft taxonomy versions cropped to a label_id subset (dataset derive)."""

from __future__ import annotations

import re
import uuid
from typing import Any

from hmi.taxonomy_db import clone_version, get_version, list_nodes, replace_nodes


def _slug_code(name: str, *, suffix: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_]+", "_", name.strip())[:40].strip("_") or "dataset"
    return f"{base}_tax_{suffix}"[:120]


def expand_label_ids_with_ancestors(
    nodes: list[dict[str, Any]],
    selected_label_ids: set[str],
) -> set[str]:
    by_label = {str(n["label_id"]): n for n in nodes}
    by_id = {str(n["id"]): n for n in nodes}
    keep = {lid for lid in selected_label_ids if lid in by_label}
    if not keep:
        raise ValueError("no valid label_id in taxonomy crop selection")

    changed = True
    while changed:
        changed = False
        for lid in list(keep):
            node = by_label.get(lid)
            if not node:
                continue
            parent_id = node.get("parent_id")
            if not parent_id:
                continue
            parent = by_id.get(str(parent_id))
            if parent is None:
                continue
            plid = str(parent["label_id"])
            if plid not in keep:
                keep.add(plid)
                changed = True
    return keep


def crop_taxonomy_version(
    source_version_id: str,
    keep_label_ids: list[str],
    *,
    version_code: str | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Clone source taxonomy to draft and keep only selected nodes (+ ancestors)."""
    source = get_version(source_version_id.strip())
    if source is None:
        raise ValueError(f"taxonomy version not found: {source_version_id}")

    source_nodes = list_nodes(source_version_id, active_only=False)
    if not source_nodes:
        raise ValueError(f"taxonomy version has no nodes: {source_version_id}")

    selected = {str(lid).strip() for lid in keep_label_ids if str(lid).strip()}
    if not selected:
        raise ValueError("keep_label_ids must not be empty")

    expanded = expand_label_ids_with_ancestors(source_nodes, selected)
    code = (version_code or "").strip() or _slug_code(source.get("version_code") or "tax", suffix=uuid.uuid4().hex[:8])

    draft = clone_version(source_version_id, code, created_by=created_by)
    draft_id = str(draft["id"])
    cloned_nodes = list_nodes(draft_id, active_only=False)
    kept_nodes = [n for n in cloned_nodes if str(n["label_id"]) in expanded]
    if not kept_nodes:
        raise ValueError("taxonomy crop removed all nodes")

    replace_nodes(draft_id, kept_nodes)
    refreshed = get_version(draft_id)
    assert refreshed is not None
    export_label_ids = sorted(str(n["label_id"]) for n in kept_nodes)
    return {
        "version": refreshed,
        "cropped_version_id": draft_id,
        "source_version_id": source_version_id.strip(),
        "selected_label_ids": sorted(selected),
        "export_label_ids": export_label_ids,
    }


def resolve_export_label_ids(
    source_version_id: str,
    selected_label_ids: list[str],
) -> list[str]:
    """Expand crop selection to kept label_ids without creating a draft."""
    nodes = list_nodes(source_version_id.strip(), active_only=False)
    if not nodes:
        raise ValueError(f"taxonomy version has no nodes: {source_version_id}")
    selected = {str(lid).strip() for lid in selected_label_ids if str(lid).strip()}
    if not selected:
        raise ValueError("selected_label_ids must not be empty")
    expanded = expand_label_ids_with_ancestors(nodes, selected)
    return sorted(expanded)


def resolve_crop_source_version_id(parent: dict[str, Any]) -> str:
    """Pick taxonomy version to crop from parent snapshot context."""
    filt = parent.get("filter_json") or {}
    deriv = parent.get("derivation_json") or {}

    tax_crop = deriv.get("taxonomy_crop") or {}
    cropped = tax_crop.get("cropped_version_id")
    if cropped:
        return str(cropped)

    for key in ("export_taxonomy_version_id", "taxonomy_version_id"):
        tid = filt.get(key)
        if tid:
            return str(tid).strip()

    from hmi.taxonomy_db import get_published_version

    published = get_published_version()
    if published is None:
        raise ValueError("no published taxonomy version available for crop")
    return str(published["id"])
