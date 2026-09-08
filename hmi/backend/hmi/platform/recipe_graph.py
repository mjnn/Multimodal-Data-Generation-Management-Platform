"""recipe.graph validate / hydrate / project (UI-DTYPE-DAG-CANVAS)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from hmi.platform.graph_expr import validate_condition
from hmi.platform.file_kinds import singleton_kind_groups
from hmi.platform.operators import CATALOG, display_op_title, is_generic_node_title
from hmi.platform.recipe_pipeline import is_legacy_hydrate_key, unique_catalog_key

NODE_TYPES = ("source", "op", "if", "label", "review", "export")
IF_OUT_PORTS = ("then", "else")


def _nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("nodes")
    if not isinstance(raw, list) or not raw:
        raise ValueError("graph.nodes must be a non-empty list")
    return raw


def _edges(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("edges")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("graph.edges must be a list")
    return raw


def _adj(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        src = str(e.get("source") or "")
        out.setdefault(src, []).append(e)
    return out


def _rev_adj(edges: list[dict[str, Any]]) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for e in edges:
        tgt = str(e.get("target") or "")
        src = str(e.get("source") or "")
        sp = str(e.get("source_port") or "out")
        out.setdefault(tgt, []).append((src, sp))
    return out


def _adj_without_node(keys: set[str], adj: dict[str, list[dict[str, Any]]], drop: str) -> dict[str, list[dict[str, Any]]]:
    return _adj_without_nodes(keys, adj, {drop})


def _adj_without_nodes(
    keys: set[str], adj: dict[str, list[dict[str, Any]]], drop: set[str]
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for src, es in adj.items():
        if src in drop:
            continue
        kept = [e for e in es if str(e.get("target") or "") not in drop]
        if kept:
            out[src] = kept
    return out


def _has_cycle(keys: set[str], adj: dict[str, list[dict[str, Any]]]) -> bool:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in keys}

    def dfs(u: str) -> bool:
        color[u] = GRAY
        for e in adj.get(u, []):
            v = str(e.get("target") or "")
            if v not in color:
                continue
            if color[v] == GRAY:
                return True
            if color[v] == WHITE and dfs(v):
                return True
        color[u] = BLACK
        return False

    return any(color[k] == WHITE and dfs(k) for k in keys)


def _reachable(start: str, adj: dict[str, list[dict[str, Any]]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for e in adj.get(u, []):
            v = str(e.get("target") or "")
            if v and v not in seen:
                seen.add(v)
                stack.append(v)
    return seen


def _reaches_label(start: str, label_key: str, adj: dict[str, list[dict[str, Any]]]) -> bool:
    return label_key in _reachable(start, adj)


def is_labels_sink(node: dict[str, Any] | None) -> bool:
    """AI打标器 or 标签树输入 both write labels_tree."""
    if not isinstance(node, dict):
        return False
    ntype = str(node.get("type") or "")
    op_id = str(node.get("op_id") or "")
    return ntype == "label" or op_id == "label_tree_input"


def _incoming_if_arm(
    source: str,
    by_key: dict[str, dict[str, Any]],
    rev_adj: dict[str, list[tuple[str, str]]],
) -> tuple[str, str] | None:
    """Nearest enclosing if-arm (if_key, then|else) for data from source, or None."""
    if by_key[source]["type"] == "source":
        return None
    seen = {source}
    stack = [source]
    while stack:
        u = stack.pop()
        for pred, port in rev_adj.get(u, []):
            if pred in seen:
                continue
            seen.add(pred)
            if by_key[pred]["type"] == "if":
                if port in IF_OUT_PORTS:
                    return (pred, port)
                continue
            if by_key[pred]["type"] == "source":
                return None
            stack.append(pred)
    return None


def _check_parallel_joins(
    by_key: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
    rev_adj: dict[str, list[tuple[str, str]]],
) -> None:
    incoming: dict[str, list[dict[str, Any]]] = {}
    for e in edges:
        tgt = str(e.get("target") or "")
        incoming.setdefault(tgt, []).append(e)
    for _tgt, es in incoming.items():
        non_src = [e for e in es if by_key[str(e.get("source") or "")]["type"] != "source"]
        if_edges = [e for e in non_src if by_key[str(e.get("source") or "")]["type"] == "if"]
        compute = [e for e in non_src if by_key[str(e.get("source") or "")]["type"] != "if"]
        compute_src = {str(e.get("source") or "") for e in compute}
        # Multiple output ports from the same producer (frames + .wav → label) is fan-in, not a join.
        if not if_edges and len(compute_src) <= 1:
            continue
        arms: list[tuple[str, str] | None] = []
        for e in es:
            src = str(e.get("source") or "")
            if by_key[src]["type"] == "source":
                continue
            if by_key[src]["type"] == "if":
                port = str(e.get("source_port") or "")
                if port not in IF_OUT_PORTS:
                    continue
                arms.append((src, port))
                continue
            arms.append(_incoming_if_arm(src, by_key, rev_adj))
        if len(arms) < 2:
            continue
        if all(a is None for a in arms):
            raise ValueError("禁止并行 join：多条计算分支汇入同一节点")
        if any(a is None for a in arms):
            raise ValueError("禁止并行 join：计算分支与无条件分支汇入同一节点")
        by_if: dict[str, list[str]] = {}
        for arm in arms:
            assert arm is not None
            by_if.setdefault(arm[0], []).append(arm[1])
        if len(by_if) != 1:
            raise ValueError("禁止并行 join：不同 if 分支汇入同一节点")
        if_key, ports = next(iter(by_if.items()))
        if len(ports) != 2 or set(ports) != set(IF_OUT_PORTS):
            raise ValueError(f"禁止并行 join：if 节点 {if_key!r} 的非互斥分支汇入同一节点")


def _reachable_without(label_key: str, start: str, adj: dict[str, list[dict[str, Any]]]) -> set[str]:
    seen = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        for e in adj.get(u, []):
            v = str(e.get("target") or "")
            if not v or v == label_key or v in seen:
                continue
            seen.add(v)
            stack.append(v)
    return seen


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(graph, dict):
        raise ValueError("graph must be an object")
    out = deepcopy(graph)
    nodes = _nodes(out)
    edges = _edges(out)
    by_key: dict[str, dict[str, Any]] = {}
    ai_labels: list[str] = []
    sinks: list[str] = []
    norm_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("graph node must be an object")
        key = str(node.get("key") or "").strip()
        ntype = str(node.get("type") or "").strip()
        if not key:
            raise ValueError("graph node.key is required")
        if ntype not in NODE_TYPES:
            raise ValueError(f"unknown graph node type={ntype!r}")
        if key in by_key:
            raise ValueError(f"duplicate graph node key={key!r}")
        pos = node.get("position") if isinstance(node.get("position"), dict) else {}
        item = {
            "key": key,
            "type": ntype,
            "op_id": str(node.get("op_id") or ("source" if ntype == "source" else ntype)).strip(),
            "title": str(node.get("title") or key).strip() or key,
            "params": dict(node.get("params") or {}) if isinstance(node.get("params"), dict) else {},
            "position": {
                "x": float(pos.get("x") or 0),
                "y": float(pos.get("y") or 0),
            },
        }
        bindings = node.get("bindings")
        if isinstance(bindings, dict) and bindings:
            item["bindings"] = deepcopy(bindings)
        if ntype == "if":
            item["_raw_condition"] = node.get("condition")
        if ntype == "label":
            item["op_id"] = "label"
            ai_labels.append(key)
        if ntype == "label" or str(item.get("op_id") or "") == "label_tree_input":
            sinks.append(key)
        if ntype == "source":
            item["params"].setdefault("required", True)
        by_key[key] = item
        norm_nodes.append(item)
    if len(ai_labels) > 1:
        raise ValueError("graph can contain at most one AI label node")
    if not sinks:
        raise ValueError("需要标签树写入（AI打标器或标签树输入）")
    norm_edges: list[dict[str, Any]] = []
    for i, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise ValueError("graph edge must be an object")
        src = str(edge.get("source") or "").strip()
        tgt = str(edge.get("target") or "").strip()
        sp = str(edge.get("source_port") or "out").strip() or "out"
        tp = str(edge.get("target_port") or "in").strip() or "in"
        if src not in by_key or tgt not in by_key:
            raise ValueError(f"graph edge references unknown node {src!r}->{tgt!r}")
        if by_key[src]["type"] == "if" and sp not in IF_OUT_PORTS:
            raise ValueError("if node outgoing port must be then or else")
        eid = str(edge.get("id") or f"e{i}").strip() or f"e{i}"
        norm_edges.append({"id": eid, "source": src, "source_port": sp, "target": tgt, "target_port": tp})
    adj = _adj(norm_edges)
    rev_adj = _rev_adj(norm_edges)
    sink_reach: set[str] = set()
    for sk in sinks:
        sink_reach |= _reachable(sk, adj)
    for node in norm_nodes:
        if node["type"] != "if":
            continue
        ik = node["key"]
        after_label = ik in sink_reach
        by_key[ik]["condition"] = validate_condition(node.pop("_raw_condition", None), after_label=after_label)
    if _has_cycle(set(by_key), adj):
        raise ValueError("graph contains a cycle")
    if_keys = [k for k, n in by_key.items() if n["type"] == "if"]
    for ik in if_keys:
        ports = {str(e.get("source_port")) for e in adj.get(ik, [])}
        if "then" not in ports:
            raise ValueError("if node must have a then outgoing edge")
        if "else" not in ports:
            raise ValueError("if node must have an else outgoing edge")
    for node in norm_nodes:
        if node["type"] != "source":
            continue
        required = bool(node["params"].get("required", True))
        if required and not adj.get(node["key"]):
            raise ValueError("必选数据源必须连到下游节点")
    _check_parallel_joins(by_key, norm_edges, rev_adj)
    adj_no_sinks = _adj_without_nodes(set(by_key), adj, set(sinks))
    source_keys = [n["key"] for n in norm_nodes if n["type"] == "source"]
    for node in norm_nodes:
        if node["type"] not in {"review", "export"}:
            continue
        rk = node["key"]
        for sk in source_keys:
            if rk in _reachable(sk, adj_no_sinks):
                raise ValueError("review/export 必须在标签树写入之后")
        if rk not in sink_reach:
            raise ValueError("review/export 必须在标签树写入之后")
    out["nodes"] = norm_nodes
    out["edges"] = norm_edges
    return out


def _remap_binding_value(raw: Any, keymap: dict[str, str]) -> Any:
    if isinstance(raw, list):
        return [_remap_binding_value(item, keymap) for item in raw]
    if not isinstance(raw, dict):
        return raw
    out = dict(raw)
    if out.get("kind") == "upstream":
        sk = str(out.get("step_key") or "")
        if sk in keymap:
            out["step_key"] = keymap[sk]
    if out.get("kind") == "slot":
        sid = str(out.get("slot_id") or "")
        if sid in keymap:
            out["slot_id"] = keymap[sid]
    return out


def catalogize_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Rewrite linear hydrate aliases (prep-N-op / stage-embed) to catalog op ids."""
    raw = deepcopy(graph) if isinstance(graph, dict) else {"nodes": [], "edges": []}
    nodes = [n for n in (raw.get("nodes") or []) if isinstance(n, dict)]
    used: set[str] = set()
    for node in nodes:
        key = str(node.get("key") or "").strip()
        if key and not is_legacy_hydrate_key(key):
            used.add(key)
    keymap: dict[str, str] = {}
    new_nodes: list[dict[str, Any]] = []
    for node in nodes:
        old = str(node.get("key") or "").strip()
        ntype = str(node.get("type") or "")
        op_id = str(node.get("op_id") or ("label" if ntype == "label" else "")).strip()
        if is_legacy_hydrate_key(old):
            preferred = op_id or old
            if old == "stage-embed":
                preferred = op_id or "embed"
            new_key = unique_catalog_key(preferred, used)
        else:
            new_key = old
        keymap[old] = new_key
        item = dict(node)
        item["key"] = new_key
        if ntype != "source" and op_id:
            title = str(item.get("title") or "")
            if is_generic_node_title(title, op_id, old) or is_generic_node_title(title, op_id, new_key):
                item["title"] = display_op_title(op_id) or item.get("title") or new_key
        new_nodes.append(item)
    for item in new_nodes:
        bindings = item.get("bindings")
        if isinstance(bindings, dict):
            item["bindings"] = {pid: _remap_binding_value(val, keymap) for pid, val in bindings.items()}
        cond = item.get("condition")
        if isinstance(cond, dict) and isinstance(cond.get("all"), list):
            remapped = []
            for pred in cond["all"]:
                if not isinstance(pred, dict):
                    remapped.append(pred)
                    continue
                p = dict(pred)
                if p.get("field") == "source.slot_id" and isinstance(p.get("value"), str) and p["value"] in keymap:
                    p["value"] = keymap[p["value"]]
                remapped.append(p)
            item["condition"] = {**cond, "all": remapped}
    new_edges: list[dict[str, Any]] = []
    for edge in raw.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src = keymap.get(str(edge.get("source") or ""), str(edge.get("source") or ""))
        tgt = keymap.get(str(edge.get("target") or ""), str(edge.get("target") or ""))
        sp = str(edge.get("source_port") or "out") or "out"
        tp = str(edge.get("target_port") or "in") or "in"
        new_edges.append(
            {
                **edge,
                "id": f"{src}-{sp}->{tgt}-{tp}",
                "source": src,
                "target": tgt,
                "source_port": sp,
                "target_port": tp,
            }
        )
    out = dict(raw)
    out["nodes"] = new_nodes
    out["edges"] = new_edges
    return out


