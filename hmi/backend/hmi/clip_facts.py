"""Clip-level label and embedding facts (future pipeline + legacy fallback)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from hmi.clip_consensus import attach_consensus_fields, parse_multi_ai_meta
from hmi.labels_util import has_label_content, label_value_ids, labels_preview, labels_to_clip_dict, parse_labels_json
from hmi.local import store
from hmi.local.clip_context import resolve_ds_for_run

CLIP_LABEL_STEP_IDS = (
    "job4_label_merge_and_compare",
    "job2_clip_omni",
    "job_clip_label",
    "job3_clip_label",
    "job3_label",
)
CLIP_EMBED_STEP_IDS = ("job2_embedding", "job2_clip_omni", "job_clip_embed", "job4_clip_embed", "job4_embed")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_has_clip_labels(raw: str | None) -> bool:
    return has_label_content(parse_labels_json(raw))


def _try_scene_summary(clip_id: str, run_id: str) -> str | None:
    try:
        from hmi.ai_artifacts import load_ai_labels_local

        doc = load_ai_labels_local(clip_id, run_id)
        if doc:
            raw = doc.get("scene_summary")
            if raw is not None and str(raw).strip():
                return str(raw).strip()
    except Exception:
        pass

    try:
        from hmi.data_source import artifact_path
        from hmi.oss_layout import SDK_LABELS_JSONL
        from hmi.sdk_ingest import read_jsonl_first

        labels_path = artifact_path(clip_id, run_id, SDK_LABELS_JSONL)
        if labels_path.is_file():
            row = read_jsonl_first(labels_path)
            raw = row.get("scene_summary")
            if raw is not None and str(raw).strip():
                return str(raw).strip()
    except Exception:
        pass
    return None


def _resolve_clip_taxonomy_version_id(
    row: dict[str, Any] | None,
    *,
    parsed_labels: dict[str, Any],
    flat_labels: dict[str, Any],
) -> str | None:
    if row:
        raw_tid = row.get("taxonomy_version_id")
        if raw_tid and str(raw_tid).strip():
            return str(raw_tid).strip()

    label_ids = list(flat_labels.keys()) if flat_labels else label_value_ids(parsed_labels)
    if not label_ids:
        return None

    preferred: str | None = None
    try:
        from hmi.local.pipeline_settings import get_pipeline_settings

        raw = get_pipeline_settings().get("taxonomy_version_id")
        if raw and str(raw).strip():
            preferred = str(raw).strip()
    except Exception:
        preferred = None

    from hmi.taxonomy_db import resolve_taxonomy_version_for_label_ids

    version = resolve_taxonomy_version_for_label_ids(
        label_ids,
        preferred_version_id=preferred,
    )
    return str(version["id"]) if version else None


def _attach_taxonomy_version(view: dict[str, Any], row: dict[str, Any] | None, parsed: dict[str, Any]) -> dict[str, Any]:
    flat = view.get("labels_json") if isinstance(view.get("labels_json"), dict) else {}
    tid = _resolve_clip_taxonomy_version_id(row, parsed_labels=parsed, flat_labels=flat)
    if not tid:
        return view
    out = dict(view)
    out["taxonomy_version_id"] = tid
    try:
        from hmi.taxonomy_db import resolve_taxonomy_display_for_version_id

        code = resolve_taxonomy_display_for_version_id(tid)
        if code:
            out["taxonomy_version_code"] = code
    except Exception:
        pass
    return out


def _with_scene_summary(view: dict[str, Any], clip_id: str, run_id: str) -> dict[str, Any]:
    summary = _try_scene_summary(clip_id, run_id)
    if not summary:
        return view
    out = dict(view)
    out["scene_summary"] = summary
    return out


def get_clip_label_row(
    clip_id: str,
    run_id: str,
    *,
    ds: str | None = None,
) -> dict[str, Any] | None:
    resolved_ds = ds or resolve_ds_for_run(clip_id, run_id)
    return store.query_one(
        """
        SELECT * FROM fact_clip_label
        WHERE clip_id=? AND run_id=? AND ds=?
        """,
        (clip_id, run_id, resolved_ds),
    )


def get_clip_embedding_row(
    clip_id: str,
    run_id: str,
    *,
    ds: str | None = None,
) -> dict[str, Any] | None:
    resolved_ds = ds or resolve_ds_for_run(clip_id, run_id)
    return store.query_one(
        """
        SELECT * FROM fact_clip_embedding
        WHERE clip_id=? AND run_id=? AND ds=?
        """,
        (clip_id, run_id, resolved_ds),
    )


def detect_label_granularity(clip_id: str, run_id: str, *, ds: str | None = None) -> str:
    """Return ``clip`` when clip-level facts exist, else ``frame`` (legacy)."""
    if get_clip_label_row(clip_id, run_id, ds=ds):
        return "clip"
    resolved_ds = ds or resolve_ds_for_run(clip_id, run_id)
    run = store.query_one(
        "SELECT label_granularity FROM pipeline_run WHERE clip_id=? AND run_id=? AND ds=?",
        (clip_id, run_id, resolved_ds),
    )
    gran = str(run.get("label_granularity") or "").strip().lower() if run else ""
    if gran in ("clip", "frame"):
        return gran
    return "frame"


def _step_succeeded(clip_id: str, run_id: str, ds: str, step_ids: tuple[str, ...]) -> bool:
    placeholders = ",".join("?" for _ in step_ids)
    row = store.query_one(
        f"""
        SELECT status FROM pipeline_step
        WHERE run_id=? AND clip_id=? AND ds=? AND step_id IN ({placeholders})
        ORDER BY finished_at DESC
        LIMIT 1
        """,
        (run_id, clip_id, ds, *step_ids),
    )
    if not row:
        return False
    status = str(row.get("status") or "").lower()
    return status in ("success", "completed")


def is_clip_label_ready(clip_id: str, run_id: str, *, ds: str | None = None) -> bool:
    resolved_ds = ds or resolve_ds_for_run(clip_id, run_id)
    row = get_clip_label_row(clip_id, run_id, ds=resolved_ds)
    if row and _row_has_clip_labels(str(row.get("labels_json") or "")):
        return True
    if _step_succeeded(clip_id, run_id, resolved_ds, CLIP_LABEL_STEP_IDS):
        return True
    labeled = store.query_one(
        """
        SELECT COUNT(*) AS cnt FROM fact_image_label
        WHERE clip_id=? AND run_id=? AND ds=?
          AND labels_json IS NOT NULL AND labels_json != '' AND labels_json != '{}'
        """,
        (clip_id, run_id, resolved_ds),
    )
    return bool(labeled and int(labeled["cnt"]) > 0)


def clip_label_stats(clip_id: str, run_id: str, *, ds: str | None = None) -> dict[str, Any]:
    """Clip-centric label counters for overview (0/1 labeled, always 1 sample unit)."""
    view = get_clip_label_view(clip_id, run_id, ds=ds)
    ready = bool(view.get("clip_label_ready"))
    return {
        "label_granularity": view.get("label_granularity") or "frame",
        "clip_label_ready": ready,
        "labeled_count": 1 if ready else 0,
        "sampled_count": 1,
        "clip_label_preview": str(view.get("label_preview") or ""),
    }


def get_clip_label_view(clip_id: str, run_id: str, *, ds: str | None = None) -> dict[str, Any]:
    """Unified clip-level label view for browse, search, and timeline."""
    resolved_ds = ds or resolve_ds_for_run(clip_id, run_id)
    row = get_clip_label_row(clip_id, run_id, ds=resolved_ds)
    if row and (
        _row_has_clip_labels(str(row.get("labels_json") or ""))
        or parse_multi_ai_meta(row.get("multi_ai_meta_json"))
    ):
        parsed = parse_labels_json(row.get("labels_json"))
        anchor = row.get("anchor_timestamp_ns")
        labels_json = labels_to_clip_dict(row.get("labels_json"))
        if not labels_json and parsed:
            labels_json = parsed
        view = {
            "label_granularity": "clip",
            "clip_label_ready": True,
            "labels_json": labels_json if isinstance(labels_json, dict) else {},
            "label_preview": labels_preview(parsed),
            "anchor_timestamp_ns": int(anchor) if anchor is not None else None,
            "source": "fact_clip_label",
            "aggregation": "clip_native",
        }
        view = _attach_taxonomy_version(view, dict(row), parsed)
        return _with_scene_summary(attach_consensus_fields(view, row), clip_id, run_id)

    granularity = detect_label_granularity(clip_id, run_id, ds=resolved_ds)
    try:
        from hmi.review.aggregate import aggregate_clip_labels

        agg = aggregate_clip_labels(clip_id, run_id, ds=resolved_ds)
        summary = agg.get("ai_source_summary_json") or {}
        return {
            "label_granularity": "frame",
            "clip_label_ready": bool(agg.get("labels_json")),
            "labels_json": agg.get("labels_json") or {},
            "label_preview": str(summary.get("label_preview") or ""),
            "anchor_timestamp_ns": summary.get("anchor_timestamp_ns"),
            "source": "fact_image_label",
            "aggregation": agg.get("aggregation"),
        }
    except ValueError:
        pass

    return {
        "label_granularity": granularity,
        "clip_label_ready": False,
        "labels_json": {},
        "label_preview": "",
        "anchor_timestamp_ns": None,
        "source": None,
        "aggregation": None,
    }


def get_clip_label_view_for_queue(
    clip_id: str, run_id: str, *, ds: str | None = None
) -> dict[str, Any] | None:
    """Clip-native labels only (no frame aggregation) for review v2 queue."""
    resolved_ds = ds or resolve_ds_for_run(clip_id, run_id)
    row = get_clip_label_row(clip_id, run_id, ds=resolved_ds)
    if not row or not (
        _row_has_clip_labels(str(row.get("labels_json") or ""))
        or parse_multi_ai_meta(row.get("multi_ai_meta_json"))
    ):
        return None
    parsed = parse_labels_json(row.get("labels_json"))
    anchor = row.get("anchor_timestamp_ns")
    labels_json = labels_to_clip_dict(row.get("labels_json"))
    if not labels_json and parsed:
        labels_json = parsed
    view = {
        "label_granularity": "clip",
        "clip_label_ready": True,
        "labels_json": labels_json if isinstance(labels_json, dict) else {},
        "label_preview": labels_preview(parsed),
        "anchor_timestamp_ns": int(anchor) if anchor is not None else None,
        "source": "fact_clip_label",
        "aggregation": "clip_native",
    }
    view = _attach_taxonomy_version(view, dict(row), parsed)
    return attach_consensus_fields(view, row)


def resolve_clip_thumbnail(
    clip_id: str,
    run_id: str,
    ds: str,
    anchor_timestamp_ns: int | None = None,
) -> dict[str, Any] | None:
    if anchor_timestamp_ns is not None:
        row = store.query_one(
            """
            SELECT camera, frame_idx, image_path, timestamp_ns
            FROM fact_frame
            WHERE clip_id=? AND run_id=? AND ds=?
            ORDER BY ABS(timestamp_ns - ?) ASC
            LIMIT 1
            """,
            (clip_id, run_id, ds, anchor_timestamp_ns),
        )
    else:
        row = store.query_one(
            """
            SELECT camera, frame_idx, image_path, timestamp_ns
            FROM fact_frame
            WHERE clip_id=? AND run_id=? AND ds=?
            ORDER BY timestamp_ns ASC
            LIMIT 1
            """,
            (clip_id, run_id, ds),
        )
    return row


def list_clip_label_candidates() -> list[dict[str, str]]:
    rows = store.query(
        """
        SELECT DISTINCT clip_id, run_id FROM fact_clip_label
        WHERE (
          labels_json IS NOT NULL AND labels_json != '' AND labels_json != '{}'
        ) OR (
          multi_ai_meta_json IS NOT NULL AND multi_ai_meta_json != '' AND multi_ai_meta_json != '{}'
        )
        UNION
        SELECT DISTINCT clip_id, run_id FROM fact_image_label
        WHERE labels_json IS NOT NULL AND labels_json != '' AND labels_json != '{}'
        """
    )
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row["clip_id"]), str(row["run_id"]))
        if key in seen:
            continue
        seen.add(key)
        out.append({"clip_id": key[0], "run_id": key[1]})
    return out


def resolve_clip_labels_for_enqueue(
    clip_id: str,
    run_id: str,
    *,
    ds: str | None = None,
) -> dict[str, Any]:
    """Prefer native clip label row; fallback to frame aggregation (legacy)."""
    row = get_clip_label_row(clip_id, run_id, ds=ds)
    if row and (
        _row_has_clip_labels(str(row.get("labels_json") or ""))
        or parse_multi_ai_meta(row.get("multi_ai_meta_json"))
    ):
        parsed = parse_labels_json(row.get("labels_json"))
        labels_json = labels_to_clip_dict(str(row.get("labels_json") or ""))
        if not labels_json and parsed:
            labels_json = parsed
        if not labels_json and isinstance(parsed, dict):
            labels_json = parsed
        summary: dict[str, Any] = {
            "source": "fact_clip_label",
            "aggregation": "clip_native",
            "label_preview": labels_preview(parsed),
            "taxonomy_version_id": row.get("taxonomy_version_id"),
            "model_version": row.get("model_version"),
            "label_source": row.get("label_source") or "ai",
            "total_rows": 1,
            "labeled_rows": 1,
        }
        if row.get("anchor_timestamp_ns") is not None:
            summary["anchor_timestamp_ns"] = int(row["anchor_timestamp_ns"])
        meta = parse_multi_ai_meta(row.get("multi_ai_meta_json"))
        if meta:
            summary["multi_ai_meta"] = meta
            view_stub = attach_consensus_fields({}, row)
            summary["disputed_label_ids"] = view_stub.get("disputed_label_ids") or []
            summary["dispute_count"] = view_stub.get("dispute_count") or 0
            summary["multi_ai_gate"] = view_stub.get("multi_ai_gate")
            summary["label_consensus"] = view_stub.get("label_consensus") or {}
        return {
            "labels_json": labels_json,
            "ai_source_summary_json": summary,
            "aggregation": "clip_native",
            "taxonomy_version_id": row.get("taxonomy_version_id"),
        }
    labels_doc = None
    try:
        from hmi.ai_artifacts import load_ai_labels_local

        labels_doc = load_ai_labels_local(clip_id, run_id)
    except ImportError:
        pass
    if labels_doc:
        if "labels_json" in labels_doc:
            raw_labels = labels_doc["labels_json"]
        elif "labels" in labels_doc:
            raw_labels = labels_doc["labels"]
        else:
            raw_labels = None
        if isinstance(raw_labels, dict):
            labels_json = labels_to_clip_dict(raw_labels) or raw_labels
            parsed = parse_labels_json(raw_labels)
            summary: dict[str, Any] = {
                "source": "ai/labels_merged.json",
                "aggregation": "dual_model_merge",
                "label_preview": labels_preview(parsed),
                "taxonomy_version_id": labels_doc.get("taxonomy_version_id"),
                "model_version": labels_doc.get("model_version"),
                "label_source": labels_doc.get("label_source") or "ai",
                "total_rows": 1,
                "labeled_rows": 1,
                "gate_passed": labels_doc.get("gate_passed"),
                "clip_agreement": labels_doc.get("clip_agreement"),
            }
            meta = labels_doc.get("multi_ai_meta")
            if isinstance(meta, dict):
                summary["multi_ai_meta"] = meta
                view_stub = attach_consensus_fields({}, {"multi_ai_meta_json": meta})
                summary["disputed_label_ids"] = view_stub.get("disputed_label_ids") or []
                summary["dispute_count"] = view_stub.get("dispute_count") or 0
                summary["multi_ai_gate"] = view_stub.get("multi_ai_gate")
                summary["label_consensus"] = view_stub.get("label_consensus") or {}
            return {
                "labels_json": labels_json,
                "ai_source_summary_json": summary,
                "aggregation": "dual_model_merge",
                "taxonomy_version_id": labels_doc.get("taxonomy_version_id"),
            }
    from hmi.review.aggregate import aggregate_clip_labels

    legacy = aggregate_clip_labels(clip_id, run_id, ds=ds)
    legacy["taxonomy_version_id"] = None
    return legacy


def upsert_clip_label(
    clip_id: str,
    run_id: str,
    *,
    ds: str,
    labels_json: dict[str, Any] | str,
    taxonomy_version_id: str | None = None,
    model_version: str | None = None,
    label_source: str = "ai",
    anchor_timestamp_ns: int | None = None,
    multi_ai_meta_json: dict[str, Any] | str | None = None,
) -> None:
    now = _utc_now_iso()
    payload = labels_json if isinstance(labels_json, str) else json.dumps(labels_json, ensure_ascii=False)
    meta_payload: str | None
    if multi_ai_meta_json is None:
        meta_payload = None
    elif isinstance(multi_ai_meta_json, str):
        meta_payload = multi_ai_meta_json
    else:
        meta_payload = json.dumps(multi_ai_meta_json, ensure_ascii=False)
    store.execute(
        """
        INSERT INTO fact_clip_label (
          clip_id, run_id, ds, labels_json, taxonomy_version_id, model_version,
          label_source, anchor_timestamp_ns, multi_ai_meta_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(clip_id, run_id, ds) DO UPDATE SET
          labels_json=excluded.labels_json,
          taxonomy_version_id=excluded.taxonomy_version_id,
          model_version=excluded.model_version,
          label_source=excluded.label_source,
          anchor_timestamp_ns=excluded.anchor_timestamp_ns,
          multi_ai_meta_json=excluded.multi_ai_meta_json,
          updated_at=excluded.updated_at
        """,
        (
            clip_id,
            run_id,
            ds,
            payload,
            taxonomy_version_id,
            model_version,
            label_source,
            anchor_timestamp_ns,
            meta_payload,
            now,
            now,
        ),
    )
    store.execute(
        """
        UPDATE pipeline_run SET label_granularity='clip', updated_at=?
        WHERE clip_id=? AND run_id=? AND ds=?
        """,
        (now, clip_id, run_id, ds),
    )


def upsert_clip_embedding(
    clip_id: str,
    run_id: str,
    *,
    ds: str,
    vector: list[float],
    model_version: str | None = None,
    aggregation_method: str = "clip_native",
) -> None:
    now = _utc_now_iso()
    store.execute(
        """
        INSERT INTO fact_clip_embedding (
          clip_id, run_id, ds, vector_json, dim, model_version,
          aggregation_method, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(clip_id, run_id, ds) DO UPDATE SET
          vector_json=excluded.vector_json,
          dim=excluded.dim,
          model_version=excluded.model_version,
          aggregation_method=excluded.aggregation_method,
          updated_at=excluded.updated_at
        """,
        (
            clip_id,
            run_id,
            ds,
            json.dumps(vector),
            len(vector),
            model_version,
            aggregation_method,
            now,
            now,
        ),
    )
