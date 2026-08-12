"""upload-only cloud enqueue does not call DataWorks."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class UploadOnlyEnqueueTests(unittest.TestCase):
    def test_trigger_false_skips_dataworks(self) -> None:
        from hmi.services import cloud_pipeline_execution as mod

        with (
            mock.patch.object(mod.dataworks_trigger, "require_dataworks_config") as req,
            mock.patch.object(mod.dataworks_trigger, "trigger_sdk_pipeline") as trig,
            mock.patch("hmi.oss_signer.upload_rosbag_bytes", return_value="rosbags/t/a.bag"),
            mock.patch.object(mod, "_write_all"),
            mock.patch.object(mod, "_read_all", return_value=[]),
        ):
            out = mod.enqueue_rosbags_cloud([("a.bag", b"data")], trigger=False)
        req.assert_not_called()
        trig.assert_not_called()
        self.assertIsNone(out.get("dag_id"))
        self.assertTrue(out.get("await_schedule"))
        self.assertFalse(out.get("trigger"))
        self.assertEqual(out["clips"][0]["bag_oss_key"], "rosbags/t/a.bag")

    def test_trigger_true_still_requires_config(self) -> None:
        from hmi.services import cloud_pipeline_execution as mod
        from hmi.services.dataworks_trigger import DataWorksConfigError

        with mock.patch.object(
            mod.dataworks_trigger,
            "require_dataworks_config",
            side_effect=DataWorksConfigError("missing"),
        ):
            with self.assertRaises(DataWorksConfigError):
                mod.enqueue_rosbags_cloud([("a.bag", b"data")], trigger=True)


if __name__ == "__main__":
    unittest.main()