def hydrate_graph(recipe: dict[str, Any]) -> dict[str, Any]:
    raw = recipe.get("graph")
    if isinstance(raw, dict) and raw.get("nodes"):
        try:
            return validate_graph(catalogize_graph(raw))
        except ValueError:
            legacy = any(
                isinstance(n, dict) and is_legacy_hydrate_key(str(n.get("key") or ""))
                for n in raw.get("nodes") or []
            )
            if not legacy:
                raise
    from hmi.platform.recipe_pipeline import hydrate_recipe_to_steps

    steps = hydrate_recipe_to_steps(recipe)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    prev: str | None = None
    y = 0
    for step in steps:
        key = str(step.get("key") or "").strip()
        if not key:
            continue
        op_id = str(step.get("op_id") or "")
        if step.get("card_kind") == "source" or op_id == "source":
            ntype = "source"
        elif op_id == "label":
            ntype = "label"
        else:
            ntype = "op"
        params = dict(step.get("params") or {})
        if ntype == "source":
            if step.get("kinds") is not None:
                params["kinds"] = list(step.get("kinds") or [])
            params.setdefault("required", bool(step.get("required", True)))
            if step.get("cardinality_min") is not None:
                params["cardinality_min"] = int(step.get("cardinality_min") or 1)
            if step.get("cardinality_max") is not None:
                params["cardinality_max"] = int(step.get("cardinality_max") or 1)
        spec = CATALOG.get(op_id) or {}
        stored_title = str(step.get("title") or "")
        title = display_op_title(op_id, stored_title, key) if op_id else (stored_title or spec.get("title") or key)
        nodes.append(
            {
                "key": key,
                "type": ntype,
                "op_id": op_id or ntype,
                "title": str(title or key),
                "params": params,
                "position": {"x": 80, "y": y},
            }
        )
        if prev:
            edges.append(
                {
                    "id": f"{prev}->{key}",
                    "source": prev,
                    "source_port": "out",
                    "target": key,
                    "target_port": "in",
                }
            )
        prev = key
        y += 96
    if not any(is_labels_sink(n) for n in nodes):
        nodes.append(
            {
                "key": "stage-label",
                "type": "label",
                "op_id": "label",
                "title": display_op_title("label"),
                "params": {},
                "position": {"x": 80, "y": y},
            }
        )
        if prev:
            edges.append(
                {
                    "id": f"{prev}->stage-label",
                    "source": prev,
                    "source_port": "out",
                    "target": "stage-label",
                    "target_port": "in",
                }
            )
    return validate_graph(catalogize_graph({"nodes": nodes, "edges": edges}))


