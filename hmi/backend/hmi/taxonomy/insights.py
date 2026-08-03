"""Taxonomy context and label coverage insights (M10)."""

from __future__ import annotations

import json
from typing import Any

from hmi.app_db import db_conn
from hmi.labels_util import labels_to_clip_dict
from hmi.taxonomy_db import get_published_version, get_version, list_nodes


def _enum_values(node: dict[str, Any]) -> list[str]:
    schema = node.get("value_schema")
    if not isinstance(schema, dict):
        return []
    raw = schema.get("values")
    if isinstance(raw, list):
        return [str(v) for v in raw]
    return []


def _load_reviews_for_version(taxonomy_version_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT clip_id, run_id, review_status, labels_json, taxonomy_version_id
            FROM clip_label_review
            WHERE taxonomy_version_id = ?
            """,
            (taxonomy_version_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        labels_raw = row["labels_json"]
        if isinstance(labels_raw, str):
            try:
                labels_json = json.loads(labels_raw) if labels_raw else {}
            except json.JSONDecodeError:
                labels_json = {}
        else:
            labels_json = labels_raw or {}
        out.append(
            {
                "clip_id": str(row["clip_id"]),
                "run_id": str(row["run_id"]),
                "review_status": str(row["review_status"] or ""),
                "labels_json": labels_json,
            }
        )
    return out


def _proposal_open_count() -> int:
    with db_conn() as conn:
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='taxonomy_proposal'"
        ).fetchone():
            return 0
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM taxonomy_proposal WHERE status = 'open'"
        ).fetchone()
    return int(row["cnt"]) if row else 0


def build_taxonomy_context() -> dict[str, Any]:
    published = get_published_version()
    published_id = str(published["id"]) if published else None
    published_code = str(published["version_code"]) if published else None

    reviewed_total = 0
    version_clip_counts: dict[str, int] = {}
    with db_conn() as conn:
        for row in conn.execute(
            """
            SELECT taxonomy_version_id, review_status, COUNT(*) AS cnt
            FROM clip_label_review
            GROUP BY taxonomy_version_id, review_status
            """
        ).fetchall():
            tid = str(row["taxonomy_version_id"] or "")
            version_clip_counts[tid] = version_clip_counts.get(tid, 0) + int(row["cnt"])
            if str(row["review_status"]) == "reviewed":
                reviewed_total += int(row["cnt"])

    node_count = 0
    if published_id:
        node_count = len([n for n in list_nodes(published_id) if n.get("is_active") is not False])

    behind_published = 0
    if published_id:
        behind_published = sum(
            cnt for tid, cnt in version_clip_counts.items() if tid and tid != published_id
        )

    return {
        "published_taxonomy_version_id": published_id,
        "published_taxonomy_version_code": published_code,
        "published_node_count": node_count,
        "reviewed_clip_total": reviewed_total,
        "clips_on_non_published_taxonomy": behind_published,
        "open_proposal_count": _proposal_open_count(),
        "version_clip_counts": version_clip_counts,
    }


def build_coverage(taxonomy_version_id: str) -> dict[str, Any]:
    version = get_version(taxonomy_version_id)
    if version is None:
        raise ValueError("taxonomy version not found")

    nodes = [
        n for n in list_nodes(taxonomy_version_id) if n.get("is_active") is not False
    ]
    reviews = _load_reviews_for_version(taxonomy_version_id)
    reviewed = [r for r in reviews if r["review_status"] == "reviewed"]
    pool = reviewed if reviewed else reviews

    items: list[dict[str, Any]] = []
    for node in sorted(nodes, key=lambda n: (n.get("sort_order", 0), n["label_id"])):
        label_id = str(node["label_id"])
        value_counts: dict[str, int] = {}
        present = 0
        for review in pool:
            flat = labels_to_clip_dict(review.get("labels_json"))
            if label_id not in flat or flat[label_id] in (None, ""):
                continue
            present += 1
            val = flat[label_id]
            if isinstance(val, bool):
                key = "true" if val else "false"
            else:
                key = str(val)
            value_counts[key] = value_counts.get(key, 0) + 1

        enum_vals = _enum_values(node)
        missing_enums: list[str] = []
        if enum_vals and pool:
            missing_enums = [v for v in enum_vals if v not in value_counts]
        has_gap = len(pool) > 0 and (bool(missing_enums) or present == 0)
        items.append(
            {
                "label_id": label_id,
                "name": node.get("name"),
                "dtype": node.get("dtype"),
                "reviewed_with_label": present,
                "reviewed_missing_label": max(0, len(pool) - present),
                "value_counts": value_counts,
                "enum_values": enum_vals,
                "missing_enum_values": missing_enums,
                "has_gap": has_gap,
            }
        )

    gap_count = sum(1 for i in items if i["has_gap"])
    return {
        "taxonomy_version_id": taxonomy_version_id,
        "taxonomy_version_code": version.get("version_code"),
        "review_pool_count": len(pool),
        "reviewed_count": len(reviewed),
        "node_count": len(nodes),
        "gap_node_count": gap_count,
        "items": items,
    }


def build_pool_taxonomy_distribution(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count taxonomy_version_id in review pool rows."""
    from hmi.taxonomy_db import get_version

    counts: dict[str, int] = {}
    for row in pool:
        tid = str(row.get("taxonomy_version_id") or "__unknown__")
        counts[tid] = counts.get(tid, 0) + 1
    out: list[dict[str, Any]] = []
    for tid, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        code: str | None = None
        if tid != "__unknown__":
            v = get_version(tid)
            code = str(v["version_code"]) if v else None
        out.append(
            {
                "taxonomy_version_id": None if tid == "__unknown__" else tid,
                "taxonomy_version_code": code,
                "clip_count": cnt,
            }
        )
    return out
