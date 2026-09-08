"""Publish DAG labels to fact_clip_label using the DataType's bound taxonomy."""

from __future__ import annotations

from typing import Any

_NVH_TAXONOMY_IDS = {"audio_nvh"}
_NVH_VERSION_PREFIXES = ("audio_nvh",)


def recipe_uses_nvh_taxonomy(recipe: dict[str, Any] | None) -> bool:
    if not isinstance(recipe, dict):
        return False
    tid = str(recipe.get("taxonomy_id") or "").strip()
    if tid in _NVH_TAXONOMY_IDS:
        return True
    code = str(recipe.get("taxonomy_version_code") or "").strip()
    return any(code == p or code.startswith(f"{p}-") or code.startswith(f"{p}_") for p in _NVH_VERSION_PREFIXES)


def graph_ctx_labels(ctx: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(ctx, dict):
        return None
    for key in ("labels", "labels_tree"):
        raw = ctx.get(key)
        if not isinstance(raw, dict) or not raw:
            continue
        values = raw.get("values")
        if isinstance(values, dict) and values:
            return raw
        if any(k != "_meta" for k in raw):
            return raw
    return None


def decide_graph_label_publish(recipe: dict[str, Any] | None, ctx: dict[str, Any] | None) -> str:
    """Return ``nvh`` | ``recipe`` | ``none``."""
    if recipe_uses_nvh_taxonomy(recipe):
        return "nvh"
    if graph_ctx_labels(ctx):
        return "recipe"
    return "none"


def persist_recipe_clip_labels(
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    recipe: dict[str, Any] | None,
    labels: dict[str, Any],
    data_type_id: str | None = None,
) -> str | None:
    """Write clip facts for the recipe taxonomy. Returns taxonomy_version_id."""
    from hmi.clip_facts import upsert_clip_label
    from hmi.platform.store import put_run_y
    from hmi.taxonomy.data_type_bind import resolve_taxonomy_version_for_data_type

    dt_id = str(data_type_id or (recipe or {}).get("id") or "").strip()
    version = resolve_taxonomy_version_for_data_type(dt_id) if dt_id else None
    tax_vid = str(version["id"]) if version else None
    tax_code = str(version.get("version_code") or "") if version else ""
    payload = dict(labels)
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    meta = dict(meta)
    if tax_code:
        meta["taxonomy_version_code"] = tax_code
    if tax_vid:
        meta["taxonomy_version_id"] = tax_vid
    payload["_meta"] = meta
    upsert_clip_label(
        clip_id,
        run_id,
        ds=ds,
        labels_json=payload,
        taxonomy_version_id=tax_vid,
        model_version="label_tree_input",
        label_source="graph",
        multi_ai_meta_json={
            "layout_version": "recipe_graph",
            "taxonomy_version_code": tax_code or None,
            "taxonomy_version_id": tax_vid,
        },
    )
    try:
        put_run_y(run_id, payload)
    except Exception:
        pass
    return tax_vid