def apply_node_param_overrides(
    graph: dict[str, Any],
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge per-node param/condition overlays. Does not add, drop, or reorder nodes."""
    g = deepcopy(validate_graph(graph))
    raw = overrides if isinstance(overrides, dict) else {}
    for node in g["nodes"]:
        ov = raw.get(str(node["key"]))
        if not isinstance(ov, dict):
            continue
        params = ov.get("params")
        if isinstance(params, dict):
            base = dict(node.get("params") or {})
            base.update(params)
            node["params"] = base
        if str(node.get("type") or "") == "if" and "condition" in ov:
            cond = ov.get("condition")
            if cond is None:
                node.pop("condition", None)
            elif isinstance(cond, dict):
                node["condition"] = cond
    return g


def _binding_refs(node: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    bindings = node.get("bindings")
    if not isinstance(bindings, dict):
        return refs
    for raw in bindings.values():
        items = raw if isinstance(raw, list) else [raw]
        for bind in items:
            if not isinstance(bind, dict):
                continue
            kind = str(bind.get("kind") or "")
            if kind == "slot" and bind.get("slot_id"):
                refs.append(str(bind["slot_id"]))
            elif kind == "upstream" and bind.get("step_key"):
                refs.append(str(bind["step_key"]))
    return refs


def _binding_from_source(src: dict[str, Any], source_port: str) -> dict[str, Any]:
    if str(src.get("type") or "") == "source":
        return {"kind": "slot", "slot_id": str(src.get("key") or "")}
    port = str(source_port or "out").strip() or "out"
    bind: dict[str, Any] = {"kind": "upstream", "step_key": str(src.get("key") or "")}
    if port != "out":
        bind["port_id"] = port
    return bind


def merge_node_bindings_from_edges(node: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    """Incoming canvas edges win over stale inspector bindings on the same port."""
    by_key = {str(n.get("key") or ""): n for n in graph.get("nodes") or [] if isinstance(n, dict)}
    merged = dict(node.get("bindings") or {}) if isinstance(node.get("bindings"), dict) else {}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in graph.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        if str(edge.get("target") or "") != str(node.get("key") or ""):
            continue
        src = by_key.get(str(edge.get("source") or ""))
        if not src:
            continue
        port = str(edge.get("target_port") or "in").strip() or "in"
        grouped.setdefault(port, []).append(_binding_from_source(src, str(edge.get("source_port") or "out")))
    for port, binds in grouped.items():
        merged[port] = binds[0] if len(binds) == 1 else binds
    return merged


def ordered_node_keys(graph: dict[str, Any]) -> list[str]:
    """Stable topological order (edges + bindings); falls back to stored node list on cycles."""
    g = validate_graph(graph)
    orig = [str(n["key"]) for n in g["nodes"]]
    indeg = {k: 0 for k in orig}
    adj: dict[str, list[str]] = {k: [] for k in orig}
    seen: set[tuple[str, str]] = set()

    def add(src: str, tgt: str) -> None:
        if not src or not tgt or src == tgt or (src, tgt) in seen:
            return
        if src not in adj or tgt not in indeg:
            return
        seen.add((src, tgt))
        adj[src].append(tgt)
        indeg[tgt] += 1

    for edge in g["edges"]:
        add(str(edge.get("source") or ""), str(edge.get("target") or ""))
    for node in g["nodes"]:
        tgt = str(node.get("key") or "")
        for ref in _binding_refs(node):
            add(ref, tgt)
    ready = [k for k in orig if indeg[k] == 0]
    out: list[str] = []
    while ready:
        key = ready.pop(0)
        out.append(key)
        for t in adj[key]:
            if t not in indeg:
                continue
            indeg[t] -= 1
            if indeg[t] == 0:
                ready.append(t)
        ready.sort(key=lambda k: orig.index(k))
    return out if len(out) == len(orig) else orig


def graph_to_steps(graph: dict[str, Any]) -> list[dict[str, Any]]:
    """Canvas → linear compile cards in topo order (mirrors frontend graphToSteps)."""
    from hmi.platform.recipe_pipeline import new_source_card

    g = validate_graph(graph)
    by_key = {n["key"]: n for n in g["nodes"]}
    steps: list[dict[str, Any]] = []
    for key in ordered_node_keys(g):
        node = by_key[key]
        ntype = str(node.get("type") or "")
        if ntype in {"if", "review", "export"}:
            continue
        params = dict(node.get("params") or {})
        if ntype == "source":
            kinds = [str(x) for x in (params.get("kinds") or [".mp4"])]
            steps.append(
                new_source_card(
                    key=key,
                    title=str(node.get("title") or key),
                    kinds=kinds or [".mp4"],
                    cardinality_min=int(params.get("cardinality_min") or 1),
                    cardinality_max=int(params.get("cardinality_max") or 1),
                    required=params.get("required", True) is not False,
                )
            )
            continue
        op_id = str(node.get("op_id") or ("label" if ntype == "label" else "")).strip()
        if not op_id:
            continue
        steps.append(
            {
                "key": key,
                "op_id": op_id,
                "title": str(node.get("title") or key),
                "role": "stage" if ntype == "label" or op_id == "label" else "preprocess",
                "params": params,
                "required": bool(params.get("required")),
                "bindings": merge_node_bindings_from_edges(node, g),
                "bbox_enabled": params.get("bbox_enabled") is not False if op_id == "detect_bbox" else None,
            }
        )
    return steps


def _require_any_kinds_from_slots(slots: list[dict[str, Any]]) -> list[list[str]]:
    required = [s for s in slots if s.get("required") and s.get("kinds")]
    pool = required if required else [s for s in slots if s.get("kinds")]
    groups: list[list[str]] = []
    for slot in pool:
        groups.extend(singleton_kind_groups(*(list(slot.get("kinds") or []))))
    return groups


def graph_is_lossy(graph: dict[str, Any]) -> bool:
    g = validate_graph(graph)
    return any(n["type"] in {"if", "review", "export"} for n in g["nodes"])


def _prefix_op_keys(g: dict[str, Any]) -> list[str]:
    adj = _adj(g["edges"])
    blocked: set[str] = set()

    def mark_from(start: str) -> None:
        stack = [start]
        seen = {start}
        while stack:
            u = stack.pop()
            blocked.add(u)
            for e in adj.get(u, []):
                v = str(e.get("target") or "")
                if v and v not in seen:
                    seen.add(v)
                    stack.append(v)

    for n in g["nodes"]:
        if n["type"] != "if":
            continue
        for e in adj.get(n["key"], []):
            tgt = str(e.get("target") or "")
            if tgt:
                mark_from(tgt)
    prefix: list[str] = []
    for n in g["nodes"]:
        if n["type"] == "op" and n["key"] not in blocked:
            prefix.append(n["key"])
    return prefix


def project_graph(graph: dict[str, Any]) -> dict[str, Any]:
    g = validate_graph(graph)
    nodes = {n["key"]: n for n in g["nodes"]}
    slots = []
    for n in g["nodes"]:
        if n["type"] != "source":
            continue
        p = n["params"]
        kinds = list(p.get("kinds") or ["video"])
        slots.append(
            {
                "id": n["key"],
                "title": n["title"],
                "kinds": kinds,
                "cardinality_min": int(p.get("cardinality_min") or 1),
                "cardinality_max": int(p.get("cardinality_max") or 1),
                "role": str(p.get("role") or "input"),
                "required": bool(p.get("required", True)),
            }
        )
    prefix_keys = _prefix_op_keys(g)
    preprocess = []
    products = []
    bbox = {"enabled": False, "detector": "opencv", "yolo_classes": ""}
    embed_enabled = False
    label_stage: dict[str, Any] = {"enabled": False}
    from hmi.platform.label_model_params import label_stage_extras

    for n in g["nodes"]:
        op_id = str(n.get("op_id") or "")
        if op_id == "embed":
            embed_enabled = True
        if op_id == "label" or n.get("type") == "label":
            label_stage["enabled"] = True
            p = dict(n.get("params") or {})
            model = str(p.get("model") or "").strip()
            if model:
                label_stage["model"] = model
            label_stage.update(label_stage_extras(p))
    for key in prefix_keys:
        n = nodes[key]
        op_id = str(n.get("op_id") or "")
        if op_id in {"embed", "label"}:
            continue
        if op_id == "detect_bbox":
            bbox = {
                "enabled": True,
                "detector": str(n["params"].get("detector") or "opencv"),
                "yolo_classes": str(n["params"].get("yolo_classes") or ""),
            }
        entry: dict[str, Any] = {"op_id": op_id, "when_kind": n["params"].get("when_kind"), "required": False}
        produces = n["params"].get("produces")
        if produces:
            entry["produces"] = list(produces)
            for name in produces:
                products.append({"id": name, "from_op": op_id, "reusable": True})
        preprocess.append(entry)
    return {
        "slots": slots,
        "preprocess": preprocess,
        "products": products,
        "stages": {"label": label_stage, "embed": {"enabled": embed_enabled}},
        "bbox": bbox,
        "require_any_kinds": _require_any_kinds_from_slots(slots),
    }
