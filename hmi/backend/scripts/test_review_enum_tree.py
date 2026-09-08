"""Nested enum_tree review: parent-only is incomplete; parent+child can complete."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.review.enum_tree import (
    assert_enum_tree_review_complete,
    inspect_enum_tree_value,
    is_nested_enum_schema,
    normalize_enum_tree_value,
)
from hmi.review.merge import apply_field_review
from hmi.review_db import create_review
from hmi.taxonomy_db import create_version, replace_nodes

NESTED_SCHEMA = {
    "type": "enum_tree",
    "values": [
        {
            "id": "powertrain",
            "children": [{"id": "engine"}, {"id": "motor"}, {"id": "transmission"}],
        },
        {"id": "road"},
        {
            "id": "structure",
            "children": [
                {"id": "panel", "children": [{"id": "rattle"}, {"id": "buzz"}]},
            ],
        },
    ],
}


def _assert(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def test_inspect_helpers() -> None:
    _assert(is_nested_enum_schema(NESTED_SCHEMA, "enum_tree"), "nested schema")
    _assert(not is_nested_enum_schema({"type": "enum", "values": ["a", "b"]}, "enum"), "flat")

    empty = inspect_enum_tree_value(NESTED_SCHEMA, None, dtype="enum_tree")
    _assert(empty["complete"] is False, "empty incomplete")
    _assert(empty["missing_level"] == 1, "empty missing L1")

    parent = inspect_enum_tree_value(NESTED_SCHEMA, "powertrain", dtype="enum_tree")
    _assert(parent["complete"] is False, "parent-only incomplete")
    _assert(parent["missing_level"] == 2, "parent missing L2")
    _assert("powertrain" in (parent["message"] or ""), "parent message")

    path_parent = inspect_enum_tree_value(NESTED_SCHEMA, ["powertrain"], dtype="enum_tree")
    _assert(path_parent["complete"] is False, "path parent incomplete")

    mid = inspect_enum_tree_value(NESTED_SCHEMA, ["structure", "panel"], dtype="enum_tree")
    _assert(mid["complete"] is False, "two of three incomplete")
    _assert(mid["missing_level"] == 3, "missing L3")

    ok_leaf = inspect_enum_tree_value(NESTED_SCHEMA, "road", dtype="enum_tree")
    _assert(ok_leaf["complete"] is True, "leaf complete")

    ok_path = inspect_enum_tree_value(NESTED_SCHEMA, ["powertrain", "engine"], dtype="enum_tree")
    _assert(ok_path["complete"] is True, "parent+child complete")

    ok_slash = inspect_enum_tree_value(NESTED_SCHEMA, "powertrain/engine", dtype="enum_tree")
    _assert(ok_slash["complete"] is True, "slash path complete")

    ok_leaf_id = inspect_enum_tree_value(NESTED_SCHEMA, "engine", dtype="enum_tree")
    _assert(ok_leaf_id["complete"] is True, "unique leaf id resolves")

    ok_deep = inspect_enum_tree_value(
        NESTED_SCHEMA, ["structure", "panel", "rattle"], dtype="enum_tree"
    )
    _assert(ok_deep["complete"] is True, "three-level complete")

    bad = inspect_enum_tree_value(NESTED_SCHEMA, "not-a-value", dtype="enum_tree")
    _assert(bad["complete"] is False, "unknown id incomplete")

    try:
        assert_enum_tree_review_complete(NESTED_SCHEMA, "powertrain", dtype="enum_tree")
        raise AssertionError("parent-only should raise")
    except ValueError as exc:
        _assert("子值" in str(exc) or "未完成" in str(exc), str(exc))

    normalized = normalize_enum_tree_value(
        NESTED_SCHEMA, "engine", dtype="enum_tree"
    )
    _assert(normalized == ["powertrain", "engine"], f"normalize leaf -> path, got {normalized}")

    flat = inspect_enum_tree_value({"type": "enum", "values": ["morning"]}, "morning", dtype="enum")
    _assert(flat["complete"] is True and flat["nested"] is False, "flat passthrough")
    print("OK inspect helpers")


def test_apply_field_review_enforces() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"enum_tree_rev_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        user = create_user(reviewer_name, "reviewpass123", roles=["reviewer"])
        reviewer_id = user["id"]
    else:
        reviewer_id = get_user_by_username(reviewer_name)["id"]

    version = create_version(f"enum_tree_{suffix}", status="draft")
    label_id = f"demo.noise_{suffix}"
    replace_nodes(
        version["id"],
        [
            {
                "label_id": label_id,
                "level_code": "L6",
                "name": "噪音类别",
                "dtype": "enum_tree",
                "value_schema": NESTED_SCHEMA,
                "sort_order": 0,
                "is_active": True,
            },
        ],
    )

    clip_id = f"sha256:enum_tree_{suffix}"
    run_id = str(uuid.uuid4())
    create_review(
        clip_id,
        run_id,
        labels_json={label_id: "powertrain"},
        taxonomy_version_id=version["id"],
        review_status="pending_review",
    )

    try:
        apply_field_review(
            clip_id=clip_id,
            run_id=run_id,
            label_id=label_id,
            action="confirm",
            reviewer_id=reviewer_id,
            ai_value="powertrain",
            taxonomy_version_id=version["id"],
        )
        raise AssertionError("confirm parent-only should fail")
    except ValueError as exc:
        _assert("未完成" in str(exc), str(exc))
    print("OK reject confirm parent-only")

    try:
        apply_field_review(
            clip_id=clip_id,
            run_id=run_id,
            label_id=label_id,
            action="correct",
            reviewer_id=reviewer_id,
            value="powertrain",
            ai_value="powertrain",
            taxonomy_version_id=version["id"],
        )
        raise AssertionError("correct parent-only should fail")
    except ValueError as exc:
        _assert("未完成" in str(exc), str(exc))
    print("OK reject correct parent-only")

    result = apply_field_review(
        clip_id=clip_id,
        run_id=run_id,
        label_id=label_id,
        action="correct",
        reviewer_id=reviewer_id,
        value=["powertrain", "engine"],
        ai_value="powertrain",
        taxonomy_version_id=version["id"],
    )
    stored = result["field_review"]["value_json"]
    _assert(stored == ["powertrain", "engine"], f"stored path {stored}")
    print("OK accept parent+child correct")

    clip2 = f"sha256:enum_tree_leaf_{suffix}"
    run2 = str(uuid.uuid4())
    create_review(
        clip2,
        run2,
        labels_json={label_id: "road"},
        taxonomy_version_id=version["id"],
        review_status="pending_review",
    )
    leaf = apply_field_review(
        clip_id=clip2,
        run_id=run2,
        label_id=label_id,
        action="confirm",
        reviewer_id=reviewer_id,
        ai_value="road",
        taxonomy_version_id=version["id"],
    )
    _assert(leaf["field_review"]["value_json"] == "road", "leaf confirm stored")
    print("OK accept leaf confirm")

    clip3 = f"sha256:enum_tree_unc_{suffix}"
    run3 = str(uuid.uuid4())
    create_review(
        clip3,
        run3,
        labels_json={label_id: "powertrain"},
        taxonomy_version_id=version["id"],
        review_status="pending_review",
    )
    unc = apply_field_review(
        clip_id=clip3,
        run_id=run3,
        label_id=label_id,
        action="uncertain",
        reviewer_id=reviewer_id,
        ai_value="powertrain",
        taxonomy_version_id=version["id"],
    )
    _assert(unc["field_review"]["human_doubtful"] is True, "uncertain allowed")
    print("OK uncertain skips cascade")


def main() -> None:
    test_inspect_helpers()
    test_apply_field_review_enforces()
    print("OK review enum_tree completeness")


if __name__ == "__main__":
    main()
