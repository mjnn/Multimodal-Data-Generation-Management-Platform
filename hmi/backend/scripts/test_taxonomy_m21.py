"""M2.1 taxonomy DB smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import ensure_schema
from hmi.taxonomy_db import (
    count_nodes,
    create_version,
    get_published_version,
    get_version,
    get_version_by_code,
    list_nodes,
    list_versions,
    replace_nodes,
)


def main() -> None:
    ensure_schema()

    code = "m21_test_v1"
    existing = get_version_by_code(code)
    if existing:
        version_id = existing["id"]
        print(f"reuse version {code} id={version_id}")
    else:
        v = create_version(code, source_import="test")
        version_id = v["id"]
        print(f"OK create_version -> {version_id}")

    nodes = [
        {
            "level_code": "L1.1",
            "level_name": "时间维度",
            "label_id": "L1.1.day_period",
            "name": "日时段",
            "definition": "按小时划分",
            "dtype": "enum",
            "value_schema": {"type": "enum", "values": ["morning", "night"]},
            "sort_order": 0,
        },
        {
            "level_code": "L1.1",
            "level_name": "时间维度",
            "label_id": "L1.1.is_holiday",
            "name": "是否节假日",
            "dtype": "bool",
            "value_schema": {"type": "bool", "values": ["true", "false"]},
            "sort_order": 1,
        },
    ]
    n = replace_nodes(version_id, nodes)
    assert n == 2
    assert count_nodes(version_id) == 2
    print("OK replace_nodes -> 2")

    listed = list_nodes(version_id)
    assert len(listed) == 2
    assert listed[0]["label_id"] == "L1.1.day_period"
    print("OK list_nodes")

    try:
        pub_code = "m21_pub"
        pub = get_version_by_code(pub_code)
        if pub is None:
            pub = create_version(pub_code, status="published")
        replace_nodes(pub["id"], nodes)
        print("FAIL should reject replace on published version")
        raise SystemExit(1)
    except ValueError as exc:
        assert "not draft" in str(exc)
        print(f"OK replace on published rejected")

    all_v = list_versions()
    assert any(v["version_code"] == code for v in all_v)
    print(f"OK list_versions count={len(all_v)}")

    assert get_version(version_id) is not None
    assert get_published_version() is None or isinstance(get_published_version(), dict)
    print("\nAll M2.1 checks passed.")


if __name__ == "__main__":
    main()
