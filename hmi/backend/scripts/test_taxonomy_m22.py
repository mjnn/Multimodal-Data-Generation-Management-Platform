"""M2.2 YAML taxonomy import smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.config import TAXONOMY_PATH
from hmi.taxonomy_db import count_nodes, get_version_by_code, list_nodes
from hmi.taxonomy_import import import_taxonomy_from_yaml, parse_taxonomy_yaml, yaml_labels_to_nodes


def main() -> None:
    parsed = parse_taxonomy_yaml(TAXONOMY_PATH)
    assert parsed.label_count == 68, f"expected label_count 68, got {parsed.label_count}"
    nodes = yaml_labels_to_nodes(parsed.labels)
    assert len(nodes) == 68
    assert nodes[0]["label_id"] == "L1.1.timestamp"
    print("OK parse_taxonomy_yaml -> 68 labels")

    test_code = "m22_test_import"
    existing = get_version_by_code(test_code)
    if existing and existing["status"] != "draft":
        raise SystemExit(f"cleanup required: {test_code} status={existing['status']}")

    r1 = import_taxonomy_from_yaml(
        TAXONOMY_PATH,
        version_code=test_code,
        force=existing is not None,
    )
    assert r1.node_count == 68
    assert r1.action in ("created", "updated")
    print(f"OK first import -> {r1.action} nodes=68")

    r2 = import_taxonomy_from_yaml(TAXONOMY_PATH, version_code=test_code)
    assert r2.action == "skipped"
    assert r2.node_count == 68
    print("OK idempotent skip")

    r3 = import_taxonomy_from_yaml(
        TAXONOMY_PATH,
        version_code=test_code,
        force=True,
    )
    assert r3.action == "updated"
    assert r3.node_count == 68
    print("OK force update draft")

    listed = list_nodes(r3.version_id)
    assert len(listed) == 68
    assert count_nodes(r3.version_id) == 68
    assert listed[-1]["label_id"]
    print("OK list_nodes count=68")

    print("\nAll M2.2 checks passed.")


if __name__ == "__main__":
    main()
