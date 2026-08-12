"""Unit tests for cloud bag orphan poller helpers (no live OSS)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hmi.services.cloud_bag_trigger_poller import find_orphan_bag_keys  # noqa: E402


class OrphanBagTests(unittest.TestCase):
    def test_find_orphans_filters_known_age_mc(self) -> None:
        listed = [
            {"key": "rosbags/a/output.bag", "age_sec": 10.0, "size": 1},
            {"key": "rosbags/b/output.bag", "age_sec": 300.0, "size": 1},
            {"key": "rosbags/c/output.bag", "age_sec": 400.0, "size": 1},
            {"key": "rosbags/d/output.bag", "age_sec": 500.0, "size": 1},
        ]

        def fake_list(prefix: str, *, max_keys: int = 2000):
            return list(listed)

        with mock.patch(
            "hmi.services.cloud_bag_trigger_poller.list_bag_objects",
            side_effect=fake_list,
        ), mock.patch(
            "hmi.services.cloud_bag_trigger_poller._bag_already_in_mc",
            side_effect=lambda k: k.endswith("c/output.bag"),
        ):
            orphans = find_orphan_bag_keys(
                prefixes=["rosbags/"],
                known={"rosbags/d/output.bag"},
                min_age_sec=180,
                max_age_sec=7 * 24 * 3600,
                check_mc=True,
            )
        # a too young; c in MC; d known → only b
        self.assertEqual(orphans, ["rosbags/b/output.bag"])


if __name__ == "__main__":
    unittest.main()
