"""Compile a Sample's source kinds against a DataType recipe."""

from __future__ import annotations

from typing import Any

from hmi.platform.recipe import validate_recipe


def preflight(recipe: dict[str, Any], source_kinds: list[str]) -> dict[str, Any]:
    """Check required inputs and list operators that would run.

    ``ok`` is False when no ``require_any_kinds`` group is satisfied.
    Missing kinds are listed for the first unsatisfied group (or all groups).
    """
    rec = validate_recipe(recipe)
    present = {str(k).strip().lower() for k in source_kinds if k}
    groups: list[list[str]] = rec["require_any_kinds"]
    matched: list[str] | None = None
    missing_by_group: list[list[str]] = []
    for group in groups:
        miss = [k for k in group if k not in present]
        if not miss:
            matched = list(group)
            break
        missing_by_group.append(miss)
    ok = matched is not None
    missing = [] if ok else sorted({k for g in missing_by_group for k in g})

    ops: list[str] = []
    for step in rec["preprocess"]:
        when = step.get("when_kind")
        if when is None:
            if rec["bbox"]["enabled"] or step["op_id"] != "detect_bbox":
                if step["op_id"] == "detect_bbox" and not rec["bbox"]["enabled"]:
                    continue
                ops.append(step["op_id"])
            continue
        if when in present:
            ops.append(step["op_id"])
        elif step.get("required"):
            ok = False
            if when not in missing:
                missing.append(when)

    # bbox operator when enabled even if not listed with when_kind
    if rec["bbox"]["enabled"] and "detect_bbox" not in ops:
        if present & {"image", "video", "rosbag"}:
            ops.append("detect_bbox")
        elif ok:
            ok = False
            missing = sorted(set(missing) | {"image"})

    if rec["stages"]["label"]["enabled"]:
        ops.append("label")
    if rec["stages"]["embed"]["enabled"]:
        ops.append("embed")

    return {
        "ok": ok,
        "missing": missing,
        "matched_group": matched,
        "ops": ops,
        "data_type_id": rec["id"],
        "taxonomy_id": rec["taxonomy_id"],
    }
