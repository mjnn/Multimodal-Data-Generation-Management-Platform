"""Taxonomy version clone lineage (M10)."""

from __future__ import annotations

from typing import Any

from hmi.taxonomy_db import get_version, list_versions


def _parent_from_source(source_import: str | None) -> str | None:
    if not source_import:
        return None
    prefix = "clone:"
    if source_import.startswith(prefix):
        return source_import[len(prefix) :].strip() or None
    return None


def list_child_version_ids(version_id: str) -> list[str]:
    children: list[str] = []
    for v in list_versions(include_archived=True):
        parent = _parent_from_source(v.get("source_import"))
        if parent == version_id:
            children.append(str(v["id"]))
    return children


def build_version_lineage(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise ValueError("taxonomy version not found")

    by_id = {str(v["id"]): v for v in list_versions(include_archived=True)}
    parent_id = _parent_from_source(version.get("source_import"))
    ancestors: list[dict[str, Any]] = []
    cursor = parent_id
    seen: set[str] = set()
    while cursor and cursor not in seen and cursor in by_id:
        seen.add(cursor)
        v = by_id[cursor]
        ancestors.append(
            {
                "id": cursor,
                "version_code": v.get("version_code"),
                "status": v.get("status"),
            }
        )
        cursor = _parent_from_source(v.get("source_import"))

    descendants: list[dict[str, Any]] = []

    def walk_children(vid: str, depth: int) -> None:
        if depth > 20:
            return
        for child_id in list_child_version_ids(vid):
            if child_id not in by_id:
                continue
            cv = by_id[child_id]
            descendants.append(
                {
                    "id": child_id,
                    "version_code": cv.get("version_code"),
                    "status": cv.get("status"),
                    "depth": depth,
                }
            )
            walk_children(child_id, depth + 1)

    walk_children(version_id, 1)

    chain = list(reversed(ancestors)) + [
        {
            "id": version_id,
            "version_code": version.get("version_code"),
            "status": version.get("status"),
        }
    ]

    return {
        "version_id": version_id,
        "parent_version_id": parent_id,
        "ancestors": list(reversed(ancestors)),
        "descendants": descendants,
        "lineage_chain": chain,
    }
