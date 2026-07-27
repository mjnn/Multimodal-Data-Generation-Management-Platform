"""Dataset snapshot assembly from reviewed clips."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from hmi.app_db import db_conn
from hmi.clip_facts import get_clip_embedding_row, is_clip_label_ready, list_clip_label_candidates
from hmi.clip_facts import resolve_clip_labels_for_enqueue
from hmi.data_source import is_local_mode
from hmi.dataset_db import DEFAULT_FILTER
from hmi.local import store
from hmi.local.clip_context import resolve_ds_for_run
from hmi.labels_util import match_label_filters
from hmi.review_db import REVIEW_STATUSES, _review_row, get_review
from hmi.taxonomy_db import get_published_version, get_version
from hmi.vec import parse_embedding

MAX_CLIP_COUNT = 10_000


@dataclass
class AssemblyResult:
    rows: list[dict[str, Any]]
    clip_count: int
    skipped: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def normalize_filter(filter_json: dict[str, Any] | None) -> dict[str, Any]:
    base = dict(DEFAULT_FILTER)
    if filter_json:
        base.update(filter_json)
    if base.get("clip_ids") == []:
        base["clip_ids"] = None
    label_filters = base.get("label_filters")
    if isinstance(label_filters, dict):
        cleaned = {
            str(k).strip(): v
            for k, v in label_filters.items()
            if str(k).strip() and v is not None and v != ""
        }
        base["label_filters"] = cleaned or None
    else:
        base["label_filters"] = None
    sample_size = base.get("sample_size")
    if sample_size is not None and sample_size != "":
        n = int(sample_size)
        if n <= 0:
            raise ValueError("sample_size must be positive")
        base["sample_size"] = n
    else:
        base["sample_size"] = None
    return base


def apply_sample(reviews: list[dict[str, Any]], filt: dict[str, Any]) -> list[dict[str, Any]]:
    sample_size = filt.get("sample_size")
    if not sample_size:
        return reviews
    n = int(sample_size)
    if len(reviews) <= n:
        return reviews
    return random.sample(reviews, n)


def _allowed_statuses(filter_json: dict[str, Any]) -> tuple[str, ...]:
    if filter_json.get("include_pending_review"):
        return ("reviewed", "pending_review")
    status = str(filter_json.get("review_status") or "reviewed").strip()
    if status not in REVIEW_STATUSES:
        raise ValueError(f"invalid review_status in filter: {status}")
    return (status,)


def _apply_field_review_gate(reviews: list[dict[str, Any]], filt: dict[str, Any]) -> list[dict[str, Any]]:
    if filt.get("include_pending_review"):
        return reviews
    from hmi.review.merge import all_ai_labels_field_reviewed

    return [
        r
        for r in reviews
        if all_ai_labels_field_reviewed(str(r["clip_id"]), str(r["run_id"]))
    ]


def _local_ai_labeled_pool(filt: dict[str, Any], *, allow_unreviewed: bool = False) -> list[dict[str, Any]]:
    """Local HMI: clips with AI labels + embedding but no clip_label_review row yet."""
    if not is_local_mode():
        return []
    include_pending = bool(filt.get("include_pending_review"))
    allow_unreviewed = allow_unreviewed or include_pending
    statuses = set(_allowed_statuses(filt))
    label_filters = filt.get("label_filters")
    published = get_published_version()
    default_taxonomy = published["id"] if published else None

    out: list[dict[str, Any]] = []
    for pair in list_clip_label_candidates():
        clip_id = str(pair["clip_id"])
        run_id = str(pair["run_id"])
        if not is_clip_label_ready(clip_id, run_id):
            continue
        if fetch_clip_feature_local(clip_id, run_id) is None:
            continue

        review = get_review(clip_id, run_id)
        if review:
            status = str(review.get("review_status") or "")
            if status not in statuses:
                continue
            row = review
        else:
            if not allow_unreviewed:
                continue
            try:
                payload = resolve_clip_labels_for_enqueue(clip_id, run_id)
            except ValueError:
                continue
            labels_json = payload.get("labels_json") or {}
            row = {
                "clip_id": clip_id,
                "run_id": run_id,
                "review_status": "pending_review",
                "labels_json": labels_json,
                "taxonomy_version_id": payload.get("taxonomy_version_id") or default_taxonomy,
            }

        if label_filters and not match_label_filters(row.get("labels_json"), label_filters):
            continue
        out.append(row)
    return out


def query_review_pool(filter_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    filt = normalize_filter(filter_json)
    statuses = _allowed_statuses(filt)
    placeholders = ",".join("?" for _ in statuses)
    sql = f"""
        SELECT * FROM clip_label_review
        WHERE review_status IN ({placeholders})
    """
    params: list[Any] = list(statuses)

    clip_ids = filt.get("clip_ids")
    if clip_ids:
        ids = [str(c).strip() for c in clip_ids if str(c).strip()]
        if ids:
            id_placeholders = ",".join("?" for _ in ids)
            sql += f" AND clip_id IN ({id_placeholders})"
            params.extend(ids)

    taxonomy_version_id = filt.get("taxonomy_version_id")
    if taxonomy_version_id:
        sql += " AND taxonomy_version_id = ?"
        params.append(str(taxonomy_version_id).strip())

    sql += " ORDER BY updated_at DESC"

    with db_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    reviews = [_review_row(r) for r in rows]

    label_filters = filt.get("label_filters")
    if label_filters:
        reviews = [
            r
            for r in reviews
            if match_label_filters(r.get("labels_json"), label_filters)
        ]

    reviews = _apply_field_review_gate(reviews, filt)

    if reviews:
        return reviews

    if is_local_mode():
        return _local_ai_labeled_pool(filt, allow_unreviewed=True)

    return []


def query_review_candidates(filter_json: dict[str, Any] | None) -> list[dict[str, Any]]:
    filt = normalize_filter(filter_json)
    pool = query_review_pool(filt)
    return apply_sample(pool, filt)


def fetch_frame_embeddings_local(clip_id: str, run_id: str) -> list[dict[str, Any]]:
    try:
        ds = resolve_ds_for_run(clip_id, run_id)
    except ValueError:
        return []
    emb_rows = store.query(
        """
        SELECT object_type, object_id, timestamp_ns, start_ns, end_ns,
               vector_json, model_version, dim
        FROM fact_embedding
        WHERE clip_id=? AND run_id=? AND ds=?
        ORDER BY timestamp_ns ASC, object_id ASC
        """,
        (clip_id, run_id, ds),
    )
    out: list[dict[str, Any]] = []
    for row in emb_rows:
        vec = parse_embedding(str(row.get("vector_json") or ""))
        if vec is None:
            continue
        out.append(
            {
                "object_type": str(row.get("object_type") or ""),
                "object_id": str(row.get("object_id") or ""),
                "timestamp_ns": int(row["timestamp_ns"]) if row.get("timestamp_ns") is not None else None,
                "start_ns": int(row["start_ns"]) if row.get("start_ns") is not None else None,
                "end_ns": int(row["end_ns"]) if row.get("end_ns") is not None else None,
                "vector": vec.tolist(),
                "model_version": row.get("model_version"),
                "dim": int(row["dim"]) if row.get("dim") is not None else len(vec),
            }
        )
    return out


def fetch_clip_feature_local(clip_id: str, run_id: str) -> dict[str, Any] | None:
    """Prefer clip-level embedding; fallback to legacy frame/object embeddings."""
    try:
        ds = resolve_ds_for_run(clip_id, run_id)
    except ValueError:
        return None

    row = get_clip_embedding_row(clip_id, run_id, ds=ds)
    if row:
        vec = parse_embedding(str(row.get("vector_json") or ""))
        if vec is not None:
            return {
                "schema": "clip_embedding_v1",
                "vector": vec.tolist(),
                "model_version": row.get("model_version"),
                "dim": int(row["dim"]) if row.get("dim") is not None else len(vec),
                "aggregation_method": row.get("aggregation_method") or "clip_native",
            }

    from hmi.ai_artifacts import load_ai_embedding_local

    embed_doc = load_ai_embedding_local(clip_id, run_id)
    if embed_doc:
        vec = embed_doc.get("vector")
        parsed = parse_embedding(vec) if vec is not None else None
        if parsed is not None:
            return {
                "schema": "clip_embedding_v1",
                "vector": parsed.tolist(),
                "model_version": embed_doc.get("model_version"),
                "dim": int(embed_doc.get("dim") or len(parsed)),
                "aggregation_method": embed_doc.get("aggregation_method") or "clip_omni",
            }

    items = fetch_frame_embeddings_local(clip_id, run_id)
    if not items:
        return None
    return {
        "schema": "frame_embeddings_v1",
        "items": items,
    }


def _taxonomy_version_code(version_id: str | None) -> str | None:
    if not version_id:
        return None
    version = get_version(version_id)
    return str(version["version_code"]) if version else None


def assemble_row(review: dict[str, Any], *, snapshot_id: str | None = None) -> dict[str, Any] | None:
    clip_id = str(review["clip_id"])
    run_id = str(review["run_id"])
    feature = fetch_clip_feature_local(clip_id, run_id)
    if feature is None:
        return None
    taxonomy_version_id = review.get("taxonomy_version_id")
    row: dict[str, Any] = {
        "clip_id": clip_id,
        "run_id": run_id,
        "x_json": feature,
        "y_json": review.get("labels_json") or {},
        "taxonomy_version_id": taxonomy_version_id,
        "taxonomy_version_code": _taxonomy_version_code(taxonomy_version_id),
    }
    if snapshot_id:
        row["snapshot_id"] = snapshot_id
    return row


def assemble_snapshot_rows(
    filter_json: dict[str, Any] | None,
    *,
    snapshot_id: str | None = None,
    max_clips: int = MAX_CLIP_COUNT,
) -> AssemblyResult:
    filt = normalize_filter(filter_json)
    reviews = query_review_candidates(filt)
    if len(reviews) > max_clips:
        raise ValueError(f"clip count {len(reviews)} exceeds limit {max_clips}")

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    warnings: list[str] = []

    for review in reviews:
        row = assemble_row(review, snapshot_id=snapshot_id)
        if row is None:
            skipped.append(
                {
                    "clip_id": review["clip_id"],
                    "run_id": review["run_id"],
                    "reason": "no_clip_embedding",
                }
            )
            warnings.append(f"skip {review['clip_id']}/{review['run_id']}: no clip embedding")
            continue
        rows.append(row)

    if not rows and reviews:
        warnings.append("all candidate clips skipped (missing clip embeddings)")

    return AssemblyResult(
        rows=rows,
        clip_count=len(rows),
        skipped=skipped,
        warnings=warnings,
    )


def row_to_manifest_line(row: dict[str, Any]) -> str:
    return json.dumps(row, ensure_ascii=False)
