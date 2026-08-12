"""Unit tests for DataWorks trigger param building (no live API)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hmi.services.dataworks_trigger import (  # noqa: E402
    DataWorksConfigError,
    build_node_param_string,
    require_dataworks_config,
)


class DataWorksTriggerTests(unittest.TestCase):
    def test_require_config_missing(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("DATAWORKS_")
            and k
            not in (
                "ODPS_ACCESS_ID",
                "ODPS_ACCESS_KEY",
                "ALIBABA_CLOUD_ACCESS_KEY_ID",
                "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
            )
        }
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(DataWorksConfigError):
                require_dataworks_config()

    def test_build_node_param_string(self) -> None:
        s = build_node_param_string(
            ["rosbags/t1/output.bag", " rosbag-labels/x.bag "],
            ds="20260811",
        )
        self.assertIn("bag_oss_keys=rosbags/t1/output.bag,rosbag-labels/x.bag", s)
        self.assertIn("max_bags=2", s)
        self.assertIn("ds=20260811", s)
        self.assertIn("stages=extract,preview,asr,label,embed,mc_write,dispatch", s)
        self.assertIn("ai_submitter=driver", s)

    def test_node_id_must_be_numeric(self) -> None:
        env = {
            "DATAWORKS_PROJECT_NAME": "ws",
            "DATAWORKS_TRIGGER_MODE": "smoke",
            "DATAWORKS_FLOW_NAME": "",
            "DATAWORKS_NODE_ID": "p0",
            "ODPS_ACCESS_ID": "id",
            "ODPS_ACCESS_KEY": "key",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            with self.assertRaises(DataWorksConfigError) as ctx:
                require_dataworks_config()
            self.assertIn("numeric", str(ctx.exception).lower())

    def test_smoke_mode_allows_empty_flow(self) -> None:
        env = {
            "DATAWORKS_PROJECT_NAME": "ws",
            "DATAWORKS_TRIGGER_MODE": "smoke",
            "DATAWORKS_FLOW_NAME": "",
            "DATAWORKS_NODE_ID": "700009283979",
            "ODPS_ACCESS_ID": "id",
            "ODPS_ACCESS_KEY": "key",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = require_dataworks_config()
            self.assertEqual(cfg["trigger_mode"], "smoke")
            self.assertEqual(cfg["node_id"], "700009283979")

    def test_reject_empty_keys(self) -> None:
        with self.assertRaises(ValueError):
            build_node_param_string([])


if __name__ == "__main__":
    unittest.main()
