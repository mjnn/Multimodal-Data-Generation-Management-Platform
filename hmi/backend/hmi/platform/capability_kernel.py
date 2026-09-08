"""Pipeline runtime kernel: op_id → pluggable capability.

Catalog (`operators.py`) describes UI. This module is the execution registry:
SDK stages stay in oms_multimodal; local/HMI ops stay in graph_runtime adapters.
"""

from __future__ import annotations

from typing import Any, Callable

from hmi.platform.graph_runtime import Adapter, execute_graph
from hmi.platform.recipe_graph import validate_graph

Plugin = dict[str, Any]


# backend: sdk | local | control
# sdk_capability: oms_multimodal.capabilities id (see CAPABILITY_IDS)
OP_PLUGINS: dict[str, Plugin] = {
    "parse_bag": {"backend": "sdk", "sdk_capability": "extract", "writes": ["extract"]},
    "extract_frames": {"backend": "sdk", "sdk_capability": "ingest_sources", "writes": ["extract"]},
    "encode_preview": {"backend": "sdk", "sdk_capability": "encode_preview", "writes": ["preview"]},
    "transcribe": {"backend": "sdk", "sdk_capability": "transcribe", "writes": ["asr"]},
    "detect_bbox": {"backend": "sdk", "sdk_capability": "annotate_bbox", "writes": ["bbox"]},
    "label": {"backend": "sdk", "sdk_capability": "label", "writes": ["labels", "labels_tree"]},
    "embed": {"backend": "sdk", "sdk_capability": "embed", "writes": ["embeddings"]},
    "json_extract": {"backend": "local", "writes": ["json_extract"]},
    "label_tree_input": {"backend": "local", "writes": ["labels", "labels_tree"]},
    "text_to_json": {"backend": "local", "writes": ["structured_json"]},
    "mel_spectrogram": {"backend": "local", "writes": ["mel_matrix"]},
    "stft_spectrogram": {"backend": "local", "writes": ["stft_matrix"]},
    "third_octave": {"backend": "local", "writes": ["third_octave_json"]},
    "spl_timeline": {"backend": "local", "writes": ["spl_jsonl"]},
    "parse_head_dat": {"backend": "local", "writes": ["pcm_pa_wavs"]},
}

_CONTROL = frozenset({"source", "if", "review", "export"})
_IMPLEMENTED_LOCAL = frozenset({"json_extract", "label_tree_input", "text_to_json"})


def _nvh_adapters() -> dict[str, Adapter]:
    from hmi.platform.capability_nvh import LOCAL_NVH_ADAPTERS

    return LOCAL_NVH_ADAPTERS


def plugin_for(op_id: str) -> Plugin | None:
    oid = str(op_id or "").strip()
    if oid in _CONTROL:
        return {"backend": "control", "writes": []}
    spec = OP_PLUGINS.get(oid)
    return dict(spec) if spec else None


def assert_plugins_registered(graph: dict[str, Any]) -> None:
    g = validate_graph(graph)
    missing: list[str] = []
    for node in g["nodes"]:
        ntype = str(node.get("type") or "")
        if ntype not in {"op", "label"}:
            continue
        op_id = str(node.get("op_id") or ntype)
        if plugin_for(op_id) is None:
            missing.append(op_id)
    if missing:
        raise RuntimeError("未注册 capability: " + ", ".join(sorted(set(missing))))


def build_adapters(
    *,
    sdk_runner: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    on_node: Callable[[str, str, str | None], None] | None = None,
) -> dict[str, Adapter]:
    """Adapters for every registered op/label. `sdk_runner(node, ctx)` runs SDK/local-nvh."""

    from hmi.platform.graph_runtime import _BUILTIN_OP_ADAPTERS

    def wrap(op_id: str, inner: Adapter) -> Adapter:
        def adapter(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
            key = str(node.get("key") or op_id)
            if on_node:
                on_node(key, "running", None)
            try:
                patch = inner(node, ctx)
                if ctx.get("_enforce_io") and str(node.get("type") or "") in {"op", "label"}:
                    from hmi.platform.graph_runtime import _merge_patch
                    from hmi.platform.io_contract import assert_produces_present

                    merged = dict(ctx)
                    _merge_patch(merged, patch)
                    assert_produces_present(node, merged)
                if on_node:
                    on_node(key, "success", None)
                return patch
            except Exception as exc:
                if on_node:
                    on_node(key, "failed", str(exc))
                raise

        return adapter

    adapters: dict[str, Adapter] = {}
    nvh = _nvh_adapters()
    for op_id, spec in OP_PLUGINS.items():
        backend = spec["backend"]
        if backend == "local" and op_id in _BUILTIN_OP_ADAPTERS:
            adapters[op_id] = wrap(op_id, _BUILTIN_OP_ADAPTERS[op_id])
            continue
        if backend == "local" and op_id in nvh:
            adapters[op_id] = wrap(op_id, nvh[op_id])
            continue
        if backend == "local" and op_id not in _IMPLEMENTED_LOCAL:

            def _missing(node: dict[str, Any], _ctx: dict[str, Any], oid: str = op_id) -> dict[str, Any]:
                raise RuntimeError(f"capability 未实现: {oid}（节点 {node.get('key')}）")

            adapters[op_id] = wrap(op_id, _missing)
            continue
        if backend == "sdk":
            if sdk_runner is None:
                continue
            adapters[op_id] = wrap(op_id, sdk_runner)
    return adapters


def execute_recipe_graph(
    graph: dict[str, Any],
    *,
    ctx0: dict[str, Any],
    sdk_runner: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    on_node: Callable[[str, str, str | None], None] | None = None,
    on_skipped: Callable[[str], None] | None = None,
    until_key: str | None = None,
    require_label: bool = True,
    include_ai: bool = True,
    enforce_io: bool = True,
) -> dict[str, Any]:
    assert_plugins_registered(graph)
    adapters = build_adapters(sdk_runner=sdk_runner, on_node=on_node)
    out = execute_graph(
        graph,
        ctx0=ctx0,
        adapters=adapters,
        until_key=until_key,
        require_label=require_label,
        include_ai=include_ai,
        enforce_io=enforce_io,
    )
    if on_skipped:
        for row in out.get("run") or []:
            if row.get("status") == "skipped" and row.get("key"):
                on_skipped(str(row["key"]))
    return out
