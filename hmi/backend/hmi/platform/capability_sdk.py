"""SDK capability plugins: one oms_multimodal stage per DAG node."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.platform.capability_kernel import plugin_for


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
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


def asr_ctx_patch(run_dir: Path) -> dict[str, Any]:
    rows = _read_jsonl(Path(run_dir) / "asr.jsonl")
    confs: list[float] = []
    texts: list[str] = []
    for row in rows:
        for key in ("avg_confidence", "confidence", "confidence_avg"):
            raw = row.get(key)
            if raw is None:
                continue
            try:
                confs.append(float(raw))
            except (TypeError, ValueError):
                pass
            break
        text = str(row.get("text") or row.get("asr_text") or "").strip()
        if text:
            texts.append(text)
    avg = sum(confs) / len(confs) if confs else 0.0
    return {
        "asr": {
            "avg_confidence": avg,
            "text": " ".join(texts),
            "row_count": len(rows),
        }
    }


def labels_ctx_patch(run_dir: Path) -> dict[str, Any]:
    rows = _read_jsonl(Path(run_dir) / "labels.jsonl")
    values: dict[str, Any] = {}
    if rows:
        payload = rows[0]
        raw_vals = payload.get("values") if isinstance(payload.get("values"), dict) else None
        if raw_vals:
            values = dict(raw_vals)
        elif isinstance(payload.get("labels"), dict):
            values = dict(payload["labels"])
    labels = {"values": values, "row_count": len(rows)}
    return {"labels": labels, "labels_tree": labels}


def ctx_patch_for_capability(capability_id: str, run_dir: Path) -> dict[str, Any]:
    if capability_id == "transcribe":
        return asr_ctx_patch(run_dir)
    if capability_id == "label":
        return labels_ctx_patch(run_dir)
    if capability_id == "annotate_bbox":
        path = Path(run_dir) / "bboxes.jsonl"
        return {"bbox": {"row_count": len(_read_jsonl(path)), "path": str(path)}}
    if capability_id == "embed":
        path = Path(run_dir) / "fusion_embeddings.jsonl"
        return {"embeddings": {"row_count": len(_read_jsonl(path))}}
    if capability_id in {"extract", "ingest_sources"}:
        path = Path(run_dir) / "clips_index.jsonl"
        return {"extract": {"clip_rows": len(_read_jsonl(path))}}
    if capability_id == "encode_preview":
        return {"preview": {"ok": True}}
    return {}


def resolve_sdk_capability(node: dict[str, Any], *, has_bag: bool) -> str | None:
    op_id = str(node.get("op_id") or node.get("type") or "").strip()
    spec = plugin_for(op_id)
    if not spec or spec.get("backend") != "sdk":
        return None
    cap = str(spec.get("sdk_capability") or "")
    if op_id == "parse_bag" and not has_bag:
        return "ingest_sources"
    if op_id == "extract_frames" and has_bag:
        return "extract"
    return cap or None


def label_uses_nvh(node: dict[str, Any]) -> bool:
    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    model = str(params.get("model") or "").strip()
    return model.startswith("nvh_sem")


def run_sdk_node(
    node: dict[str, Any],
    graph_ctx: dict[str, Any],
    *,
    run_dir: Path,
    bag_path: Path | None,
    client: Any,
    clip_config: Any,
    recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute one DAG node via SDK `run_plan` (or NVH fill) and return ctx patch."""
    from oms_multimodal.capabilities.planner import PipelinePlan, PlannedCapability
    from oms_multimodal.capabilities.stages import run_plan
    from oms_multimodal.capabilities.types import RunContext

    op_id = str(node.get("op_id") or node.get("type") or "")
    if op_id == "label" and label_uses_nvh(node):
        return _run_nvh_label(node, graph_ctx, run_dir=run_dir, recipe=recipe)

    cap = resolve_sdk_capability(node, has_bag=bag_path is not None and Path(bag_path).is_file())
    if not cap:
        raise RuntimeError(f"节点 {node.get('key')} 不是 SDK capability: {op_id}")

    params = dict(node.get("params") or {}) if isinstance(node.get("params"), dict) else {}
    graph = graph_ctx.get("graph") if isinstance(graph_ctx.get("graph"), dict) else (recipe or {}).get("graph")
    consume = None
    if isinstance(graph, dict) and op_id in {"label", "embed"}:
        from hmi.platform.io_contract import consume_flags

        consume = consume_flags(node, graph)
        params["include_audio"] = bool(consume.get("include_audio"))
        params["merge_asr_file"] = bool(consume.get("include_asr"))
        if not consume.get("include_bbox"):
            params["include_bbox_context"] = False
    if cap == "annotate_bbox" and not params.get("detector"):
        bbox = (recipe or {}).get("bbox") if recipe else None
        if isinstance(bbox, dict) and bbox.get("detector"):
            params["detector"] = bbox.get("detector")
    if cap == "label":
        label_stage = ((recipe or {}).get("stages") or {}).get("label") or {}
        if isinstance(label_stage.get("bbox_in_label_prompt"), bool):
            bound_bbox = params.get("include_bbox_context")
            if bound_bbox is False:
                params["include_bbox_context"] = False
            else:
                params["include_bbox_context"] = bool(label_stage["bbox_in_label_prompt"])

    steps = [PlannedCapability(cap, params=params)]
    if cap == "encode_preview":
        steps.append(PlannedCapability("preview"))

    sdk_ctx = RunContext(
        run_dir=Path(run_dir),
        work_dir=Path(run_dir) / "work",
        clip_id=str(graph_ctx.get("clip_id") or ""),
        run_id=str(graph_ctx.get("run_id") or ""),
        media_mode="local",
    )
    bag = bag_path if bag_path is not None else Path(run_dir)
    result = run_plan(sdk_ctx, bag, client, PipelinePlan(steps=steps), clip_config=clip_config)
    if result.errors:
        raise RuntimeError(str(result.errors[0]))
    patch = ctx_patch_for_capability(cap, Path(run_dir))
    patch["_sdk_stages"] = list(result.stages_done)
    if consume is not None:
        patch["_consume"] = consume
    return patch


