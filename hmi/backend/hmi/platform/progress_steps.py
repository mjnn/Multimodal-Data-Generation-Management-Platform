"""Map DataType recipe.graph + runtime pipeline_step rows to UI progress cards.

The local worker still records coarse SDK phases (sdk_infer / sqlite / oss / dispatch).
Execution-queue display expands sdk_infer into the authored DAG work nodes so the
flow matches the DataType canvas. Persist/upload/dispatch are every-clip infra and
are not shown as pipeline steps.
"""

from __future__ import annotations

from typing import Any

from hmi.config import pipeline_step_label, sdk_pipeline_step_order
from hmi.db import normalize_pipeline_status

_SKIP_NODE_TYPES = frozenset({"if", "review", "export", "source"})
_HIDDEN_INFRA = frozenset({"sdk_mc_write", "sdk_upload", "sdk_dispatch"})


def load_recipe_graph(data_type_id: str | None) -> dict[str, Any] | None:
    if not data_type_id or not str(data_type_id).strip():
        return None
    try:
        from hmi.platform.store import get_data_type

        rec = get_data_type(str(data_type_id).strip())
    except Exception:
        return None
    graph = (rec or {}).get("graph") if isinstance(rec, dict) else None
    if isinstance(graph, dict) and graph.get("nodes"):
        return graph
    return None


def graph_work_nodes(graph: dict[str, Any] | None) -> list[dict[str, str]]:
    """Topo-ordered op/label nodes (skip source / if / review / export)."""
    if not isinstance(graph, dict) or not graph.get("nodes"):
        return []
    raw_nodes = [n for n in (graph.get("nodes") or []) if isinstance(n, dict) and n.get("key")]
    by_key = {str(n["key"]): n for n in raw_nodes}
    try:
        from hmi.platform.recipe_graph import ordered_node_keys, validate_graph

        g = validate_graph(graph)
        keys = ordered_node_keys(g)
        by_key = {str(n["key"]): n for n in g["nodes"]}
    except Exception:
        keys = [str(n["key"]) for n in raw_nodes]
    out: list[dict[str, str]] = []
    for key in keys:
        node = by_key.get(key)
        if not node:
            continue
        ntype = str(node.get("type") or "")
        if ntype in _SKIP_NODE_TYPES:
            continue
        op_id = str(node.get("op_id") or ntype).strip() or ntype
        title = str(node.get("title") or "").strip() or op_id
        try:
            from hmi.platform.operators import display_op_title

            title = display_op_title(op_id, title)
        except Exception:
            if op_id == "label" and title in {"打标器", "label", "labeler"}:
                title = "AI打标器"
        out.append({"key": key, "op_id": op_id, "title": title})
    return out


def _row_status(row: dict[str, Any] | None) -> str:
    return normalize_pipeline_status(str((row or {}).get("status") or "pending"))


def _row_error(row: dict[str, Any] | None) -> str | None:
    msg = str((row or {}).get("error_message") or "").strip()
    return msg or None


def _runtime_card(step_id: str, step_map: dict[str, dict[str, Any]], *, local: bool) -> dict[str, Any]:
    row = step_map.get(step_id) or {}
    return {
        "step_id": step_id,
        "label": pipeline_step_label(step_id, local=local),
        "status": _row_status(row),
        "error_message": _row_error(row),
    }


def _infer_onto_dag(
    nodes: list[dict[str, str]],
    infer: dict[str, Any] | None,
    step_map: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    status = _row_status(infer)
    err = _row_error(infer)
    step_map = step_map or {}
    cards: list[dict[str, Any]] = []
    running_claimed = False
    for i, node in enumerate(nodes):
        per = step_map.get(f"dag:{node['key']}")
        if per:
            cards.append(
                {
                    "step_id": f"dag:{node['key']}",
                    "label": node["title"],
                    "status": _row_status(per),
                    "error_message": _row_error(per),
                }
            )
            continue
        card_status = "pending"
        card_err: str | None = None
        if status in {"success", "completed"}:
            card_status = "success"
        elif status == "skipped":
            card_status = "skipped"
        elif status == "failed":
            if i == 0:
                card_status = "failed"
                card_err = err
        elif status == "cancelled":
            if i == 0:
                card_status = "cancelled"
        elif status == "running":
            if not running_claimed:
                card_status = "running"
                running_claimed = True
        cards.append(
            {
                "step_id": f"dag:{node['key']}",
                "label": node["title"],
                "status": card_status,
                "error_message": card_err,
            }
        )
    return cards


def _first_failed_infra(step_map: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for sid in ("sdk_mc_write", "sdk_upload", "sdk_dispatch"):
        row = step_map.get(sid)
        if _row_status(row) == "failed":
            return row
    return None


def _attach_hidden_infra_failure(cards: list[dict[str, Any]], infra: dict[str, Any] | None) -> None:
    """Persist/upload failures must not look like the first DAG op (parser) failed."""
    if not cards or not infra:
        return
    last = cards[-1]
    if last["status"] in {"failed", "cancelled"}:
        if not last.get("error_message"):
            last["error_message"] = _row_error(infra)
        return
    last["status"] = "failed"
    last["error_message"] = _row_error(infra)


def _looks_like_import_failure(*rows: dict[str, Any] | None) -> bool:
    blob = " ".join((_row_error(r) or "") for r in rows)
    return "no importable runs" in blob or "导入失败" in blob


def expand_progress_steps(
    *,
    graph: dict[str, Any] | None,
    step_map: dict[str, dict[str, Any]] | None,
    local: bool = True,
) -> list[dict[str, Any]]:
    """Build UI steps from DAG work nodes (or sdk_infer). Hide sqlite/OSS/dispatch."""
    step_map = step_map or {}
    order = sdk_pipeline_step_order(local=local)
    work = graph_work_nodes(graph)
    infer = step_map.get("sdk_infer")
    infra_fail = _first_failed_infra(step_map)
    infer_status = _row_status(infer)
    infer_ok = infer_status in {"success", "completed"}
    # Worker used to copy import errors onto sdk_infer; treat those as ingest, not parse.
    import_fail = _looks_like_import_failure(infer, infra_fail)
    if not work:
        cards = [
            _runtime_card(sid, step_map, local=local)
            for sid in order
            if sid not in ("job0_discover", "sdk_discover") and sid not in _HIDDEN_INFRA
        ]
        if infer_ok or (infer_status == "failed" and import_fail):
            _attach_hidden_infra_failure(cards, infra_fail or infer)
        return cards
    if infer_status == "failed" and import_fail:
        dag_cards = _infer_onto_dag(
            work, {**(infer or {}), "status": "success", "error_message": None}, step_map
        )
        _attach_hidden_infra_failure(dag_cards, infra_fail or infer)
        return dag_cards
    dag_cards = _infer_onto_dag(work, infer, step_map)
    if infer_ok:
        _attach_hidden_infra_failure(dag_cards, infra_fail)
    return dag_cards


def expand_progress_steps_for_type(
    *,
    data_type_id: str | None,
    step_map: dict[str, dict[str, Any]] | None,
    local: bool = True,
    graph_cache: dict[str, dict[str, Any] | None] | None = None,
) -> list[dict[str, Any]]:
    graph: dict[str, Any] | None = None
    key = str(data_type_id or "").strip()
    if key:
        if graph_cache is not None and key in graph_cache:
            graph = graph_cache[key]
        else:
            graph = load_recipe_graph(key)
            if graph_cache is not None:
                graph_cache[key] = graph
    return expand_progress_steps(graph=graph, step_map=step_map, local=local)
