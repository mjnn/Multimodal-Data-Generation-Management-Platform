"""M3.2 AI aggregate + enqueue smoke test."""

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
from hmi.local import store
from hmi.review.aggregate import aggregate_clip_labels, select_representative_rows
from hmi.review.enqueue import enqueue_clip, list_enqueue_candidates
from hmi.review_db import get_review


def _seed_local_clip(
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    labels_rows: list[dict],
    job3_status: str = "success",
) -> None:
    store.execute(
        """
        INSERT OR REPLACE INTO dim_clip (clip_id, clip_dir_name, active_run_id)
        VALUES (?, ?, ?)
        """,
        (clip_id, clip_id[:16], run_id),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO pipeline_run (run_id, clip_id, ds, status)
        VALUES (?, ?, ?, 'completed')
        """,
        (run_id, clip_id, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO pipeline_step (run_id, ds, step_id, status)
        VALUES (?, ?, 'job3_label', ?)
        """,
        (run_id, ds, job3_status),
    )
    for row in labels_rows:
        store.execute(
            """
            INSERT OR REPLACE INTO fact_image_label (
              clip_id, run_id, ds, frame_id, timestamp_ns, labels_json,
              sync_group_id, anchor_timestamp_ns, label_scope
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                run_id,
                ds,
                row["frame_id"],
                row["timestamp_ns"],
                json.dumps(row["labels_json"], ensure_ascii=False),
                row.get("sync_group_id"),
                row.get("anchor_timestamp_ns"),
                row.get("label_scope"),
            ),
        )


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    ds = "20260721"

    # Frame-first aggregation
    clip_frame = f"sha256:m32_frame_{suffix}"
    run_frame = str(uuid.uuid4())
    labels_payload = {
        "values": {"L1.1.day_period": {"value": "morning"}, "L1.1.is_holiday": {"value": False}}
    }
    _seed_local_clip(
        clip_id=clip_frame,
        run_id=run_frame,
        ds=ds,
        labels_rows=[
            {
                "frame_id": "cam0:0",
                "timestamp_ns": 1_000_000_000,
                "labels_json": labels_payload,
            },
            {
                "frame_id": "cam0:1",
                "timestamp_ns": 2_000_000_000,
                "labels_json": {"values": {"L1.1.day_period": {"value": "night"}}},
            },
        ],
    )
    agg_frame = aggregate_clip_labels(clip_frame, run_frame)
    assert agg_frame["aggregation"] == "frame_first"
    assert agg_frame["labels_json"]["L1.1.day_period"] == "morning"
    assert agg_frame["ai_source_summary_json"]["selected_frame_id"] == "cam0:0"
    print("OK aggregate frame_first")

    reps, mode = select_representative_rows(
        [
            {"frame_id": "a", "timestamp_ns": 1, "labels_json": json.dumps(labels_payload)},
            {"frame_id": "a", "timestamp_ns": 2, "labels_json": json.dumps(labels_payload)},
        ]
    )
    assert mode == "frame_first"
    assert len(reps) == 1
    print("OK select_representative_rows dedupe")

    # Sync-group aggregation prefers label_scope=sync_group row
    clip_sg = f"sha256:m32_sg_{suffix}"
    run_sg = str(uuid.uuid4())
    sg_id = f"sg_{suffix}"
    _seed_local_clip(
        clip_id=clip_sg,
        run_id=run_sg,
        ds=ds,
        labels_rows=[
            {
                "frame_id": "cam0:0",
                "timestamp_ns": 1_000_000_000,
                "labels_json": {"values": {"L1.1.day_period": {"value": "wrong"}}},
                "sync_group_id": sg_id,
                "anchor_timestamp_ns": 1_500_000_000,
                "label_scope": "frame",
            },
            {
                "frame_id": "cam1:0",
                "timestamp_ns": 1_000_100_000,
                "labels_json": {
                    "values": {"L1.1.day_period": {"value": "afternoon"}, "L1.1.is_holiday": {"value": True}}
                },
                "sync_group_id": sg_id,
                "anchor_timestamp_ns": 1_500_000_000,
                "label_scope": "sync_group",
            },
        ],
    )
    agg_sg = aggregate_clip_labels(clip_sg, run_sg)
    assert agg_sg["aggregation"] == "sync_group"
    assert agg_sg["labels_json"]["L1.1.day_period"] == "afternoon"
    assert agg_sg["ai_source_summary_json"]["selected_sync_group_id"] == sg_id
    print("OK aggregate sync_group")

    # Enqueue creates pending review
    result = enqueue_clip(clip_frame, run_frame)
    assert result["status"] == "created"
    review = result["review"]
    assert review["review_status"] == "pending_review"
    assert review["labels_json"]["L1.1.day_period"] == "morning"
    assert review["ai_source_summary_json"]["aggregation"] == "frame_first"
    print("OK enqueue_clip create")

    dup = enqueue_clip(clip_frame, run_frame)
    assert dup["status"] == "skipped"
    assert dup["reason"] == "already_exists"
    print("OK enqueue_clip skip duplicate")

    assert get_review(clip_frame, run_frame) is not None
    candidates = list_enqueue_candidates()
    assert not any(c["clip_id"] == clip_frame and c["run_id"] == run_frame for c in candidates)
    assert any(c["clip_id"] == clip_sg and c["run_id"] == run_sg for c in candidates)
    print("OK list_enqueue_candidates")

    print("\nAll M3.2 checks passed.")


if __name__ == "__main__":
    main()
