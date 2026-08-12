"""Unit tests: default pipeline progress uses SDK v1, not dual-model labels."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hmi.services.pipeline_status import (  # noqa: E402
    _pending_steps,
    _step_order_for_ids,
    compute_overall_status,
)


class SdkPipelineStepsTests(unittest.TestCase):
    def test_pending_default_is_sdk_not_dual_model(self) -> None:
        steps = _pending_steps(include_job0=True)
        labels = [s["label"] for s in steps]
        ids = [s["step_id"] for s in steps]
        self.assertIn("sdk_infer", ids)
        self.assertNotIn("job2_labeling", ids)
        self.assertNotIn("job3_labeling_by_other_model", ids)
        joined = " ".join(labels)
        self.assertNotIn("主模型", joined)
        self.assertNotIn("副模型", joined)
        self.assertNotIn("多模型比对", joined)

    def test_pending_without_discover(self) -> None:
        steps = _pending_steps(include_job0=False)
        ids = [s["step_id"] for s in steps]
        self.assertNotIn("sdk_discover", ids)
        self.assertEqual(
            ids,
            ["sdk_infer", "sdk_upload", "sdk_mc_write", "sdk_dispatch"],
        )

    def test_legacy_ids_keep_dual_model_order(self) -> None:
        order = _step_order_for_ids({"job2_labeling", "job4_label_merge_and_compare"})
        self.assertIn("job2_labeling", order)
        self.assertIn("job3_labeling_by_other_model", order)

    def test_sdk_ids_prefer_sdk_order(self) -> None:
        order = _step_order_for_ids({"sdk_infer", "sdk_mc_write"})
        self.assertEqual(order[0], "sdk_discover")
        self.assertIn("sdk_infer", order)
        self.assertNotIn("job2_labeling", order)

    def test_compute_overall_ignores_discover(self) -> None:
        steps = [
            {"step_id": "sdk_discover", "status": "success"},
            {"step_id": "sdk_infer", "status": "success"},
            {"step_id": "sdk_upload", "status": "success"},
            {"step_id": "sdk_mc_write", "status": "success"},
            {"step_id": "sdk_dispatch", "status": "success"},
        ]
        self.assertEqual(compute_overall_status(steps), "completed")


if __name__ == "__main__":
    unittest.main()
