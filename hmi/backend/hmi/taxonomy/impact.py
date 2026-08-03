"""Taxonomy version publish impact (M10)."""

from __future__ import annotations

import json
from typing import Any

from hmi.app_db import db_conn
from hmi.taxonomy.lineage import list_child_version_ids
from hmi.taxonomy_db import get_published_version, get_version


def _count_clips_by_taxonomy(version_id: str) -> dict[str, int]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT review_status, COUNT(*) AS cnt
            FROM clip_label_review
            WHERE taxonomy_version_id = ?
            GROUP BY review_status
            """,
            (version_id,),
        ).fetchall()
    out = {"total": 0, "reviewed": 0, "pending_review": 0}
    for row in rows:
        status = str(row["review_status"] or "")
        cnt = int(row["cnt"])
        out["total"] += cnt
        if status == "reviewed":
            out["reviewed"] = cnt
        elif status == "pending_review":
            out["pending_review"] = cnt
    return out


def _count_datasets_referencing(version_id: str) -> int:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT filter_json FROM dataset_snapshot WHERE status != 'archived'"
        ).fetchall()
    count = 0
    needle = version_id
    for row in rows:
        try:
            filt = json.loads(row["filter_json"] or "{}")
        except json.JSONDecodeError:
            continue
        if str(filt.get("taxonomy_version_id") or "") == needle:
            count += 1
        label_filters = filt.get("label_filters") or {}
        balance = filt.get("balance_by_label")
        if isinstance(label_filters, dict) and label_filters:
            count += 0  # version lock only for explicit taxonomy_version_id
        if balance:
            pass
    return count


def _count_datasets_with_balance_label(version_id: str, label_ids: set[str]) -> int:
    if not label_ids:
        return 0
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT filter_json FROM dataset_snapshot WHERE status != 'archived'"
        ).fetchall()
    count = 0
    for row in rows:
        try:
            filt = json.loads(row["filter_json"] or "{}")
        except json.JSONDecodeError:
            continue
        bal = str(filt.get("balance_by_label") or "")
        if bal in label_ids:
            count += 1
        lf = filt.get("label_filters") or {}
        if isinstance(lf, dict) and any(k in label_ids for k in lf):
            count += 1
    return count


def build_version_impact(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise ValueError("taxonomy version not found")

    published = get_published_version()
    published_id = str(published["id"]) if published else None
    clip_stats = _count_clips_by_taxonomy(version_id)
    child_ids = list_child_version_ids(version_id)

    from hmi.taxonomy_db import list_nodes

    label_ids = {str(n["label_id"]) for n in list_nodes(version_id)}

    warnings: list[str] = []
    if published_id and version_id != published_id and clip_stats["reviewed"] > 0:
        warnings.append(
            f"仍有 {clip_stats['reviewed']} 条已校核 clip 绑定在此标签树版本"
        )
    if version.get("status") == "draft" and clip_stats["total"] > 0:
        warnings.append("草稿版本已被 clip 校核引用")

    return {
        "taxonomy_version_id": version_id,
        "taxonomy_version_code": version.get("version_code"),
        "status": version.get("status"),
        "is_published": version_id == published_id,
        "clip_counts": clip_stats,
        "dataset_filter_lock_count": _count_datasets_referencing(version_id),
        "dataset_label_reference_count": _count_datasets_with_balance_label(
            version_id, label_ids
        ),
        "child_version_ids": child_ids,
        "warnings": warnings,
    }
