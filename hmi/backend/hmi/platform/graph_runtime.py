"""Local DAG walk: execute_graph with op/label adapters (UI-DTYPE-DAG-CANVAS)."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from hmi.platform.graph_expr import eval_condition
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


_DEFAULT_ADAPTERS: dict[str, Adapter] = {
    "source": _default_source,
    "if": _default_if,
    "review": _default_review,
    "export": _default_export,
}


def _resolve_adapter(node: dict[str, Any], adapters: dict[str, Adapter]) -> Adapter:
    ntype = str(node.get("type") or "")
    op_id = str(node.get("op_id") or ntype)
    if ntype in ("op", "label"):
        if op_id not in adapters:
            raise RuntimeError(f"missing adapter for op_id={op_id}")
        return adapters[op_id]
    if op_id in adapters:
        return adapters[op_id]
    default = _DEFAULT_ADAPTERS.get(ntype)
    if default is None:
        raise RuntimeError(f"missing adapter for op_id={op_id}")
    return default


def _merge_patch(ctx: dict[str, Any], patch: Any) -> None:
    if isinstance(patch, dict) and patch is not ctx:
        ctx.update(patch)


def execute_graph(
    graph: dict[str, Any],
    *,
    ctx0: dict[str, Any],
    adapters: dict[str, Adapter],
) -> dict[str, Any]:
    g = validate_graph(graph)
    ctx: dict[str, Any] = deepcopy(ctx0) if ctx0 else {}
    adapters = dict(adapters or {})
    by_key = {n["key"]: n for n in g["nodes"]}
    outgoing: dict[str, list[dict[str, Any]]] = {k: [] for k in by_key}
    incoming: dict[str, list[dict[str, Any]]] = {k: [] for k in by_key}
    for edge in g["edges"]:
        outgoing[str(edge["source"])].append(edge)
        incoming[str(edge["target"])].append(edge)

    status: dict[str, str] = {}
    run: list[dict[str, str]] = []
    taken_edges: set[str] = set()
    work: deque[str] = deque(n["key"] for n in g["nodes"] if n["type"] == "source")

    def enqueue_targets(key: str, *, take_all: bool, if_port: str | None) -> None:
        for edge in outgoing.get(key, []):
            port = str(edge.get("source_port") or "out")
            if if_port is not None:
                if port == if_port:
                    taken_edges.add(str(edge["id"]))
            elif take_all:
                taken_edges.add(str(edge["id"]))
            work.append(str(edge["target"]))

    while work:
        key = work.popleft()
        if key in status or key not in by_key:
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

        adapter = _resolve_adapter(node, adapters)
        _merge_patch(ctx, adapter(node, ctx))
        status[key] = "success"
        run.append({"key": key, "status": "success"})
        if node["type"] == "if":
            port = "then" if eval_condition(node.get("condition"), ctx) else "else"
            enqueue_targets(key, take_all=False, if_port=port)
        else:
            enqueue_targets(key, take_all=True, if_port=None)

    label_keys = [n["key"] for n in g["nodes"] if n["type"] == "label"]
    if not label_keys or status.get(label_keys[0]) != "success":
        raise RuntimeError("打标器未执行")

    return {"ctx": ctx, "run": run}


def assert_runnable_locally(graph: dict[str, Any]) -> None:
    g = validate_graph(graph)
    for n in g["nodes"]:
        if n["type"] != "if":
            continue
        for pred in (n.get("condition") or {}).get("all") or []:
            field = str(pred.get("field") or "")
            if field.startswith("asr.") or field.startswith("labels.") or field.startswith("label."):
                raise RuntimeError("本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支")


def _ctx0_from_source_nodes(graph: dict[str, Any], ctx0: dict[str, Any] | None) -> dict[str, Any]:
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
    merged = _ctx0_from_source_nodes(g, ctx0)

    def _noop(_node: dict[str, Any], _ctx: dict[str, Any]) -> dict[str, Any]:
        return {}

    adapters: dict[str, Adapter] = {}
    for node in g["nodes"]:
        if node["type"] not in {"op", "label"}:
            continue
        op_id = str(node.get("op_id") or node["type"])
        adapters[op_id] = _noop
    out = execute_graph(g, ctx0=merged, adapters=adapters)
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
    taken = set(preview_taken_op_ids(graph, _ctx0_from_source_nodes(graph, {})))
    overlay["need_label"] = "label" in taken
    overlay["need_embed"] = "embed" in taken
    overlay["bbox_enabled"] = bool(overlay.get("bbox_enabled") or ("detect_bbox" in taken))
    return overlay


__all__ = [
    "Adapter",
    "apply_graph_to_run_request",
    "assert_runnable_locally",
    "execute_graph",
    "preview_taken_op_ids",
]
