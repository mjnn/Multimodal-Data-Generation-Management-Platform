"""Per-label_id usage stats (M10)."""

from __future__ import annotations

import json
from typing import Any

from hmi.app_db import db_conn
from hmi.labels_util import labels_to_clip_dict
from hmi.taxonomy_db import get_version, list_nodes


def build_node_usage(label_id: str, *, taxonomy_version_id: str | None = None) -> dict[str, Any]:
    label_id = label_id.strip()
    if not label_id:
        raise ValueError("label_id required")

    version_id = taxonomy_version_id
    version_code: str | None = None
    if version_id:
        version = get_version(version_id)
        if version is None:
            raise ValueError("taxonomy version not found")
        version_code = str(version.get("version_code") or "")

    clip_samples: list[dict[str, str]] = []
    reviewed_count = 0
    with db_conn() as conn:
        sql = "SELECT clip_id, run_id, review_status, labels_json, taxonomy_version_id FROM clip_label_review"
        params: list[Any] = []
        if version_id:
            sql += " WHERE taxonomy_version_id = ?"
            params.append(version_id)
        rows = conn.execute(sql, params).fetchall()

    for row in rows:
        labels_raw = row["labels_json"]
        if isinstance(labels_raw, str):
            try:
                labels_json = json.loads(labels_raw) if labels_raw else {}
            except json.JSONDecodeError:
                labels_json = {}
        else:
            labels_json = labels_raw or {}
        flat = labels_to_clip_dict(labels_json)
        if label_id not in flat or flat[label_id] in (None, ""):
            continue
        if str(row["review_status"]) == "reviewed":
            reviewed_count += 1
        if len(clip_samples) < 20:
            clip_samples.append(
                {
                    "clip_id": str(row["clip_id"]),
                    "run_id": str(row["run_id"]),
                    "value": str(flat[label_id]),
                }
            )

    dataset_refs = 0
    with db_conn() as conn:
        for row in conn.execute(
            "SELECT filter_json FROM dataset_snapshot WHERE status != 'archived'"
        ).fetchall():
            try:
                filt = json.loads(row["filter_json"] or "{}")
            except json.JSONDecodeError:
                continue
            if filt.get("balance_by_label") == label_id:
                dataset_refs += 1
                continue
            lf = filt.get("label_filters") or {}
            if isinstance(lf, dict) and label_id in lf:
                dataset_refs += 1

    node_name: str | None = None
    if version_id:
        for n in list_nodes(version_id):
            if str(n["label_id"]) == label_id:
                node_name = str(n.get("name") or label_id)
                break

    return {
        "label_id": label_id,
        "name": node_name,
        "taxonomy_version_id": version_id,
        "taxonomy_version_code": version_code,
        "clip_with_label_count": reviewed_count,
        "clip_samples": clip_samples,
        "dataset_reference_count": dataset_refs,
    }
