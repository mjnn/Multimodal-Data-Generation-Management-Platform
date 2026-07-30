"""Export published taxonomy to OSS and update dispatch manifest."""

from __future__ import annotations

import json
from typing import Any

import yaml

from hmi.app_meta import write_app_meta
from hmi.config import get_settings
from hmi.oss_signer import get_object_json, put_object_text
from hmi.services.pipeline_status import DISPATCH_MANIFEST_KEY
from hmi.taxonomy_db import get_version, list_nodes

TAXONOMY_OSS_PREFIX = "config/taxonomy"
TAXONOMY_LATEST_KEY = f"{TAXONOMY_OSS_PREFIX}/latest.json"


def taxonomy_oss_key(version_code: str) -> str:
    code = version_code.strip()
    return f"{TAXONOMY_OSS_PREFIX}/{code}.yaml"


def nodes_to_yaml_document(version: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, Any]:
    labels: list[dict[str, Any]] = []
    for node in nodes:
        item: dict[str, Any] = {
            "level_code": node.get("level_code") or "other",
            "id": node["label_id"],
            "name": node.get("name") or node["label_id"],
        }
        if node.get("level_name"):
            item["level_name"] = node["level_name"]
        if node.get("definition"):
            item["definition"] = node["definition"]
        if node.get("dtype"):
            item["dtype"] = node["dtype"]
        if node.get("value_schema") is not None:
            schema = node["value_schema"]
            try:
                from shared.taxonomy_i18n import enrich_value_schema

                schema = enrich_value_schema(schema if isinstance(schema, dict) else None)
            except ImportError:
                pass
            item["value_schema"] = schema
        labels.append(item)

    return {
        "version": version["version_code"],
        "source": version.get("source_import") or "hmi_taxonomy_db",
        "label_count": len(labels),
        "excluded_labels": [],
        "labels": labels,
    }


def serialize_taxonomy_yaml(document: dict[str, Any]) -> str:
    return yaml.dump(document, allow_unicode=True, sort_keys=False, default_flow_style=False)


def taxonomy_pointer(version: dict[str, Any]) -> dict[str, str]:
    oss_key = taxonomy_oss_key(version["version_code"])
    return {
        "taxonomy_version_id": version["id"],
        "taxonomy_version_code": version["version_code"],
        "taxonomy_oss_key": oss_key,
    }


def merge_taxonomy_into_dispatch(
    payload: dict[str, Any],
    taxonomy: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(payload)
    for key in ("taxonomy_version_id", "taxonomy_version_code", "taxonomy_oss_key"):
        value = taxonomy.get(key)
        if value:
            merged[key] = str(value)
    return merged


def _require_oss_settings() -> None:
    get_settings()


def export_published_taxonomy(version_id: str) -> dict[str, Any]:
    """Upload YAML + latest pointer; merge dispatch manifest; update local app_meta."""
    _require_oss_settings()

    version = get_version(version_id)
    if version is None:
        raise ValueError(f"taxonomy version not found: {version_id}")
    if version["status"] != "published":
        raise ValueError(f"taxonomy version is not published: {version['status']}")

    nodes = list_nodes(version_id)
    if not nodes:
        raise ValueError("cannot export published taxonomy with zero nodes")

    document = nodes_to_yaml_document(version, nodes)
    yaml_text = serialize_taxonomy_yaml(document)
    oss_key = taxonomy_oss_key(version["version_code"])
    pointer = taxonomy_pointer(version)

    put_object_text(oss_key, yaml_text, content_type="application/x-yaml")
    put_object_text(
        TAXONOMY_LATEST_KEY,
        json.dumps({**pointer, "label_count": len(nodes)}, ensure_ascii=False, indent=2),
        content_type="application/json",
    )

    dispatch = get_object_json(DISPATCH_MANIFEST_KEY) or {}
    merged_dispatch = merge_taxonomy_into_dispatch(dispatch, pointer)
    put_object_text(
        DISPATCH_MANIFEST_KEY,
        json.dumps(merged_dispatch, ensure_ascii=False, indent=2),
        content_type="application/json",
    )

    write_app_meta(
        {
            "latest_published_taxonomy_version_id": pointer["taxonomy_version_id"],
            "latest_published_taxonomy_version_code": pointer["taxonomy_version_code"],
            "latest_published_taxonomy_oss_key": pointer["taxonomy_oss_key"],
        }
    )

    return {
        **pointer,
        "label_count": len(nodes),
        "dispatch_updated": bool(dispatch),
    }
