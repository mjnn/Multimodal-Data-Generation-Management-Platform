from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline" / "dataworks"))

from sdk_driver_bare_asr import (  # noqa: E402
    image_mime_from_key,
    oss_internal_object_url,
    resolve_ai_media_mode,
    resolve_driver_oss_ak_sk,
)
from sdk_driver_bare_pack import path_under_mount_to_oss_key  # noqa: E402


class _FakeArgs:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    def __call__(self, key: str, default: str | None = None) -> str | None:
        if key in self._mapping:
            return self._mapping[key]
        return default


class TestMediaModeSelection(unittest.TestCase):
    def test_auto_without_ak_falls_back_to_base64(self) -> None:
        get_arg = _FakeArgs({})
        self.assertEqual(resolve_ai_media_mode(get_arg), "dpe_base64")

    def test_auto_with_oss_vl_ak_uses_oss_url(self) -> None:
        get_arg = _FakeArgs(
            {
                "oss_vl_access_key_id": "LTAIxxxx",
                "oss_vl_access_key_secret": "secret",
            }
        )
        self.assertEqual(resolve_ai_media_mode(get_arg), "oss_url")

    def test_sts_ak_not_used_for_oss_url(self) -> None:
        get_arg = _FakeArgs(
            {
                "oss_vl_access_key_id": "STS.Nxxx",
                "oss_vl_access_key_secret": "secret",
            }
        )
        self.assertIsNone(resolve_driver_oss_ak_sk(get_arg))
        self.assertEqual(resolve_ai_media_mode(get_arg), "dpe_base64")

    def test_explicit_oss_url_requires_ak(self) -> None:
        get_arg = _FakeArgs({"ai_media_mode": "oss_url"})
        with self.assertRaises(ValueError):
            resolve_ai_media_mode(get_arg)

    def test_label_image_mode_alias(self) -> None:
        get_arg = _FakeArgs(
            {
                "label_image_mode": "base64",
                "oss_vl_access_key_id": "LTAIxxxx",
                "oss_vl_access_key_secret": "secret",
            }
        )
        self.assertEqual(resolve_ai_media_mode(get_arg), "dpe_base64")


class TestOssUrlBuilding(unittest.TestCase):
    def test_internal_object_url(self) -> None:
        url = oss_internal_object_url(
            cloud_region="cn_shanghai",
            bucket="my-bucket",
            object_key="clips/sha256:abc/runs/r1/_sdk_work/output/clips/output_0000/audio.wav",
        )
        self.assertEqual(
            url,
            "oss://oss-cn-shanghai-internal.aliyuncs.com/my-bucket/"
            "clips/sha256:abc/runs/r1/_sdk_work/output/clips/output_0000/audio.wav",
        )

    def test_image_mime_from_key(self) -> None:
        self.assertEqual(image_mime_from_key("panel.png"), "image/png")
        self.assertEqual(image_mime_from_key("frame.jpg"), "image/jpeg")

    def test_path_under_mount_to_oss_key(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            mount = Path(tmp) / "mnt" / "oss"
            file_path = mount / "clips" / "run1" / "frames" / "a.jpg"
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b"fake")
            key = path_under_mount_to_oss_key(file_path, mount)
            self.assertEqual(key, "clips/run1/frames/a.jpg")


if __name__ == "__main__":
    unittest.main()
