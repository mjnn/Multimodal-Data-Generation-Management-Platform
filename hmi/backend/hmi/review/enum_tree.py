"""Nested enum_tree completeness for field review (parent + every required child)."""

from __future__ import annotations

from typing import Any


def coerce_enum_tree_nodes(values: Any) -> list[dict[str, Any]]:
    if not isinstance(values, list):
        return []
    out: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, str):
            nid = item.strip()
            if nid:
                out.append({"id": nid})
            continue
        if not isinstance(item, dict):
            continue
        nid = str(item.get("id") or "").strip()
        if not nid:
            continue
        node: dict[str, Any] = {"id": nid}
        if item.get("name") is not None:
            node["name"] = str(item["name"])
        kids = item.get("children")
        if isinstance(kids, list) and kids:
            node["children"] = coerce_enum_tree_nodes(kids)
        out.append(node)
    return out


def is_enum_tree_schema(schema: Any, dtype: str | None = None) -> bool:
    if (dtype or "").strip().lower() == "enum_tree":
        return True
    if not isinstance(schema, dict):
        return False
    if str(schema.get("type") or "").strip().lower() == "enum_tree":
        return True
    raw = schema.get("values")
    if not isinstance(raw, list) or not raw:
        return False
    return any(isinstance(v, dict) and "id" in v for v in raw)


def is_nested_enum_schema(schema: Any, dtype: str | None = None) -> bool:
    """True when at least one option has children (cascade / parent+child)."""
    if not is_enum_tree_schema(schema, dtype):
        return False
    values = schema.get("values") if isinstance(schema, dict) else None
    return _has_nested_children(coerce_enum_tree_nodes(values))


def _has_nested_children(nodes: list[dict[str, Any]]) -> bool:
    for node in nodes:
        kids = node.get("children")
        if isinstance(kids, list) and kids:
            return True
    return False


def parse_enum_path(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        text = str(value).strip()
        return [text] if text else []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if "/" in text:
            return [part.strip() for part in text.split("/") if part.strip()]
        return [text]
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            part = str(item).strip()
            if part:
                out.append(part)
        return out
    if isinstance(value, dict):
        if "path" in value:
            return parse_enum_path(value.get("path"))
        if "value" in value:
            return parse_enum_path(value.get("value"))
    return []


def _find_child(nodes: list[dict[str, Any]], nid: str) -> dict[str, Any] | None:
    for node in nodes:
        if str(node.get("id") or "") == nid:
            return node
    return None


def _walk_find(nodes: list[dict[str, Any]], nid: str, trail: list[str]) -> list[str] | None:
    for node in nodes:
        current = str(node.get("id") or "")
        next_trail = [*trail, current]
        if current == nid:
            return next_trail
        kids = node.get("children")
        if isinstance(kids, list) and kids:
            found = _walk_find(kids, nid, next_trail)
            if found is not None:
                return found
    return None


def resolve_enum_path(nodes: list[dict[str, Any]], value: Any) -> list[str] | None:
    """Resolve a stored value to a root-to-node path, or None if invalid."""
    raw = parse_enum_path(value)
    if not raw:
        return []
    cursor = nodes
    walked: list[str] = []
    for idx, segment in enumerate(raw):
        match = _find_child(cursor, segment)
        if match is None:
            if idx == 0 and len(raw) == 1:
                found = _walk_find(nodes, segment, [])
                return found
            return None
        walked.append(segment)
        kids = match.get("children")
        cursor = kids if isinstance(kids, list) else []
    return walked


def _node_at_path(nodes: list[dict[str, Any]], path: list[str]) -> dict[str, Any] | None:
    cursor = nodes
    current: dict[str, Any] | None = None
    for segment in path:
        current = _find_child(cursor, segment)
        if current is None:
            return None
        kids = current.get("children")
        cursor = kids if isinstance(kids, list) else []
    return current


def inspect_enum_tree_value(schema: Any, value: Any, *, dtype: str | None = None) -> dict[str, Any]:
    """Inspect cascade completeness.

    Returns dict: complete, nested, path, missing_level (1-based or None), message.
    Non-nested schemas are always complete (passthrough).
    """
    if not is_nested_enum_schema(schema, dtype):
        return {
            "complete": True,
            "nested": False,
            "path": parse_enum_path(value),
            "missing_level": None,
            "message": None,
        }

    values = schema.get("values") if isinstance(schema, dict) else None
    nodes = coerce_enum_tree_nodes(values)
    raw = parse_enum_path(value)
    if not raw:
        return {
            "complete": False,
            "nested": True,
            "path": [],
            "missing_level": 1,
            "message": "嵌套枚举未完成：值为空，每一级都需要取值",
        }

    path = resolve_enum_path(nodes, value)
    if path is None:
        return {
            "complete": False,
            "nested": True,
            "path": raw,
            "missing_level": None,
            "message": f"嵌套枚举取值无效：{'/'.join(raw)} 不在选项中",
        }

    terminal = _node_at_path(nodes, path)
    kids = terminal.get("children") if terminal else None
    if isinstance(kids, list) and kids:
        parent = path[-1]
        return {
            "complete": False,
            "nested": True,
            "path": path,
            "missing_level": len(path) + 1,
            "message": f"嵌套枚举未完成：已选 {parent}，还需选择第 {len(path) + 1} 级子值",
        }

    return {
        "complete": True,
        "nested": True,
        "path": path,
        "missing_level": None,
        "message": None,
    }


def normalize_enum_tree_value(schema: Any, value: Any, *, dtype: str | None = None) -> Any:
    """If complete nested path has 2+ levels, store the full path list (parent+child)."""
    info = inspect_enum_tree_value(schema, value, dtype=dtype)
    if not info["complete"] or not info["nested"]:
        return value
    path = info["path"]
    if len(path) > 1:
        return path
    return path[0] if path else value


def assert_enum_tree_review_complete(schema: Any, value: Any, *, dtype: str | None = None) -> Any:
    """Raise ValueError when a nested enum value is incomplete; return normalized value."""
    info = inspect_enum_tree_value(schema, value, dtype=dtype)
    if not info["complete"]:
        raise ValueError(info["message"] or "嵌套枚举未完成")
    return normalize_enum_tree_value(schema, value, dtype=dtype)


def find_incomplete_enum_tree_labels(
    labels_json: dict[str, Any],
    nodes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return incomplete nested-enum label inspections (for clip-level mark reviewed)."""
    out: list[dict[str, Any]] = []
    for node in nodes:
        label_id = str(node.get("label_id") or "").strip()
        if not label_id:
            continue
        schema = node.get("value_schema")
        dtype = node.get("dtype")
        if not is_nested_enum_schema(schema, dtype):
            continue
        info = inspect_enum_tree_value(schema, labels_json.get(label_id), dtype=dtype)
        if not info["complete"]:
            out.append({"label_id": label_id, **info})
    return out
