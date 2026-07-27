"""P0 clip-level facts: enqueue from fact_clip_label + assemble from fact_clip_embedding."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import ensure_schema
from hmi.clip_facts import (
    detect_label_granularity,
    resolve_clip_labels_for_enqueue,
    upsert_clip_embedding,
    upsert_clip_label,
)
from hmi.dataset.assemble import assemble_snapshot_rows, fetch_clip_feature_local
from hmi.local import store
from hmi.review.enqueue import enqueue_clip
from hmi.review_db import update_review


def _seed_dim(clip_id: str, run_id: str, ds: str) -> None:
    store.execute(
        "INSERT OR REPLACE INTO dim_clip (clip_id, clip_dir_name, active_run_id) VALUES (?, ?, ?)",
        (clip_id, clip_id[:16], run_id),
    )
    store.execute(
        "INSERT OR REPLACE INTO pipeline_run (run_id, clip_id, ds, status) VALUES (?, ?, ?, 'completed')",
        (run_id, clip_id, ds),
    )


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    ds = "20260721"

    clip_id = f"sha256:p0_clip_{suffix}"
    run_id = str(uuid.uuid4())
    _seed_dim(clip_id, run_id, ds)

    labels_payload = {
        "values": {
            "L1.1.day_period": {"value": "afternoon"},
            "L1.1.is_holiday": {"value": False},
        }
    }
    upsert_clip_label(
        clip_id,
        run_id,
        ds=ds,
        labels_json=labels_payload,
        model_version="clip-label-v1",
        anchor_timestamp_ns=1_500_000_000,
    )
    assert detect_label_granularity(clip_id, run_id) == "clip"
    print("OK detect_label_granularity clip")

    payload = resolve_clip_labels_for_enqueue(clip_id, run_id)
    assert payload["aggregation"] == "clip_native"
    assert payload["labels_json"]["L1.1.day_period"] == "afternoon"
    assert payload["ai_source_summary_json"]["source"] == "fact_clip_label"
    print("OK resolve_clip_labels_for_enqueue clip native")

    result = enqueue_clip(clip_id, run_id)
    assert result["status"] == "created"
    review = result["review"]
    assert review["review_status"] == "pending_review"
    assert review["labels_json"]["L1.1.day_period"] == "afternoon"
    assert review["ai_source_summary_json"]["aggregation"] == "clip_native"
    print("OK enqueue_clip from fact_clip_label")

    vector = [0.4, 0.5, 0.6, 0.7]
    upsert_clip_embedding(
        clip_id,
        run_id,
        ds=ds,
        vector=vector,
        model_version="clip-embed-v1",
    )
    feature = fetch_clip_feature_local(clip_id, run_id)
    assert feature is not None
    assert feature["schema"] == "clip_embedding_v1"
    assert len(feature["vector"]) == 4
    assert abs(feature["vector"][0] - 0.4) < 1e-5
    print("OK fetch_clip_feature_local prefers clip embedding")

    update_review(clip_id, run_id, review_status="reviewed")
    assembled = assemble_snapshot_rows({"review_status": "reviewed", "clip_ids": [clip_id]})
    assert assembled.clip_count == 1
    row = assembled.rows[0]
    assert row["clip_id"] == clip_id
    assert row["x_json"]["schema"] == "clip_embedding_v1"
    assert len(row["x_json"]["vector"]) == 4
    assert row["y_json"]["L1.1.day_period"] == "afternoon"
    print("OK assemble_snapshot_rows clip_embedding_v1")

    # Legacy fallback: frame labels + frame embeddings when no clip facts
    clip_legacy = f"sha256:p0_legacy_{suffix}"
    run_legacy = str(uuid.uuid4())
    _seed_dim(clip_legacy, run_legacy, ds)
    store.execute(
        """
        INSERT OR REPLACE INTO pipeline_step (run_id, ds, step_id, status)
        VALUES (?, ?, 'job4_label_merge_and_compare', 'success')
        """,
        (run_legacy, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_image_label (
          clip_id, run_id, ds, frame_id, timestamp_ns, labels_json
        ) VALUES (?, ?, ?, 'cam0:0', 1000000000, ?)
        """,
        (
            clip_legacy,
            run_legacy,
            ds,
            json.dumps({"values": {"L1.1.day_period": {"value": "night"}}}, ensure_ascii=False),
        ),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_embedding (
          clip_id, run_id, ds, object_type, object_id, timestamp_ns, vector_json, dim
        ) VALUES (?, ?, ?, 'frame', 'cam0:0', 1000000000, ?, 2)
        """,
        (clip_legacy, run_legacy, ds, json.dumps([0.9, 0.1])),
    )
    assert detect_label_granularity(clip_legacy, run_legacy) == "frame"
    legacy_payload = resolve_clip_labels_for_enqueue(clip_legacy, run_legacy)
    assert legacy_payload["aggregation"] in ("frame_first", "sync_group")
    legacy_feature = fetch_clip_feature_local(clip_legacy, run_legacy)
    assert legacy_feature["schema"] == "frame_embeddings_v1"
    assert len(legacy_feature["items"]) == 1
    print("OK legacy frame fallback")

    print("\nAll P0 clip facts checks passed.")


if __name__ == "__main__":
    main()
