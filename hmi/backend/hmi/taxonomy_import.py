"""Import label taxonomy from YAML into app.db."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from hmi.app_db import ensure_schema
from hmi.config import TAXONOMY_PATH
from hmi.taxonomy_db import (
    count_nodes,
    create_version,
    get_version,
    get_version_by_code,
    publish_version,
    replace_nodes,
    update_version_source_import,
)

ImportAction = Literal["created", "skipped", "updated", "published"]


@dataclass(frozen=True)
class ParsedTaxonomyYaml:
    version_code: str
    source: str | None
    label_count: int | None
    labels: list[dict[str, Any]]
    yaml_path: Path


@dataclass(frozen=True)
class ImportResult:
    action: ImportAction
    version_id: str
    version_code: str
    node_count: int
    yaml_path: Path
    message: str


def parse_taxonomy_yaml(yaml_path: Path | None = None) -> ParsedTaxonomyYaml:
    path = (yaml_path or TAXONOMY_PATH).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"taxonomy YAML not found: {path}")

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    labels_raw = data.get("labels") or []
    if not labels_raw:
        raise ValueError(f"no labels[] in taxonomy YAML: {path}")

    version_code = str(data.get("version") or "v1").strip()
    if not version_code:
        raise ValueError("version_code resolved empty from YAML")

    label_count = data.get("label_count")
    if label_count is not None:
        label_count = int(label_count)

    return ParsedTaxonomyYaml(
        version_code=version_code,
        source=str(data.get("source") or "") or None,
        label_count=label_count,
        labels=[dict(item) for item in labels_raw],
        yaml_path=path,
    )


def yaml_labels_to_nodes(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for idx, item in enumerate(labels):
        label_id = str(item.get("id") or "").strip()
        if not label_id:
            raise ValueError(f"label at index {idx} missing id")

        nodes.append(
            {
                "level_code": str(item.get("level_code") or "other"),
                "level_name": item.get("level_name"),
                "label_id": label_id,
                "name": str(item.get("name") or label_id),
                "definition": item.get("definition"),
                "dtype": item.get("dtype"),
                "value_schema": item.get("value_schema"),
                "sort_order": idx,
                "is_active": True,
            }
        )
    return nodes


def import_taxonomy_from_yaml(
    yaml_path: Path | None = None,
    *,
    version_code: str | None = None,
    publish: bool = False,
    force: bool = False,
    created_by: str | None = None,
) -> ImportResult:
    ensure_schema()
    parsed = parse_taxonomy_yaml(yaml_path)
    resolved_code = (version_code or parsed.version_code).strip()
    if not resolved_code:
        raise ValueError("version_code required")

    nodes = yaml_labels_to_nodes(parsed.labels)
    source_import = str(parsed.yaml_path)

    existing = get_version_by_code(resolved_code)
    if existing is None:
        version = create_version(
            resolved_code,
            source_import=source_import,
            created_by=created_by,
        )
        replace_nodes(version["id"], nodes)
        node_count = count_nodes(version["id"])
        action: ImportAction = "created"
        message = f"created draft {resolved_code} with {node_count} nodes"
        version_id = version["id"]
    elif not force:
        node_count = count_nodes(existing["id"])
        return ImportResult(
            action="skipped",
            version_id=existing["id"],
            version_code=resolved_code,
            node_count=node_count,
            yaml_path=parsed.yaml_path,
            message=f"version {resolved_code} already exists; skipped",
        )
    elif existing["status"] != "draft":
        raise ValueError(
            f"cannot --force overwrite non-draft version {resolved_code} "
            f"(status={existing['status']})"
        )
    else:
        replace_nodes(existing["id"], nodes)
        update_version_source_import(existing["id"], source_import)
        node_count = count_nodes(existing["id"])
        action = "updated"
        message = f"updated draft {resolved_code} with {node_count} nodes"
        version_id = existing["id"]

    if parsed.label_count is not None and node_count != parsed.label_count:
        raise ValueError(
            f"imported node count {node_count} != YAML label_count {parsed.label_count}"
        )

    if publish:
        publish_version(version_id)
        from hmi.taxonomy.export import export_published_taxonomy

        export_published_taxonomy(version_id)
        action = "published"
        message = f"published {resolved_code} with {node_count} nodes"

    version = get_version(version_id)
    assert version is not None
    if publish and version["status"] != "published":
        raise RuntimeError(f"publish failed for {resolved_code}")

    return ImportResult(
        action=action,
        version_id=version_id,
        version_code=resolved_code,
        node_count=node_count,
        yaml_path=parsed.yaml_path,
        message=message,
    )
