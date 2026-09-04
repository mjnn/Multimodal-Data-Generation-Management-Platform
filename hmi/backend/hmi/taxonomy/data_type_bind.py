"""Resolve the taxonomy version bound to a DataType recipe."""

from __future__ import annotations

from typing import Any

from hmi.platform.store import get_data_type
from hmi.taxonomy_db import get_published_version, get_version_by_code, list_nodes, list_versions

_STATUS_RANK = {"published": 3, "draft": 2, "archived": 1, "proposal": 0}


def resolve_taxonomy_version_for_data_type(data_type_id: str) -> dict[str, Any] | None:
    """Pick the taxonomy version a DataType recipe binds to.

    Order: recipe.taxonomy_version_code → version_code matching taxonomy_id
    (exact or ``{taxonomy_id}-*`` / ``{taxonomy_id}_*``) → globally published
    (OMS YAML tree, whose version_code is typically ``v2`` rather than ``oms-*``).
    Does not publish draft trees such as ``audio_nvh-v2``.
    """
    dt_id = str(data_type_id or "").strip()
    if not dt_id:
        return None
    recipe = get_data_type(dt_id)
    if recipe is None:
        return None

    explicit = str(recipe.get("taxonomy_version_code") or "").strip()
    if explicit:
        found = get_version_by_code(explicit)
        if found is not None:
            return found

    taxonomy_id = str(recipe.get("taxonomy_id") or "").strip()
    if taxonomy_id:
        exact = get_version_by_code(taxonomy_id)
        if exact is not None:
            return exact
        prefix_hits: list[dict[str, Any]] = []
        for version in list_versions(include_archived=False):
            code = str(version.get("version_code") or "")
            if (
                code == taxonomy_id
                or code.startswith(f"{taxonomy_id}-")
                or code.startswith(f"{taxonomy_id}_")
            ):
                prefix_hits.append(version)
        if prefix_hits:
            prefix_hits.sort(
                key=lambda v: (
                    _STATUS_RANK.get(str(v.get("status") or ""), 0),
                    str(v.get("created_at") or ""),
                ),
                reverse=True,
            )
            return prefix_hits[0]

    return get_published_version()


def label_ids_for_data_type(data_type_id: str) -> set[str]:
    version = resolve_taxonomy_version_for_data_type(data_type_id)
    if version is None:
        return set()
    return {
        str(node["label_id"])
        for node in list_nodes(version["id"], active_only=True)
        if node.get("is_active") is not False and str(node.get("label_id") or "").strip()
    }
