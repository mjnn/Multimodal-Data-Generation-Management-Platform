"""Isolated DAG node probe (orchestration-time, no facts / active_run)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from hmi.platform.io_contract import consume_flags, diagnose_graph, missing_produces, node_produces
from hmi.platform.recipe_graph import validate_graph
from hmi.platform.store import get_source

_AUDIO_FILE_EXTS = frozenset({".wav", ".dat"})


def _source_manifest_for_probe(src: dict[str, Any], run_dir: Path) -> Path | None:
    """Lake audio stores local_path as source_manifest.json next to audio.wav."""
    local = Path(str(src.get("local_path") or "").strip())
    if local.is_file() and local.name.lower() == "source_manifest.json":
        return local
    if local.is_file():
        sibling = local.parent / "source_manifest.json"
        if sibling.is_file():
            return sibling
    oss_key = str(src.get("local_oss_key") or "").strip()
    if oss_key:
        try:
            from hmi.local.source_upload import resolve_local_source_manifest

            resolved = resolve_local_source_manifest(oss_key)
        except Exception:
            resolved = None
        if resolved is not None and resolved.is_file():
            return resolved
    if local.is_file() and local.suffix.lower() in _AUDIO_FILE_EXTS:
        man = run_dir / "source_manifest.json"
        man.write_text(
            json.dumps({"audio": str(local.resolve()), "audio_path": str(local.resolve())}),
            encoding="utf-8",
        )
        return man
    return None


def probe_graph(
    graph: dict[str, Any],
    *,
    until_key: str,
    include_ai: bool = False,
    source_ids: list[str] | None = None,
    recipe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    until = str(until_key or "").strip()
    ids = [str(s).strip() for s in (source_ids or []) if str(s).strip()]
    if not ids:
        diag: dict[str, Any] = {}
        expected: list[str] = []
        consume: dict[str, Any] = {}
        try:
            g = validate_graph(graph)
            diag = diagnose_graph(g)
            by_key = {str(n.get("key") or ""): n for n in g["nodes"]}
            node = by_key.get(until)
            if node is not None:
                expected = node_produces(node)
                if str(node.get("type") or "") in {"op", "label"}:
                    consume = consume_flags(node, g)
        except ValueError:
            pass
        return {
            "ok": False,
            "ran": False,
            "error": "需要数据源才能试跑",
            "until_key": until,
            "nodes": diag,
            "produces_expected": expected,
            "consume": consume,
        }

    g = validate_graph(graph)
    diag = diagnose_graph(g)
    by_key = {str(n.get("key") or ""): n for n in g["nodes"]}
    node = by_key.get(until)
    if not until or node is None:
        return {"ok": False, "ran": False, "error": "until_key 不是图上的节点", "nodes": diag}
    consume = consume_flags(node, g) if str(node.get("type") or "") in {"op", "label"} else {}
    expected = node_produces(node)

    src = get_source(ids[0])
    if not src:
        return {"ok": False, "ran": False, "error": f"未知数据源 {ids[0]}", "nodes": diag, "until_key": until}
    bag = Path(str(src.get("local_path") or ""))
    if not bag.is_file():
        return {"ok": False, "ran": False, "error": "数据源没有本地文件", "nodes": diag, "until_key": until}

    run_dir = Path(tempfile.mkdtemp(prefix="dtype-probe-"))
    try:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.capability_sdk import sdk_runner_for_bundle
        from oms_multimodal.client import OmsMultimodalClient
        from oms_multimodal.config import ClientConfig, ClipConfig

        client_cfg = ClientConfig.from_env()
        client_cfg.model_backend = "api"
        client = OmsMultimodalClient(config=client_cfg, work_dir=run_dir / "work")
        manifest = _source_manifest_for_probe(src, run_dir)
        ctx0: dict[str, Any] = {
            "run_dir": str(run_dir),
            "source": {
                "kind": src.get("kind"),
                "slot_id": ids[0],
                "path": str(bag),
            },
            "bag_path": str(bag),
        }
        if manifest is not None:
            ctx0["source_manifest_path"] = str(manifest)
        out = execute_recipe_graph(
            g,
            ctx0=ctx0,
            sdk_runner=sdk_runner_for_bundle(
                run_dir=run_dir,
                bag_path=bag,
                client=client,
                clip_config=ClipConfig(),
                recipe=recipe,
            ),
            until_key=until,
            require_label=False,
            include_ai=bool(include_ai),
        )
        ctx = out.get("ctx") if isinstance(out.get("ctx"), dict) else {}
        found_missing = missing_produces(node, ctx=ctx)
        found = [p for p in expected if p not in found_missing]
        statuses = {str(r.get("key")): str(r.get("status")) for r in (out.get("run") or [])}
        err = None
        if found_missing and statuses.get(until) == "success":
            err = f"节点 {until} 未按期望输出: {', '.join(found_missing)}"
        ok = not found_missing and statuses.get(until) in {"success", "checked"}
        return {
            "ok": ok,
            "ran": True,
            "until_key": until,
            "run": out.get("run") or [],
            "produces_expected": expected,
            "produces_found": found,
            "missing": found_missing,
            "consume": ctx.get("_consume") or consume,
            "nodes": diag,
            "error": err,
            "run_dir": str(run_dir),
        }
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        return {
            "ok": False,
            "ran": True,
            "until_key": until,
            "error": msg,
            "nodes": diag,
            "produces_expected": expected,
            "consume": consume,
            "run_dir": str(run_dir),
        }
