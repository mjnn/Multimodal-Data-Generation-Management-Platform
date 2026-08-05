"""Unit tests for sdk_infer_node helpers."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_DATAWORKS = Path(__file__).resolve().parents[2] / "pipeline" / "dataworks"
sys.path.insert(0, str(_DATAWORKS))

import sdk_node_common as common  # noqa: E402

_MC_ENV_KEYS = (
    "MODEL_BACKEND",
    "MC_OMNI_FALLBACK_MODEL",
    "MC_IMAGE_MODE",
    "MC_CLOUD_REGION",
    "MC_MODELSET_PROJECT",
    "MC_OSS_BUCKET",
    "OSS_BUCKET",
)


def _fake_get_arg(name: str, default: str | None = None) -> str | None:
    values = {
        "mc_omni_fallback_model": "qwen3.6-plus",
        "cloud_region": "cn_shanghai",
        "oss_bucket": "rosbag-labels-pipline-bucket",
    }
    return values.get(name, default)


class TestSdkInferNodeEnv(unittest.TestCase):
    def test_apply_env_mc_sets_fallback(self) -> None:
        baseline = {key: "" for key in _MC_ENV_KEYS}
        with patch.dict(os.environ, baseline, clear=False):
            for key in _MC_ENV_KEYS:
                os.environ.pop(key, None)
            with patch.object(common, "get_arg", side_effect=_fake_get_arg):
                common.apply_env_from_args("mc")
            self.assertEqual(os.environ.get("MODEL_BACKEND"), "mc")
            self.assertEqual(os.environ.get("MC_OMNI_FALLBACK_MODEL"), "qwen3.6-plus")
            self.assertEqual(os.environ.get("MC_CLOUD_REGION"), "cn_shanghai")
            # media_mode 由 RunContext 控制，不再默认写 MC_IMAGE_MODE
            self.assertIsNone(os.environ.get("MC_IMAGE_MODE"))

    def test_apply_env_does_not_override_existing(self) -> None:
        with patch.dict(os.environ, {"MC_IMAGE_MODE": "oss_url"}, clear=False):
            with patch.object(common, "get_arg", return_value="base64"):
                common.apply_env_from_args("mc")
            self.assertEqual(os.environ.get("MC_IMAGE_MODE"), "oss_url")

    def test_validate_mc_requires_fallback_for_omni(self) -> None:
        with patch.dict(
            os.environ,
            {"OMNI_MODEL": "qwen3.5-omni-plus"},
            clear=False,
        ):
            with patch.object(common, "resolve_odps_entry", return_value=object()):
                with self.assertRaises(ValueError) as ctx:
                    common.validate_mc_backend()
            self.assertIn("mc_omni_fallback_model", str(ctx.exception))

    def test_validate_mc_ok_with_fallback(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OMNI_MODEL": "qwen3.5-omni-plus",
                "MC_OMNI_FALLBACK_MODEL": "qwen3.6-plus",
            },
            clear=False,
        ):
            with patch.object(common, "resolve_odps_entry", return_value=object()):
                common.validate_mc_backend()


if __name__ == "__main__":
    unittest.main()