def _run_nvh_label(
    node: dict[str, Any],
    graph_ctx: dict[str, Any],
    *,
    run_dir: Path,
    recipe: dict[str, Any] | None,
) -> dict[str, Any]:
    from hmi.local.nvh_ai_label import fill_nvh_semantic_labels
    from hmi.local.nvh_deriver import derive_nvh_labels, persist_nvh_labels_artifact

    params = node.get("params") if isinstance(node.get("params"), dict) else {}
    label_stage = ((recipe or {}).get("stages") or {}).get("label") or {}
    model = str(params.get("model") or label_stage.get("model") or "nvh_sem_ast")
    ast_raw = params.get("ast_top_k", label_stage.get("ast_top_k"))
    try:
        ast_top_k = int(ast_raw) if ast_raw is not None else None
    except (TypeError, ValueError):
        ast_top_k = None
    labels_path = Path(run_dir) / "labels.jsonl"
    nvh_path = Path(run_dir) / "nvh_labels.json"
    base: dict[str, Any] = {}
    if nvh_path.is_file():
        try:
            loaded = json.loads(nvh_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                base = loaded
        except json.JSONDecodeError:
            base = {}
    if not base and labels_path.is_file():
        rows = _read_jsonl(labels_path)
        if rows:
            base = dict(rows[0])
    if not base:
        source_dir = None
        man = str(graph_ctx.get("source_manifest_path") or "").strip()
        if man:
            source_dir = Path(man).parent
        base = derive_nvh_labels(Path(run_dir), source_dir=source_dir)
    merged = fill_nvh_semantic_labels(
        Path(run_dir),
        base,
        model=model,
        ast_top_k=ast_top_k,
        vl_prompt=str(params.get("vl_prompt") or label_stage.get("vl_prompt") or "").strip() or None,
        vl_model=str(params.get("vl_model") or label_stage.get("vl_model") or "").strip() or None,
        reference_constraints=str(
            params.get("reference_constraints") or label_stage.get("reference_constraints") or ""
        ).strip()
        or None,
    )
    persist_nvh_labels_artifact(Path(run_dir), merged)
    labels_path.write_text(json.dumps(merged, ensure_ascii=False) + "\n", encoding="utf-8")
    return labels_ctx_patch(Path(run_dir))


def sdk_runner_for_bundle(
    *,
    run_dir: Path,
    bag_path: Path | None,
    client: Any,
    clip_config: Any,
    recipe: dict[str, Any] | None,
) -> Any:
    def runner(node: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
        return run_sdk_node(
            node,
            ctx,
            run_dir=run_dir,
            bag_path=bag_path,
            client=client,
            clip_config=clip_config,
            recipe=recipe,
        )

    return runner
