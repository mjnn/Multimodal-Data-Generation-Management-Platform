"""Tests for SDK DPE batch helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_DATAWORKS = Path(__file__).resolve().parents[2] / "pipeline" / "dataworks"
sys.path.insert(0, str(_DATAWORKS))

import sdk_dpe_common as common  # noqa: E402
from pipeline_dispatch import _normalize_batch_items, pick_dispatch_batch  # noqa: E402


class TestSdkDpeBatch(unittest.TestCase):
    def test_work_items_to_job_rows(self) -> None:
        rows = common.work_items_to_job_rows(
            [
                {
                    "clip_id": "sha256:a",
                    "run_id": "r1",
                    "run_relpath": "clips/sha256:a/runs/r1",
                    "bag_oss_key": "rosbags/a.bag",
                }
            ]
        )
        self.assertEqual(rows[0]["clip_id"], "sha256:a")
        self.assertEqual(rows[0]["bag_oss_key"], "rosbags/a.bag")

    def test_normalize_batch_items_single(self) -> None:
        items = _normalize_batch_items({"clip_id": "c1", "run_id": "r1", "bag_oss_key": "b.bag"})
        self.assertEqual(len(items), 1)

    def test_normalize_batch_items_multi(self) -> None:
        payload = {
            "items": [
                {"clip_id": "c1", "run_id": "r1"},
                {"clip_id": "c2", "run_id": "r2"},
            ]
        }
        self.assertEqual(len(_normalize_batch_items(payload)), 2)

    def test_pick_dispatch_batch_from_discover(self) -> None:
        discover = {
            "items": [
                {
                    "clip_id": "sha256:x",
                    "object_key": "rosbags/x.bag",
                    "clip_dir_name": "x",
                }
            ]
        }

        class _FakeClient:
            project = "p"
            endpoint = "https://example.com"

        with patch.dict("os.environ", {}, clear=False):
            payload = pick_dispatch_batch(
                _FakeClient(),
                "aig_sdk__",
                discover_payload=discover,
                max_batch=8,
            )
        self.assertEqual(payload["action"], "run")
        self.assertEqual(payload["batch_size"], 1)
        self.assertEqual(payload["items"][0]["bag_oss_key"], "rosbags/x.bag")

    def test_dpe_nodes_import(self) -> None:
        try:
            import maxframe  # noqa: F401
        except ImportError:
            self.skipTest("maxframe not installed locally")
        import sdk_asr_dpe_node  # noqa: F401
        import sdk_embed_dpe_node  # noqa: F401
        import sdk_extract_dpe_node  # noqa: F401
        import sdk_label_dpe_node  # noqa: F401
        import sdk_preview_dpe_node  # noqa: F401

        self.assertTrue(callable(sdk_asr_dpe_node.main))


if __name__ == "__main__":
    unittest.main()
