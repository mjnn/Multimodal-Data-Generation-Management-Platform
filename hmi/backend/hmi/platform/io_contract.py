"""Closed I/O contract for DataType DAG nodes.

Catalog ports declare min_count. Bindings must resolve to upstream produces or
source slots. Runtime consumes only bound kinds; producers fail if declared
artifacts are missing.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.platform.file_kinds import AUDIO_EXTS, normalize_source_kind
from hmi.platform.operators import CATALOG, get_operator, type_compatible
from hmi.platform.recipe_graph import merge_node_bindings_from_edges, validate_graph
from hmi.platform.recipe_pipeline import _bind_list, effective_produces, expand_output_ports, input_ports, is_source_card

AI_OP_IDS = frozenset({"label", "embed", "transcribe", "detect_bbox"})
CONTROL_TYPES = frozenset({"source", "if", "review", "export"})
PASSTHROUGH_TYPES = frozenset({"if", "review", "export"})
PRODUCE_ALIASES = {
    "pcm_pa": "pcm_pa_wavs",
    "third_octave": "third_octave_json",
    "spl_timeline": "spl_jsonl",
    "mel_png": "mel_matrix",
}

_MSG = {
    "min_input": "最少需要 {need} 路「{port}」，当前 {got} 路",
    "unbound_kind": "输入不在上游产物或数据源内：{detail}",
    "empty_assignments": "标签树输入还没有条目",
    "bad_produces": "期望输出不在组件可输出列表内",
}


def _node_card(node: dict[str, Any]) -> dict[str, Any]:
    params = dict(node.get("params") or {}) if isinstance(node.get("params"), dict) else {}
    produces = node.get("produces")
    if produces is None:
        produces = params.get("produces")
    card = {
        "key": node.get("key"),
        "op_id": node.get("op_id") or node.get("type"),
        "type": node.get("type"),
        "params": params,
        "produces": produces,
        "kinds": params.get("kinds") or node.get("kinds"),
        "bindings": node.get("bindings"),
    }
    if str(node.get("type") or "") == "source" or str(card.get("op_id") or "") == "source":
        card["card_kind"] = "source"
        card["op_id"] = "source"
    return card


def node_produces(node: dict[str, Any]) -> list[str]:
    card = _node_card(node)
    if is_source_card(card):
        kinds: list[str] = []
        for raw in card.get("kinds") or []:
            text = str(raw).strip()
            nk = normalize_source_kind(text) or text
            if nk and nk not in kinds:
                kinds.append(nk)
        return kinds
    if str(node.get("type") or "") in PASSTHROUGH_TYPES:
        return []
    op = get_operator(str(card.get("op_id") or ""))
    names = list(effective_produces(card, op))
    out: list[str] = []
    for name in names:
        canon = PRODUCE_ALIASES.get(name, name)
        if canon not in out:
            out.append(canon)
    return out


def allowed_output_ids(node: dict[str, Any]) -> list[str]:
    op = get_operator(str(node.get("op_id") or node.get("type") or ""))
    if not op:
        return node_produces(node)
    names: list[str] = []
    raw_params = node.get("params") if isinstance(node.get("params"), dict) else {}
    for port in expand_output_ports(op, raw_params):
        pid = str(port.get("id") or "").strip()
        types = [str(t).strip() for t in (port.get("types") or []) if str(t).strip()]
        if pid:
            names.append(pid)
        for t in types:
            if t not in names:
                names.append(t)
    return names or node_produces(node)


def resolved_bindings(node: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    return merge_node_bindings_from_edges(node, graph)


def _by_key(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(n.get("key") or ""): n for n in graph.get("nodes") or [] if isinstance(n, dict)}


def _upstream_source_kinds(node: dict[str, Any], graph: dict[str, Any]) -> list[str]:
    nodes = _by_key(graph)
    seen: set[str] = set()
    stack = [str(node.get("key") or "")]
    kinds: list[str] = []
    while stack:
        key = stack.pop()
        if not key or key in seen:
            continue
        seen.add(key)
        cur = nodes.get(key)
        if not cur:
            continue
        if str(cur.get("type") or "") == "source":
            for k in node_produces(cur):
                if k not in kinds:
                    kinds.append(k)
            continue
        for edge in graph.get("edges") or []:
            if not isinstance(edge, dict):
                continue
            if str(edge.get("target") or "") != key:
                continue
            stack.append(str(edge.get("source") or ""))
    return kinds


def bind_provided_types(bind: dict[str, Any], graph: dict[str, Any]) -> list[str] | None:
    """Return provided type ids, ``['*']`` for control passthrough, or ``None`` if dangling."""
    kind = str(bind.get("kind") or "")
    nodes = _by_key(graph)
    if kind == "slot":
        src = nodes.get(str(bind.get("slot_id") or "").strip())
        if not src or str(src.get("type") or "") != "source":
            return None
        kinds = node_produces(src)
        return kinds or ["*"]
    if kind != "upstream":
        return None
    up = nodes.get(str(bind.get("step_key") or "").strip())
    if not up:
        return None
    if str(up.get("type") or "") in PASSTHROUGH_TYPES:
        return ["*"]
    produces = node_produces(up)
    port_id = str(bind.get("port_id") or "").strip()
    up_op = get_operator(str(up.get("op_id") or up.get("type") or ""))
    raw_params = up.get("params") if isinstance(up.get("params"), dict) else {}
    expanded = expand_output_ports(up_op, raw_params) if up_op else []
    if not port_id or port_id == "out":
        merged = list(produces)
        for k in _upstream_source_kinds(up, graph):
            if k not in merged:
                merged.append(k)
        return merged
    expand_from = str((up_op or {}).get("expand_outputs_from") or "")
    for port in expanded:
        if str(port.get("id") or "") != port_id:
            continue
        types = [str(t).strip() for t in (port.get("types") or []) if str(t).strip()]
        if expand_from == "channel_count":
            return types or [port_id]
        if port_id in produces or any(t in produces for t in types):
            return types or [port_id]
        return None
    if port_id in produces:
        return [port_id]
    return None


def _is_audio_kind(kind: str) -> bool:
    k = str(kind or "").strip()
    if not k or k == "*":
        return False
    if k in AUDIO_EXTS or k == "pcm_pa_wavs":
        return True
    return type_compatible(k, ".wav")


def consume_flags(node: dict[str, Any], graph: dict[str, Any]) -> dict[str, bool]:
    kinds: list[str] = []
    bindings = resolved_bindings(node, graph)
    for raw in (bindings or {}).values():
        for bind in _bind_list(raw):
            provided = bind_provided_types(bind, graph) or []
            kinds.extend(provided)
    return {
        "include_audio": any(_is_audio_kind(k) for k in kinds),
        "include_asr": any(k == "asr_jsonl" or type_compatible(k, "asr_jsonl") for k in kinds if k != "*"),
        "include_bbox": any(k == "bboxes_jsonl" or type_compatible(k, "bboxes_jsonl") for k in kinds if k != "*"),
    }


def _compatible_any(provided: list[str], needed: list[str]) -> bool:
    if "*" in provided:
        return True
    if not needed:
        return bool(provided)
    for p in provided:
        for n in needed:
            if type_compatible(p, n) or p == n:
                return True
    return False


def diagnose_node(node: dict[str, Any], graph: dict[str, Any]) -> dict[str, Any]:
    ntype = str(node.get("type") or "")
    if ntype in CONTROL_TYPES and ntype != "source":
        return {"level": "ok", "codes": [], "message": ""}
    if ntype == "source":
        return {"level": "ok", "codes": [], "message": ""}
    op_id = str(node.get("op_id") or ntype)
    op = get_operator(op_id) or CATALOG.get(op_id)
    codes: list[str] = []
    parts: list[str] = []
    bindings = resolved_bindings(node, graph)
    for port in input_ports(op):
        pid = str(port.get("id") or "in")
        min_count = max(0, int(port.get("min_count") if port.get("min_count") is not None else 1))
        needed = [str(t).strip() for t in (port.get("types") or []) if str(t).strip()]
        binds = _bind_list((bindings or {}).get(pid))
        ok_binds: list[dict[str, Any]] = []
        bad: list[str] = []
        for bind in binds:
            provided = bind_provided_types(bind, graph)
            if provided is None:
                bad.append(_bind_label(bind))
                continue
            if not _compatible_any(provided, needed):
                bad.append(_bind_label(bind))
                continue
            ok_binds.append(bind)
        if len(ok_binds) < min_count:
            codes.append("min_input")
            parts.append(
                _MSG["min_input"].format(
                    need=min_count,
                    port=str(port.get("title") or pid),
                    got=len(ok_binds),
                )
            )
        if bad:
            codes.append("unbound_kind")
            parts.append(_MSG["unbound_kind"].format(detail="、".join(bad)))
    if op_id == "label_tree_input":
        params = node.get("params") if isinstance(node.get("params"), dict) else {}
        rows = params.get("assignments") if isinstance(params.get("assignments"), list) else []
        if not rows:
            codes.append("empty_assignments")
            parts.append(_MSG["empty_assignments"])
    allowed = set(allowed_output_ids(node))
    selected = node_produces(node)
    if allowed and selected and any(p not in allowed for p in selected):
        codes.append("bad_produces")
        parts.append(_MSG["bad_produces"])
    uniq: list[str] = []
    for c in codes:
        if c not in uniq:
            uniq.append(c)
    return {
        "level": "warn" if uniq else "ok",
        "codes": uniq,
        "message": "；".join(parts),
    }


def _bind_label(bind: dict[str, Any]) -> str:
    if str(bind.get("kind") or "") == "slot":
        return str(bind.get("slot_id") or "slot")
    port = str(bind.get("port_id") or "out")
    step = str(bind.get("step_key") or "?")
    return f"{step}.{port}"


def diagnose_graph(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    g = validate_graph(graph)
    return {str(n["key"]): diagnose_node(n, g) for n in g["nodes"]}


def assert_inputs_ok(node: dict[str, Any], graph: dict[str, Any]) -> None:
    diag = diagnose_node(node, graph)
    blocking = {"min_input", "unbound_kind", "empty_assignments"}
    hit = [c for c in diag.get("codes") or [] if c in blocking]
    if hit:
        raise RuntimeError(f"节点 {node.get('key')} {diag.get('message') or '输入不满足契约'}")


def _run_dir(ctx: dict[str, Any]) -> Path | None:
    raw = str(ctx.get("run_dir") or "").strip()
    return Path(raw) if raw else None


def _clips_index_rows(run_dir: Path | None) -> list[dict[str, Any]]:
    if run_dir is None:
        return []
    path = run_dir / "clips_index.jsonl"
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _file_exists(raw: Any) -> bool:
    if not isinstance(raw, str) or not raw.strip():
        return False
    return Path(raw).is_file()


def produce_present(name: str, node: dict[str, Any], ctx: dict[str, Any]) -> bool:
    key = str(name or "").strip()
    run_dir = _run_dir(ctx)
    if key == "frames":
        if ctx.get("extract"):
            return True
        return bool(_clips_index_rows(run_dir))
    if key in {".wav", "pcm_pa_wavs"}:
        if ctx.get("pcm_pa_wavs") or ctx.get("pcm_pa"):
            return True
        if run_dir and (run_dir / "pcm_pa.npy").is_file():
            return True
        for row in _clips_index_rows(run_dir):
            audio = row.get("audio") if isinstance(row.get("audio"), dict) else {}
            path = audio.get("audio_path") or row.get("audio_path")
            if _file_exists(path):
                return True
        if run_dir and any(run_dir.rglob("*.wav")):
            return True
        return False
    if key == ".json":
        for row in _clips_index_rows(run_dir):
            events = row.get("events")
            if isinstance(events, list) and events:
                return True
        if run_dir:
            for path in run_dir.rglob("*.json"):
                if path.name in {"source_manifest.json", "structured.json"}:
                    continue
                return True
        return bool(ctx.get("extract"))
    if key == "asr_jsonl":
        if isinstance(ctx.get("asr"), dict):
            return True
        return bool(run_dir and (run_dir / "asr.jsonl").is_file())
    if key == "bboxes_jsonl":
        if ctx.get("bbox"):
            return True
        return bool(run_dir and (run_dir / "bboxes.jsonl").is_file())
    if key in {"labels_tree", "labels"}:
        if ctx.get("labels_tree") or ctx.get("labels"):
            return True
        return bool(run_dir and ((run_dir / "labels.jsonl").is_file() or (run_dir / "nvh_labels.json").is_file()))
    if key == "embeddings":
        if ctx.get("embeddings"):
            return True
        return bool(run_dir and (run_dir / "fusion_embeddings.jsonl").is_file())
    if key == "preview_mp4":
        if ctx.get("preview"):
            return True
        if run_dir:
            prev = run_dir / "preview"
            if prev.is_dir() and any(prev.glob("clip_preview_*.mp4")):
                return True
        return False
    if key == "structured_json":
        if ctx.get("structured_json"):
            return True
        return bool(run_dir and (run_dir / "structured.json").is_file())
    if key == "json_value":
        bag = ctx.get("json_extract")
        if bag is not None:
            return True
        node_key = str(node.get("key") or "")
        return node_key in ctx and ctx.get(node_key) is not None
    if key in {"mel_matrix", "stft_matrix", "third_octave_json", "spl_jsonl"}:
        if ctx.get(key):
            return True
        if run_dir:
            for name in (f"{key}.json", f"{key}.jsonl", "nvh_labels.json"):
                if (run_dir / name).is_file():
                    return True
        return False
    if ctx.get(key):
        return True
    return False


def missing_produces(node: dict[str, Any], *, ctx: dict[str, Any]) -> list[str]:
    ntype = str(node.get("type") or "")
    if ntype in CONTROL_TYPES:
        return []
    missing: list[str] = []
    for name in node_produces(node):
        if not produce_present(name, node, ctx):
            missing.append(name)
    return missing


def assert_produces_present(node: dict[str, Any], ctx: dict[str, Any]) -> None:
    missing = missing_produces(node, ctx=ctx)
    if missing:
        raise RuntimeError(f"节点 {node.get('key')} 未按期望输出: {', '.join(missing)}")
