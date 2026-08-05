"""Tests for upload_run grouping and dispatch."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DATAWORKS = Path(__file__).resolve().parents[2] / "pipeline" / "dataworks"
sys.path.insert(0, str(_DATAWORKS))

from pipeline_dispatch import pick_dispatch_upload_run  # noqa: E402
from upload_run import group_bags_by_upload_run, new_pipeline_run_id, upload_run_id_from_object_key  # noqa: E402


class TestUploadRunGrouping(unittest.TestCase):
    def test_upload_run_id_from_key(self) -> None:
        key = "rosbags/uploads/batch-001/foo.bag"
        self.assertEqual(upload_run_id_from_object_key(key), "batch-001")

    def test_group_bags(self) -> None:
        bags = [
            {"clip_id": "sha256:a", "object_key": "rosbags/uploads/u1/a.bag"},
            {"clip_id": "sha256:b", "object_key": "rosbags/uploads/u1/b.bag"},
            {"clip_id": "sha256:c", "object_key": "rosbags/uploads/u2/c.bag"},
        ]
        runs = group_bags_by_upload_run(bags, allow_legacy_flat=False)
        self.assertEqual(len(runs), 2)
        by_id = {r["upload_run_id"]: r for r in runs}
        self.assertEqual(len(by_id["u1"]["bags"]), 2)
        self.assertEqual(len(by_id["u2"]["bags"]), 1)

    def test_new_pipeline_run_id_format(self) -> None:
        # 2026-08-03 14:26:45.123456 UTC+8
        cn = timezone(timedelta(hours=8))
        run_id = new_pipeline_run_id(datetime(2026, 8, 3, 14, 26, 45, 123456, tzinfo=cn))
        self.assertEqual(run_id, "2026-08-03-14-26-45.0123")

    def test_pick_dispatch_upload_run_shared_run_id(self) -> None:
        discover = {
            "upload_runs": [
                {
                    "upload_run_id": "batch-001",
                    "complete": True,
                    "new_count": 2,
                    "bags": [
                        {
                            "clip_id": "sha256:a",
                            "object_key": "rosbags/uploads/batch-001/a.bag",
                            "clip_dir_name": "a",
                        },
                        {
                            "clip_id": "sha256:b",
                            "object_key": "rosbags/uploads/batch-001/b.bag",
                            "clip_dir_name": "b",
                        },
                    ],
                }
            ]
        }
        payload = pick_dispatch_upload_run(object(), "aig_sdk__", discover_payload=discover)
        self.assertEqual(payload["action"], "run")
        self.assertEqual(payload["mode"], "upload_run")
        self.assertEqual(payload["upload_run_id"], "batch-001")
        self.assertEqual(len(payload["items"]), 2)
        run_ids = {item["run_id"] for item in payload["items"]}
        self.assertEqual(len(run_ids), 1)
        run_id = payload["pipeline_run_id"]
        self.assertRegex(run_id, r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.\d{4}$")
        self.assertEqual(run_id, payload["items"][0]["run_id"])


if __name__ == "__main__":
    unittest.main()
