"""Taxonomy version diff (M10)."""

from __future__ import annotations

import json
from typing import Any

from hmi.taxonomy_db import get_version, list_nodes


def _node_map(version_id: str) -> dict[str, dict[str, Any]]:
    return {str(n["label_id"]): n for n in list_nodes(version_id)}


def _norm_schema(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def diff_versions(base_version_id: str, against_version_id: str) -> dict[str, Any]:
    """Diff current version (base) against a reference version (against).

    Semantics: changes from reference → current.
    - added: label_ids present in current but not in reference
    - removed: label_ids present in reference but not in current
    """
    base_v = get_version(base_version_id)
    against_v = get_version(against_version_id)
    if base_v is None or against_v is None:
        raise ValueError("taxonomy version not found")

    base = _node_map(base_version_id)
    against = _node_map(against_version_id)
    base_ids = set(base)
    against_ids = set(against)

    added = sorted(base_ids - against_ids)
    removed = sorted(against_ids - base_ids)
    changed: list[dict[str, Any]] = []

    for label_id in sorted(base_ids & against_ids):
        b = base[label_id]
        a = against[label_id]
        fields: list[str] = []
        if str(b.get("name") or "") != str(a.get("name") or ""):
            fields.append("name")
        if str(b.get("dtype") or "") != str(a.get("dtype") or ""):
            fields.append("dtype")
        if _norm_schema(b.get("value_schema")) != _norm_schema(a.get("value_schema")):
            fields.append("value_schema")
        if bool(b.get("is_active", True)) != bool(a.get("is_active", True)):
            fields.append("is_active")
        if fields:
            changed.append(
                {
                    "label_id": label_id,
                    "fields": fields,
                    "before": {
                        "name": a.get("name"),
                        "dtype": a.get("dtype"),
                        "is_active": a.get("is_active"),
                    },
                    "after": {
                        "name": b.get("name"),
                        "dtype": b.get("dtype"),
                        "is_active": b.get("is_active"),
                    },
                }
            )

    return {
        "base_version_id": base_version_id,
        "base_version_code": base_v.get("version_code"),
        "against_version_id": against_version_id,
        "against_version_code": against_v.get("version_code"),
        "added_label_ids": added,
        "removed_label_ids": removed,
        "changed": changed,
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
        },
    }
