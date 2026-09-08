"""Local DAG walk: execute_graph with op/label adapters (UI-DTYPE-DAG-CANVAS)."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from hmi.platform.file_kinds import TEXT_EXTS
from hmi.platform.graph_expr import eval_condition
from hmi.platform.operators import apply_label_tree_assignments, extract_json_path, normalize_path_keys
from hmi.platform.recipe_graph import validate_graph

Adapter = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]


def _default_source(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    src = dict(ctx.get("source") or {})
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    kinds = params.get("kinds") if isinstance(params.get("kinds"), list) else []
    if not src.get("kind"):
        if kinds:
            src["kind"] = kinds[0]
        elif params.get("kind"):
            src["kind"] = params.get("kind")
    if not src.get("slot_id"):
        src["slot_id"] = params.get("slot_id") or node.get("key")
    return {"source": src}


def _default_if(_node: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    return {}


def _default_review(_node: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
    return {"review_status": "pending_review"}


def _default_export(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    raw = params.get("exported_product_ids")
    chosen: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            pid = str(item or "").strip()
            if pid and pid not in chosen:
                chosen.append(pid)
    existing = ctx.get("exported_product_ids")
    if not isinstance(existing, list):
        return {"exported_product_ids": chosen}
    merged = [str(x).strip() for x in existing if str(x).strip()]
    for pid in chosen:
        if pid not in merged:
            merged.append(pid)
    return {"exported_product_ids": merged}


def _bind_payload(bind: Any, ctx: dict[str, Any]) -> Any:
    item = bind
    if isinstance(item, list) and item:
        item = item[0]
    if not isinstance(item, dict):
        return None
    if str(item.get("kind") or "") != "upstream":
        return None
    step = str(item.get("step_key") or "").strip()
    if not step:
        return None
    bag = ctx.get(step)
    if isinstance(bag, dict) and "value" in bag:
        return bag.get("value")
    if bag is not None:
        return bag
    je = ctx.get("json_extract")
    if isinstance(je, dict) and step in je:
        return je.get(step)
    return None


def _json_input_from_ctx(node: dict[str, Any], ctx: dict[str, Any]) -> Any:
    bindings = node.get("bindings") if isinstance(node.get("bindings"), dict) else {}
    from_bind = _bind_payload(bindings.get("in"), ctx)
    if from_bind is not None:
        return from_bind
    for key in ("json", "structured_json", "payload", "json_extract"):
        if key in ctx:
            bag = ctx[key]
            if key == "json_extract" and isinstance(bag, dict) and "value" in bag:
                return bag.get("value")
            return bag
    return ctx


_TEXT_SCHEMA_IDS = frozenset({"generic_json", "generic_text"})
_SKIP_TEXT_NAMES = frozenset({"source_manifest.json", "structured.json"})


def _existing_file(raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    return path if path.is_file() else None


def _load_source_manifest(ctx: dict[str, Any]) -> tuple[dict[str, Any], Path | None]:
    raw = str(ctx.get("source_manifest_path") or "").strip()
    path: Path | None = Path(raw) if raw else None
    if path is None or not path.is_file():
        run = Path(str(ctx.get("run_dir") or "").strip())
        candidate = run / "source_manifest.json"
        path = candidate if candidate.is_file() else None
    if path is None:
        return {}, None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, path
    return (payload if isinstance(payload, dict) else {}), path


def _resolve_rel_file(raw: Any, base: Path | None) -> Path | None:
    found = _existing_file(raw)
    if found is not None:
        return found
    if not isinstance(raw, str) or not raw.strip() or base is None:
        return None
    candidate = base / raw
    return candidate if candidate.is_file() else None


def _scan_text_file(folder: Path | None) -> Path | None:
    if folder is None or not folder.is_dir():
        return None
    hits: list[Path] = []
    for ext in TEXT_EXTS:
        for path in folder.glob(f"*{ext}"):
            if path.is_file() and path.name not in _SKIP_TEXT_NAMES:
                hits.append(path)
    if not hits:
        return None
    hits.sort(key=lambda p: (0 if p.suffix.lower() == ".json" else 1, p.name.lower()))
    return hits[0]


def _text_file_from_ctx(ctx: dict[str, Any]) -> Path | None:
    source = ctx.get("source") if isinstance(ctx.get("source"), dict) else {}
    for raw in (
        ctx.get("text_path"),
        ctx.get("text"),
        source.get("path"),
        source.get("text_path"),
        source.get("text"),
    ):
        found = _existing_file(raw)
        if found is not None:
            return found
    man, man_path = _load_source_manifest(ctx)
    base = man_path.parent if man_path is not None else None
    for key in ("text", "text_path"):
        found = _resolve_rel_file(man.get(key), base)
        if found is not None:
            return found
    run_dir = Path(str(ctx.get("run_dir") or "").strip()) if str(ctx.get("run_dir") or "").strip() else None
    return _scan_text_file(base) or _scan_text_file(run_dir)


def _resolve_text_schema_id(node: dict[str, Any], ctx: dict[str, Any], path: Path | None) -> str:
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    sid = str(params.get("schema_id") or "").strip()
    if not sid:
        sid = str(ctx.get("text_schema_id") or "").strip()
    if not sid:
        man, _ = _load_source_manifest(ctx)
        sid = str(man.get("text_schema_id") or "").strip()
    if not sid and path is not None:
        sid = "generic_json" if path.suffix.lower() == ".json" else "generic_text"
    return sid or "generic_json"


def _parse_text_schema(text: str, schema_id: str) -> Any:
    if schema_id not in _TEXT_SCHEMA_IDS:
        raise RuntimeError(f"text_to_json: 未知 schema_id: {schema_id}")
    if schema_id == "generic_text":
        return {"raw": text}
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"text_to_json: JSON 解析失败: {exc}") from exc


def _adapt_text_to_json(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    path = _text_file_from_ctx(ctx)
    if path is None:
        raise RuntimeError("text_to_json: 找不到文本文件")
    schema_id = _resolve_text_schema_id(node, ctx, path)
    obj = _parse_text_schema(path.read_text(encoding="utf-8-sig"), schema_id)
    run_raw = str(ctx.get("run_dir") or "").strip()
    if run_raw:
        out_path = Path(run_raw) / "structured.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    node_key = str(node.get("key") or "").strip()
    patch: dict[str, Any] = {"structured_json": obj}
    if node_key:
        patch[node_key] = {"value": obj}
    return patch


def _adapt_json_extract(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    keys = normalize_path_keys(params.get("path_keys"))
    value = extract_json_path(_json_input_from_ctx(node, ctx), keys)
    node_key = str(node.get("key") or "").strip()
    je = dict(ctx.get("json_extract") or {}) if isinstance(ctx.get("json_extract"), dict) else {}
    je["value"] = value
    if node_key:
        je[node_key] = value
    patch: dict[str, Any] = {"json_extract": je}
    if node_key:
        patch[node_key] = {"value": value}
    return patch


def _adapt_label_tree_input(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    bindings = node.get("bindings") if isinstance(node.get("bindings"), dict) else {}

    def resolve(bind: Any) -> Any:
        from_row = _bind_payload(bind, ctx)
        if from_row is not None:
            return from_row
        return _bind_payload(bindings.get("in"), ctx)

    labels = apply_label_tree_assignments(params.get("assignments"), resolve_upstream=resolve)
    incoming = dict(labels.get("values") or {})
    existing = ctx.get("labels")
    if isinstance(existing, dict) and isinstance(existing.get("values"), dict):
        out_labels = {**existing, "values": {**existing["values"], **incoming}}
    else:
        out_labels = labels
    return {"labels": out_labels, "labels_tree": out_labels}


_DEFAULT_ADAPTERS: dict[str, Adapter] = {
    "source": _default_source,
    "if": _default_if,
    "review": _default_review,
    "export": _default_export,
}

_BUILTIN_OP_ADAPTERS: dict[str, Adapter] = {
    "json_extract": _adapt_json_extract,
    "label_tree_input": _adapt_label_tree_input,
    "text_to_json": _adapt_text_to_json,
}


def _resolve_adapter(node: dict[str, Any], adapters: dict[str, Adapter]) -> Adapter:
    ntype = str(node.get("type") or "")
    op_id = str(node.get("op_id") or ntype)
    if ntype in ("op", "label"):
        if op_id in adapters:
            return adapters[op_id]
        builtin = _BUILTIN_OP_ADAPTERS.get(op_id)
        if builtin is not None:
            return builtin
        raise RuntimeError(f"missing adapter for op_id={op_id}")
    if op_id in adapters:
        return adapters[op_id]
    default = _DEFAULT_ADAPTERS.get(ntype)
    if default is None:
        raise RuntimeError(f"missing adapter for op_id={op_id}")
    return default


def _merge_patch(ctx: dict[str, Any], patch: Any) -> None:
    if isinstance(patch, dict) and patch is not ctx:
        ctx.update(patch)


def _ancestor_set(until_key: str | None, incoming: dict[str, list[dict[str, Any]]]) -> set[str] | None:
    if not until_key:
        return None
    seen = {until_key}
    stack = [until_key]
    while stack:
        key = stack.pop()
        for edge in incoming.get(key, []):
            src = str(edge.get("source") or "")
            if src and src not in seen:
                seen.add(src)
                stack.append(src)
    return seen


def execute_graph(
    graph: dict[str, Any],
    *,
    ctx0: dict[str, Any],
    adapters: dict[str, Adapter],
    until_key: str | None = None,
    require_label: bool = True,
    include_ai: bool = True,
    enforce_io: bool = True,
) -> dict[str, Any]:
    from hmi.platform.io_contract import AI_OP_IDS, assert_inputs_ok, assert_produces_present
    from hmi.platform.recipe_graph import is_labels_sink, validate_graph

    g = validate_graph(graph)
    ctx: dict[str, Any] = deepcopy(ctx0) if ctx0 else {}
    ctx["graph"] = g
    ctx["_enforce_io"] = bool(enforce_io)
    adapters = dict(adapters or {})
    by_key = {n["key"]: n for n in g["nodes"]}
    outgoing: dict[str, list[dict[str, Any]]] = {k: [] for k in by_key}
    incoming: dict[str, list[dict[str, Any]]] = {k: [] for k in by_key}
    for edge in g["edges"]:
        outgoing[str(edge["source"])].append(edge)
        incoming[str(edge["target"])].append(edge)
    stop_key = str(until_key).strip() if until_key else ""
    allowed = _ancestor_set(stop_key or None, incoming)

    status: dict[str, str] = {}
    run: list[dict[str, str]] = []
    taken_edges: set[str] = set()
    work: deque[str] = deque(
        n["key"] for n in g["nodes"] if n["type"] == "source" and (allowed is None or n["key"] in allowed)
    )

    def enqueue_targets(key: str, *, take_all: bool, if_port: str | None) -> None:
        if stop_key and key == stop_key:
            return
        for edge in outgoing.get(key, []):
            port = str(edge.get("source_port") or "out")
            tgt = str(edge.get("target") or "")
            if allowed is not None and tgt not in allowed:
                continue
            if if_port is not None:
                if port == if_port:
                    taken_edges.add(str(edge["id"]))
            elif take_all:
                taken_edges.add(str(edge["id"]))
            work.append(tgt)

    while work:
        key = work.popleft()
        if key in status or key not in by_key:
            continue
        if allowed is not None and key not in allowed:
            continue
        node = by_key[key]
        in_edges = incoming.get(key, [])
        taken_in = [e for e in in_edges if str(e["id"]) in taken_edges]
        preds = [str(e["source"]) for e in in_edges]
        preds_done = all(p in status for p in preds)

        if in_edges and not taken_in:
            if not preds_done:
                continue
            status[key] = "skipped"
            run.append({"key": key, "status": "skipped"})
            enqueue_targets(key, take_all=False, if_port=None)
            continue

        ntype = str(node.get("type") or "")
        op_id = str(node.get("op_id") or ntype)
        try:
            if enforce_io and ntype in {"op", "label"}:
                assert_inputs_ok(node, g)
                if not include_ai and op_id in AI_OP_IDS:
                    status[key] = "checked"
                    run.append({"key": key, "status": "checked"})
                    enqueue_targets(key, take_all=True, if_port=None)
                    continue
            adapter = _resolve_adapter(node, adapters)
            _merge_patch(ctx, adapter(node, ctx))
            if enforce_io and ntype in {"op", "label"}:
                assert_produces_present(node, ctx)
        except Exception as exc:
            status[key] = "failed"
            run.append({"key": key, "status": "failed", "error": str(exc)})
            raise
        status[key] = "success"
        run.append({"key": key, "status": "success"})
        if node["type"] == "if":
            port = "then" if eval_condition(node.get("condition"), ctx) else "else"
            enqueue_targets(key, take_all=False, if_port=port)
        else:
            enqueue_targets(key, take_all=True, if_port=None)

    if require_label:
        sinks = [n for n in g["nodes"] if is_labels_sink(n)]
        if not any(status.get(n["key"]) == "success" for n in sinks):
            raise RuntimeError("标签树未写入")

    return {"ctx": ctx, "run": run}


def assert_runnable_locally(graph: dict[str, Any]) -> None:
    from hmi.platform.capability_kernel import assert_plugins_registered

    assert_plugins_registered(graph)


def ctx0_from_source_nodes(graph: dict[str, Any], ctx0: dict[str, Any] | None) -> dict[str, Any]:
    ctx: dict[str, Any] = deepcopy(ctx0) if ctx0 else {}
    source = dict(ctx.get("source") or {})
    g = validate_graph(graph)
    for node in g["nodes"]:
        if node["type"] != "source":
            continue
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        kinds = params.get("kinds") if isinstance(params.get("kinds"), list) else []
        if not source.get("kind"):
            if kinds:
                source["kind"] = kinds[0]
            elif params.get("kind"):
                source["kind"] = params.get("kind")
        if not source.get("slot_id"):
            source["slot_id"] = params.get("slot_id") or node.get("key")
        break
    if source:
        ctx["source"] = source
    return ctx


def preview_taken_op_ids(graph: dict[str, Any], ctx0: dict[str, Any]) -> list[str]:
    g = validate_graph(graph)
    merged = ctx0_from_source_nodes(g, ctx0)

    def _noop(_node: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        return {}

    adapters: dict[str, Adapter] = {}
    for node in g["nodes"]:
        if node["type"] not in {"op", "label"}:
            continue
        op_id = str(node.get("op_id") or node["type"])
        adapters[op_id] = _noop
    out = execute_graph(g, ctx0=merged, adapters=adapters, require_label=False, enforce_io=False)
    by_key = {n["key"]: n for n in g["nodes"]}
    taken: list[str] = []
    for row in out["run"]:
        if row.get("status") != "success":
            continue
        node = by_key.get(row.get("key") or "")
        if not node:
            continue
        taken.append(str(node.get("op_id") or node["type"]))
    return taken


def apply_graph_to_run_request(
    graph: dict[str, Any],
    recipe: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    from hmi.platform.run_bind import overlay_run_request

    overlay = overlay_run_request(recipe, settings)
    taken = set(preview_taken_op_ids(graph, ctx0_from_source_nodes(graph, {})))
    overlay["need_label"] = "label" in taken
    overlay["need_embed"] = "embed" in taken
    overlay["bbox_enabled"] = bool(overlay.get("bbox_enabled") or ("detect_bbox" in taken))
    return overlay


__all__ = [
    "Adapter",
    "apply_graph_to_run_request",
    "assert_runnable_locally",
    "ctx0_from_source_nodes",
    "execute_graph",
    "preview_taken_op_ids",
]
