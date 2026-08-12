"""Unit checks for HMI test mode + reset gate (no cloud I/O)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "hmi" / "backend"
for p in (str(BACKEND), str(REPO / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)


class TestModeFlag(unittest.TestCase):
    def test_is_test_mode_truthy(self) -> None:
        from hmi.test_mode import is_test_mode

        for val in ("1", "true", "YES", "on"):
            with mock.patch.dict(os.environ, {"HMI_TEST_MODE": val}, clear=False):
                self.assertTrue(is_test_mode(), val)

    def test_is_test_mode_falsy(self) -> None:
        from hmi.test_mode import is_test_mode

        for val in ("", "0", "false", "no"):
            with mock.patch.dict(os.environ, {"HMI_TEST_MODE": val}, clear=False):
                self.assertFalse(is_test_mode(), repr(val))

    def test_reset_requires_test_mode(self) -> None:
        from hmi.hmi_baseline_reset import reset_hmi_artifacts_to_baseline

        with mock.patch.dict(os.environ, {"HMI_TEST_MODE": "0"}, clear=False):
            with self.assertRaises(PermissionError):
                reset_hmi_artifacts_to_baseline()


if __name__ == "__main__":
    unittest.main()
