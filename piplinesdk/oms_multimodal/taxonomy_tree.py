"""Nested enum_tree taxonomy: depth crop + output-mode normalization."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

TreeOutputMode = str  # leaf | path | ancestors


@dataclass
class LabelingTaxonomyOptions:
    """Controls taxonomy depth crop and tree value output shape for labeling."""

    depth: int = 0  # 0 / unset = no crop (full tree); N>=1 keep nodes with depth <= N
    depth_by_dim: dict[str, int] = field(default_factory=dict)
    output_mode: TreeOutputMode = "path"


def parse_depth_by_dim(raw: str | None) -> dict[str, int]:
    """Parse ``L1.3=2,L1.1=1`` or JSON ``{\"L1.3\": 2}``."""
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("LABEL_TAXONOMY_DEPTH_BY_DIM JSON must be an object")
        return {str(k): int(v) for k, v in data.items()}
    out: dict[str, int] = {}
    for part in re.split(r"[,;\s]+", text):
        part = part.strip()
        if not part:
            continue
        if "=" not in part and ":" not in part:
            raise ValueError(f"invalid depth-by-dim token: {part!r}")
        sep = "=" if "=" in part else ":"
        key, val = part.split(sep, 1)
        out[key.strip()] = int(val.strip())
    return out


def resolve_labeling_taxonomy_options(
    *,
    depth: int | None = None,
    depth_by_dim: dict[str, int] | str | None = None,
    output_mode: str | None = None,
) -> LabelingTaxonomyOptions:
    """Resolve options from explicit args or env vars."""
    if depth is None:
        raw = os.getenv("LABEL_TAXONOMY_DEPTH", "").strip()
        depth = int(raw) if raw else 0
    if depth_by_dim is None:
        depth_by_dim = parse_depth_by_dim(os.getenv("LABEL_TAXONOMY_DEPTH_BY_DIM"))
    elif isinstance(depth_by_dim, str):
        depth_by_dim = parse_depth_by_dim(depth_by_dim)
    if output_mode is None:
        output_mode = os.getenv("LABEL_TREE_OUTPUT", "path").strip().lower() or "path"
    mode = str(output_mode).strip().lower()
    if mode not in {"leaf", "path", "ancestors"}:
        mode = "path"
    return LabelingTaxonomyOptions(
        depth=max(0, int(depth)),
        depth_by_dim=dict(depth_by_dim or {}),
        output_mode=mode,
    )


def resolve_label_depth(
    level_code: str | None,
    *,
    global_depth: int,
    depth_by_dim: dict[str, int],
) -> int:
    """Return max depth for a label (0 = unlimited). Dim override wins when present."""
    code = (level_code or "").strip()
    if code and code in depth_by_dim:
        return max(0, int(depth_by_dim[code]))
    return max(0, int(global_depth))


def _as_tree_nodes(values: Any) -> list[dict[str, Any]]:
    """Normalize flat string lists or node dicts into ``{id, children?}`` nodes."""
    if not isinstance(values, list):
        return []
    nodes: list[dict[str, Any]] = []
    for item in values:
        if isinstance(item, str):
            nodes.append({"id": item})
        elif isinstance(item, dict) and item.get("id") is not None:
            node = {"id": str(item["id"])}
            children = item.get("children")
            if children:
                node["children"] = _as_tree_nodes(children)
            # preserve extra keys (e.g. label) except we rebuild children
            for k, v in item.items():
                if k not in {"id", "children"}:
                    node[k] = v
            nodes.append(node)
    return nodes


def is_enum_tree_schema(schema: dict[str, Any] | None) -> bool:
    if not schema or not isinstance(schema, dict):
        return False
    if schema.get("type") == "enum_tree":
        return True
    # Heuristic: enum with object children
    if schema.get("type") == "enum":
        values = schema.get("values")
        if isinstance(values, list) and any(isinstance(v, dict) and "children" in v for v in values):
            return True
    return False


def iter_tree_ids(nodes: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for node in nodes:
        nid = str(node.get("id") or "")
        if nid:
            out.append(nid)
        kids = node.get("children")
        if isinstance(kids, list):
            out.extend(iter_tree_ids(_as_tree_nodes(kids)))
    return out


def crop_tree_nodes(nodes: list[dict[str, Any]], max_depth: int, *, depth: int = 1) -> list[dict[str, Any]]:
    """Keep nodes with depth <= max_depth. max_depth<=0 means unlimited."""
    if max_depth <= 0:
        return deepcopy(nodes)
    cropped: list[dict[str, Any]] = []
    for node in nodes:
        item = {k: v for k, v in node.items() if k != "children"}
        item["id"] = str(node["id"])
        if depth < max_depth:
            kids = node.get("children")
            if kids:
                item["children"] = crop_tree_nodes(_as_tree_nodes(kids), max_depth, depth=depth + 1)
        cropped.append(item)
    return cropped


def crop_value_schema(schema: dict[str, Any] | None, max_depth: int) -> dict[str, Any] | None:
    if not schema or not isinstance(schema, dict):
        return schema
    out = deepcopy(schema)
    if not is_enum_tree_schema(out):
        return out
    nodes = _as_tree_nodes(out.get("values"))
    out["type"] = "enum_tree"
    out["values"] = crop_tree_nodes(nodes, max_depth)
    return out


def crop_taxonomy(
    taxonomy: dict[str, Any],
    *,
    options: LabelingTaxonomyOptions | None = None,
) -> dict[str, Any]:
    """Return a copy of taxonomy with enum_tree values cropped per depth options."""
    opts = options or resolve_labeling_taxonomy_options()
    labels_out: list[dict[str, Any]] = []
    for item in taxonomy.get("labels") or []:
        row = deepcopy(item)
        schema = row.get("value_schema")
        if isinstance(schema, dict) and is_enum_tree_schema(schema):
            max_d = resolve_label_depth(
                row.get("level_code"),
                global_depth=opts.depth,
                depth_by_dim=opts.depth_by_dim,
            )
            row["value_schema"] = crop_value_schema(schema, max_d)
        labels_out.append(row)
    return {**taxonomy, "labels": labels_out}


def crop_taxonomy_for_labeling(
    taxonomy: dict[str, Any],
    *,
    options: LabelingTaxonomyOptions | None = None,
) -> tuple[dict[str, Any], LabelingTaxonomyOptions]:
    opts = options or resolve_labeling_taxonomy_options()
    return crop_taxonomy(taxonomy, options=opts), opts


def format_enum_tree_for_prompt(schema: dict[str, Any], *, labels: dict[str, str] | None = None) -> str:
    """Human-readable nested values for Omni prompt."""
    label_map = dict(labels or schema.get("labels") or {})
    nodes = _as_tree_nodes(schema.get("values"))

    def _fmt(ns: list[dict[str, Any]], indent: int) -> list[str]:
        lines: list[str] = []
        pad = "  " * indent
        for node in ns:
            nid = str(node["id"])
            zh = label_map.get(nid) or nid
            lines.append(f"{pad}- {zh} ({nid})")
            kids = node.get("children")
            if kids:
                lines.extend(_fmt(_as_tree_nodes(kids), indent + 1))
        return lines

    return "\n".join(_fmt(nodes, 0))


def _node_index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for node in nodes:
        idx[str(node["id"])] = node
        kids = node.get("children")
        if kids:
            idx.update(_node_index(_as_tree_nodes(kids)))
    return idx


def _find_path_to_id(nodes: list[dict[str, Any]], target: str, prefix: list[str] | None = None) -> list[str] | None:
    prefix = prefix or []
    for node in nodes:
        nid = str(node["id"])
        cur = prefix + [nid]
        if nid == target:
            return cur
        kids = node.get("children")
        if kids:
            found = _find_path_to_id(_as_tree_nodes(kids), target, cur)
            if found:
                return found
    return None


def _resolve_token(token: str, id_to_zh: dict[str, str], zh_to_id: dict[str, str], all_ids: set[str]) -> str | None:
    key = str(token).strip()
    if key in all_ids:
        return key
    if key in zh_to_id:
        return zh_to_id[key]
    # case-insensitive id
    low = key.lower()
    for nid in all_ids:
        if nid.lower() == low:
            return nid
    return None


def _validate_path(nodes: list[dict[str, Any]], path: list[str]) -> list[str] | None:
    if not path:
        return None
    cursor = nodes
    resolved: list[str] = []
    for i, step in enumerate(path):
        match = None
        for node in cursor:
            if str(node["id"]) == step:
                match = node
                break
        if match is None:
            return None
        resolved.append(step)
        kids = match.get("children")
        if i < len(path) - 1:
            if not kids:
                return None
            cursor = _as_tree_nodes(kids)
    return resolved


def format_tree_value(path: list[str], *, output_mode: TreeOutputMode) -> Any:
    if not path:
        return None
    if output_mode == "leaf":
        return path[-1]
    if output_mode == "ancestors":
        levels = {str(i + 1): path[i] for i in range(len(path))}
        return {"path": list(path), "leaf": path[-1], "levels": levels}
    return list(path)


def normalize_tree_value(
    schema: dict[str, Any] | None,
    raw: Any,
    *,
    output_mode: TreeOutputMode = "path",
) -> Any | None:
    """Map model output onto a valid path on the (already cropped) enum_tree.

    Accepts leaf id/zh, path list, slash string, or ancestors dict.
    Returns None if the value cannot be placed on the tree.
    """
    if raw is None or schema is None:
        return raw
    if not is_enum_tree_schema(schema):
        return raw

    nodes = _as_tree_nodes(schema.get("values"))
    labels = dict(schema.get("labels") or {})
    all_ids = set(iter_tree_ids(nodes))
    zh_to_id = {str(v): k for k, v in labels.items()}
    id_to_zh = {k: str(v) for k, v in labels.items()}

    path_tokens: list[str] = []
    if isinstance(raw, dict):
        if isinstance(raw.get("path"), list):
            path_tokens = [str(x) for x in raw["path"]]
        elif raw.get("leaf") is not None:
            path_tokens = [str(raw["leaf"])]
        elif isinstance(raw.get("levels"), dict):
            levels = raw["levels"]
            keys = sorted(levels.keys(), key=lambda k: int(k) if str(k).isdigit() else str(k))
            path_tokens = [str(levels[k]) for k in keys]
    elif isinstance(raw, list):
        path_tokens = [str(x) for x in raw]
    else:
        text = str(raw).strip()
        if "/" in text or "→" in text or "->" in text:
            text = text.replace("→", "/").replace("->", "/")
            path_tokens = [p.strip() for p in text.split("/") if p.strip()]
        else:
            path_tokens = [text]

    resolved: list[str] = []
    for tok in path_tokens:
        rid = _resolve_token(tok, id_to_zh, zh_to_id, all_ids)
        if rid is None:
            return None
        resolved.append(rid)

    # If single leaf token, expand to full path from root
    if len(resolved) == 1:
        full = _find_path_to_id(nodes, resolved[0])
        if not full:
            return None
        resolved = full
    else:
        valid = _validate_path(nodes, resolved)
        if valid is None:
            # try treating last as leaf
            full = _find_path_to_id(nodes, resolved[-1])
            if not full:
                return None
            resolved = full
        else:
            resolved = valid

    return format_tree_value(resolved, output_mode=output_mode)


def tree_output_mode_rule(output_mode: TreeOutputMode) -> str:
    if output_mode == "leaf":
        return (
            "嵌套枚举（enum_tree）的 value 只输出最深叶子英文 id（如 heavy_rain）；"
            "不得编造树上不存在的取值。"
        )
    if output_mode == "ancestors":
        return (
            '嵌套枚举（enum_tree）的 value 输出对象 '
            '{"path":["rain","heavy_rain"],"leaf":"heavy_rain","levels":{"1":"rain","2":"heavy_rain"}}；'
            "path 必须是树上从根到叶的合法路径。"
        )
    return (
        '嵌套枚举（enum_tree）的 value 输出英文 id 路径数组（如 ["rain","heavy_rain"]）；'
        "必须是树上从根到叶的合法路径。"
    )



# ---------------------------------------------------------------------------
# Scaffold：平台「创建标签树」时用 —— 只提供深度结构能力，不预设业务树内容
# ---------------------------------------------------------------------------


def enum_tree_node(node_id: str, *children: dict[str, Any] | str, **extra: Any) -> dict[str, Any]:
    """Build one tree node. Children may be node dicts or bare id strings."""
    nid = str(node_id).strip()
    if not nid:
        raise ValueError("enum_tree node id must be non-empty")
    node: dict[str, Any] = {"id": nid, **extra}
    child_nodes = [_coerce_scaffold_child(c) for c in children]
    if child_nodes:
        node["children"] = child_nodes
    return node


def _coerce_scaffold_child(child: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(child, str):
        return {"id": child}
    if isinstance(child, dict) and child.get("id") is not None:
        out = dict(child)
        out["id"] = str(out["id"])
        if out.get("children"):
            out["children"] = [_coerce_scaffold_child(c) for c in out["children"]]
        return out
    raise ValueError(f"invalid enum_tree child: {child!r}")


def make_enum_tree_schema(
    *roots: dict[str, Any] | str,
    labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Scaffold a value_schema with type enum_tree and depth-capable nodes."""
    values = [_coerce_scaffold_child(r) for r in roots]
    schema: dict[str, Any] = {"type": "enum_tree", "values": values}
    if labels:
        schema["labels"] = {str(k): str(v) for k, v in labels.items()}
    return schema


def tree_depth(schema: dict[str, Any] | None) -> int:
    """Max depth of an enum_tree (root level = 1). Flat / empty returns 0."""
    if not schema or not is_enum_tree_schema(schema):
        return 0

    def _depth(nodes: list[dict[str, Any]]) -> int:
        if not nodes:
            return 0
        best = 1
        for node in nodes:
            kids = node.get("children")
            if kids:
                best = max(best, 1 + _depth(_as_tree_nodes(kids)))
        return best

    return _depth(_as_tree_nodes(schema.get("values")))


def validate_enum_tree_schema(schema: dict[str, Any] | None) -> list[str]:
    """Return validation errors (empty list = ok). Enforces unique ids in the tree."""
    errors: list[str] = []
    if not schema or not isinstance(schema, dict):
        return ["schema must be a dict"]
    if schema.get("type") not in {"enum_tree", "enum"}:
        errors.append(f"unexpected type={schema.get('type')!r}; want enum_tree")
    if not is_enum_tree_schema(schema) and schema.get("type") != "enum_tree":
        if schema.get("type") == "enum":
            return []
        return errors or ["not an enum_tree schema"]
    nodes = _as_tree_nodes(schema.get("values"))
    if not nodes:
        errors.append("enum_tree values must be a non-empty list")
    seen: set[str] = set()

    def _walk(ns: list[dict[str, Any]], path: str) -> None:
        for node in ns:
            nid = str(node.get("id") or "").strip()
            if not nid:
                errors.append(f"empty id under {path or '/'}")
                continue
            if nid in seen:
                errors.append(f"duplicate id {nid!r}")
            seen.add(nid)
            kids = node.get("children")
            if kids is not None and not isinstance(kids, list):
                errors.append(f"children of {nid!r} must be a list")
            elif kids:
                _walk(_as_tree_nodes(kids), f"{path}/{nid}")

    _walk(nodes, "")
    return errors


def minimal_enum_tree_example() -> dict[str, Any]:
    """Tiny demo tree for docs/tests (not a product taxonomy)."""
    return make_enum_tree_schema(
        enum_tree_node("group_a", "a1", "a2"),
        enum_tree_node("group_b"),
        labels={"group_a": "组A", "a1": "A-1", "a2": "A-2", "group_b": "组B"},
    )
