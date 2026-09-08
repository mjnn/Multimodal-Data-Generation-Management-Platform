"""Write human L6 semantic NVH labels into facts + nvh_labels.json.

Never calls ``publish_version``. Objective ``nvh.clip.`` / ``nvh.ch.`` / …
leaves are not overwritten.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from hmi.clip_facts import get_clip_label_row
from hmi.labels_util import parse_labels_json
from hmi.local.clip_context import resolve_ds_for_run
from hmi.local.nvh_ai_label import (
    SEMANTIC_KEYS,
    merge_nvh_semantic_labels,
    resolve_audio_nvh_taxonomy_version_id,
)
from hmi.local.nvh_deriver import apply_nvh_labels_to_facts, persist_nvh_labels_artifact


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def looks_like_nvh_labels(labels: dict[str, Any] | None) -> bool:
    if not isinstance(labels, dict):
        return False
    return any(str(k).startswith("nvh.") for k in labels if not str(k).startswith("_"))


def semantic_patch(labels_json: Any) -> dict[str, Any]:
    """Extract L6 keys only. Nested OMS ``values`` payloads are ignored."""
    if not isinstance(labels_json, dict):
        return {}
    if "values" in labels_json and isinstance(labels_json.get("values"), dict):
        nested = labels_json["values"]
        if any(str(k).startswith("nvh.sem.") for k in nested):
            return {k: v for k, v in nested.items() if k in SEMANTIC_KEYS}
        return {}
    return {k: v for k, v in labels_json.items() if k in SEMANTIC_KEYS}


def queue_label_ids(label_ids: list[str]) -> list[str]:
    """Confidence queue: NVH clips only enqueue ``nvh.sem.*`` (not objective leaves)."""
    ids = [str(i) for i in label_ids if not str(i).startswith("_")]
    if any(i.startswith("nvh.") for i in ids):
        return [i for i in ids if i.startswith("nvh.sem.")]
    return ids


def rollup_label_ids(clip_id: str, run_id: str) -> list[str]:
    from hmi.review.merge import get_ai_label_ids

    return queue_label_ids(get_ai_label_ids(clip_id, run_id))


def prefer_nvh_taxonomy_id(labels: dict[str, Any] | None, current: str | None) -> str | None:
    """Prefer clip taxonomy; NVH facts fall back to draft ``audio_nvh-v2``, never publish."""
    cur = str(current or "").strip() or None
    if cur:
        return cur
    if looks_like_nvh_labels(labels):
        return resolve_audio_nvh_taxonomy_version_id()
    return None


def writeback_nvh_l6(
    *,
    clip_id: str,
    run_id: str,
    labels_json: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge SEMANTIC_KEYS into fact_clip_label + nvh_labels.json. OMS → None."""
    patch = semantic_patch(labels_json)
    if not patch:
        return None
    try:
        ds = resolve_ds_for_run(clip_id, run_id)
    except ValueError:
        return None
    row = get_clip_label_row(clip_id, run_id, ds=ds)
    if not row:
        return None
    base = parse_labels_json(row.get("labels_json"))
    if not looks_like_nvh_labels(base):
        return None
    merged = merge_nvh_semantic_labels(base, patch)
    meta = dict(merged.get("_meta") or {})
    src = str(meta.get("label_source") or "")
    if "human" not in src:
        meta["label_source"] = f"{src}+human" if src else "human"
    meta["human_reviewed_at"] = _utc_now_iso()
    meta["human_semantic_keys"] = sorted(patch.keys())
    merged["_meta"] = meta

    from hmi.data_source import artifacts_dir

    root = artifacts_dir(clip_id, run_id)
    root.mkdir(parents=True, exist_ok=True)
    persist_nvh_labels_artifact(root, merged)
    apply_nvh_labels_to_facts(
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        labels=merged,
        update_platform_run=True,
    )
    return merged
