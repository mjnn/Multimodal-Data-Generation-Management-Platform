"""Export human-reviewed labels to OSS reviews/ prefix (v2)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from hmi.oss_layout import review_labels_key, review_meta_key
from hmi.oss_signer import put_object_text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def export_review_to_oss(review: dict[str, Any], *, reviewer_id: str | None) -> dict[str, str]:
    clip_id = str(review["clip_id"])
    run_id = str(review["run_id"])
    labels = review.get("labels_json") or {}
    labels_key = review_labels_key(clip_id, run_id)
    meta_key = review_meta_key(clip_id, run_id)

    labels_body = json.dumps(
        {
            "clip_id": clip_id,
            "run_id": run_id,
            "label_source": "human",
            "review_id": review.get("id"),
            "review_status": review.get("review_status"),
            "taxonomy_version_id": review.get("taxonomy_version_id"),
            "labels_json": labels,
            "updated_at": review.get("updated_at") or _utc_now(),
        },
        ensure_ascii=False,
        indent=2,
    )
    meta_body = json.dumps(
        {
            "clip_id": clip_id,
            "run_id": run_id,
            "review_id": review.get("id"),
            "reviewer_id": reviewer_id,
            "reviewed_at": review.get("updated_at") or _utc_now(),
            "taxonomy_version_id": review.get("taxonomy_version_id"),
            "source": "hmi_review_save",
        },
        ensure_ascii=False,
        indent=2,
    )
    put_object_text(labels_key, labels_body, content_type="application/json")
    put_object_text(meta_key, meta_body, content_type="application/json")
    return {"labels_key": labels_key, "meta_key": meta_key}
