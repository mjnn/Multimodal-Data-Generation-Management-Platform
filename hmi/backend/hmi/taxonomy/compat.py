"""Label taxonomy compatibility: DB-first with YAML fallback."""

from __future__ import annotations

from typing import Any

import yaml

from hmi.config import TAXONOMY_PATH
from hmi.taxonomy_db import get_published_version, get_version, list_nodes


def nodes_to_label_taxonomy(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build LabelSearchPage-compatible grouped tree (children only id+name)."""
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
            }
        )
    return list(by_level.values())


def get_label_taxonomy_from_yaml() -> list[dict[str, Any]]:
    if not TAXONOMY_PATH.is_file():
        return []
    with TAXONOMY_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    labels = data.get("labels") or []
    by_level: dict[str, dict[str, Any]] = {}
    for item in labels:
        level_code = str(item.get("level_code") or "other")
        level_name = str(item.get("level_name") or level_code)
        if level_code not in by_level:
            by_level[level_code] = {"id": level_code, "name": level_name, "children": []}
        by_level[level_code]["children"].append(
            {"id": str(item.get("id")), "name": str(item.get("name"))}
        )
    return list(by_level.values())


def count_taxonomy_leaves(tree: list[dict[str, Any]]) -> int:
    total = 0
    for level in tree:
        total += len(level.get("children") or [])
    return total


def get_label_taxonomy(version_id: str | None = None) -> list[dict[str, Any]]:
    """Resolve taxonomy for GET /api/label-taxonomy."""
    if version_id:
        version = get_version(version_id)
        if version is None:
            raise ValueError(f"taxonomy version not found: {version_id}")
        nodes = list_nodes(version_id)
        return nodes_to_label_taxonomy(nodes)

    published = get_published_version()
    if published is not None:
        nodes = list_nodes(published["id"])
        return nodes_to_label_taxonomy(nodes)

    return get_label_taxonomy_from_yaml()
