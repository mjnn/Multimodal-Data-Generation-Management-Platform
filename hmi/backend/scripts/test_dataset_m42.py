"""M4.2 dataset assemble smoke test."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_DATA_SOURCE", "local")

from hmi.app_db import ensure_schema
from hmi.dataset.assemble import assemble_snapshot_rows, query_review_candidates
from hmi.local import store
from hmi.review_db import create_review


def _seed_clip(*, clip_id: str, run_id: str, ds: str, with_embedding: bool) -> None:
    store.execute(
        "INSERT OR REPLACE INTO dim_clip (clip_id, clip_dir_name, active_run_id) VALUES (?, ?, ?)",
        (clip_id, clip_id[:16], run_id),
    )
    store.execute(
        "INSERT OR REPLACE INTO pipeline_run (run_id, clip_id, ds, status) VALUES (?, ?, ?, 'completed')",
        (run_id, clip_id, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_clip_label (
          clip_id, run_id, ds, labels_json, anchor_timestamp_ns
        ) VALUES (?, ?, ?, ?, 1000000000)
        """,
        (clip_id, run_id, ds, json.dumps({"L1.1.day_period": "night"})),
    )
    if with_embedding:
        store.execute(
            """
            INSERT OR REPLACE INTO fact_embedding (
              clip_id, run_id, ds, object_type, object_id, timestamp_ns,
              vector_json, dim
            ) VALUES (?, ?, ?, 'frame', 'cam0:0', 1000000000, ?, 3)
            """,
            (clip_id, run_id, ds, json.dumps([0.1, 0.2, 0.3])),
        )


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    ds = "20260721"

    clip_reviewed = f"sha256:m42_ok_{suffix}"
    clip_pending = f"sha256:m42_pending_{suffix}"
    clip_no_emb = f"sha256:m42_noemb_{suffix}"
    run_ok = str(uuid.uuid4())
    run_pending = str(uuid.uuid4())
    run_noemb = str(uuid.uuid4())

    _seed_clip(clip_id=clip_reviewed, run_id=run_ok, ds=ds, with_embedding=True)
    _seed_clip(clip_id=clip_pending, run_id=run_pending, ds=ds, with_embedding=True)
    _seed_clip(clip_id=clip_no_emb, run_id=run_noemb, ds=ds, with_embedding=False)

    labels = {"L1.1.day_period": "night"}
    create_review(clip_reviewed, run_ok, labels_json=labels, review_status="reviewed")
    create_review(clip_pending, run_pending, labels_json=labels, review_status="pending_review")
    create_review(clip_no_emb, run_noemb, labels_json=labels, review_status="reviewed")

    default_candidates = query_review_candidates({"review_status": "reviewed"})
    assert any(r["clip_id"] == clip_reviewed for r in default_candidates)
    assert any(r["clip_id"] == clip_pending for r in default_candidates)
    print("OK local default candidate pool includes pending_review")

    result = assemble_snapshot_rows({"review_status": "reviewed"})
    assert result.clip_count >= 1
    row = next(r for r in result.rows if r["clip_id"] == clip_reviewed)
    assert row["run_id"] == run_ok
    assert row["y_json"]["L1.1.day_period"] == "night"
    x = row["x_json"]
    assert x["schema"] == "frame_embeddings_v1"
    assert len(x["items"]) == 1
    assert len(x["items"][0]["vector"]) == 3
    assert abs(x["items"][0]["vector"][0] - 0.1) < 1e-5
    print("OK assemble reviewed row with x/y")

    assert not any(r["clip_id"] == clip_no_emb for r in default_candidates)
    print("OK exclude clip without embedding from pool")

    include = assemble_snapshot_rows({"include_pending_review": True})
    clip_ids = {r["clip_id"] for r in include.rows}
    assert clip_reviewed in clip_ids
    assert clip_pending in clip_ids
    print("OK include_pending_review")

    specific = assemble_snapshot_rows({"review_status": "reviewed", "clip_ids": [clip_reviewed]})
    assert specific.clip_count == 1
    assert specific.rows[0]["clip_id"] == clip_reviewed
    print("OK clip_ids filter")

    clip_morning = f"sha256:m42_morning_{suffix}"
    run_morning = str(uuid.uuid4())
    _seed_clip(clip_id=clip_morning, run_id=run_morning, ds=ds, with_embedding=True)
    create_review(
        clip_morning,
        run_morning,
        labels_json={"L1.1.day_period": "morning"},
        review_status="reviewed",
    )

    morning_only = query_review_candidates(
        {"review_status": "reviewed", "label_filters": {"L1.1.day_period": "morning"}}
    )
    morning_ids = {r["clip_id"] for r in morning_only}
    assert clip_morning in morning_ids
    assert clip_reviewed not in morning_ids
    print("OK label_filters reviewed subset")

    morning_assemble = assemble_snapshot_rows(
        {
            "review_status": "reviewed",
            "label_filters": {"L1.1.day_period": "morning"},
            "clip_ids": [clip_morning, clip_reviewed],
        }
    )
    morning_row_ids = {r["clip_id"] for r in morning_assemble.rows}
    assert morning_row_ids == {clip_morning}
    print("OK assemble with label_filters")

    print("\nAll M4.2 checks passed.")


if __name__ == "__main__":
    main()
