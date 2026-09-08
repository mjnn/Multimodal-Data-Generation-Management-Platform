"""ffmpeg resolution for encode_preview (Windows PATH often has no ffmpeg)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _bundled_ffmpeg_candidates() -> list[Path]:
    try:
        import imageio_ffmpeg
    except ImportError:
        return []
    binaries = Path(imageio_ffmpeg.__file__).resolve().parent / "binaries"
    if not binaries.is_dir():
        return []
    if sys.platform.startswith("win"):
        return [p for p in sorted(binaries.glob("ffmpeg*.exe")) if p.is_file()]
    return [
        p
        for p in sorted(binaries.glob("ffmpeg*"))
        if p.is_file() and p.suffix.lower() not in {".md", ".txt", ".py"}
    ]


class TestResolveFfmpeg(unittest.TestCase):
    def test_falls_back_to_bundled_binary_when_get_ffmpeg_exe_raises(self) -> None:
        """imageio_ffmpeg.get_ffmpeg_exe() can raise even when binaries/ exists.

        Production error on Windows HMI worker:
        'No ffmpeg exe could be found. ... IMAGEIO_FFMPEG_EXE ...'
        because _is_valid_exe() fails while the bundled file is on disk.
        """
        bundled = _bundled_ffmpeg_candidates()
        if not bundled:
            self.skipTest("imageio-ffmpeg bundled binary not installed")

        from oms_multimodal.clip_video import _resolve_ffmpeg

        with (
            patch("oms_multimodal.clip_video.shutil.which", return_value=None),
            patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": ""}, clear=False),
            patch(
                "imageio_ffmpeg.get_ffmpeg_exe",
                side_effect=RuntimeError(
                    "No ffmpeg exe could be found. Install ffmpeg on your system, "
                    "or set the IMAGEIO_FFMPEG_EXE environment variable."
                ),
            ),
        ):
            exe = _resolve_ffmpeg()
        self.assertTrue(Path(exe).is_file(), exe)
        self.assertTrue(Path(exe).name.lower().startswith("ffmpeg"), Path(exe).name)

    def test_prefers_imageio_ffmpeg_exe_env_when_file_exists(self) -> None:
        from oms_multimodal.clip_video import resolve_ffmpeg

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / ("ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg")
            fake.write_bytes(b"not-a-real-ffmpeg")
            with (
                patch("oms_multimodal.clip_video.shutil.which", return_value=None),
                patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": str(fake)}, clear=False),
            ):
                self.assertEqual(Path(resolve_ffmpeg()).resolve(), fake.resolve())

    def test_raises_clear_error_when_nothing_found(self) -> None:
        from oms_multimodal.clip_video import resolve_ffmpeg

        with (
            patch("oms_multimodal.clip_video.shutil.which", return_value=None),
            patch.dict(os.environ, {"IMAGEIO_FFMPEG_EXE": ""}, clear=False),
            patch("oms_multimodal.clip_video._bundled_ffmpeg_exe", return_value=None),
            patch(
                "imageio_ffmpeg.get_ffmpeg_exe",
                side_effect=RuntimeError("No ffmpeg exe could be found."),
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                resolve_ffmpeg()
        msg = str(ctx.exception)
        self.assertNotIn("IMAGEIO_FFMPEG_EXE environment variable", msg)
        self.assertIn("ffmpeg", msg.lower())


if __name__ == "__main__":
    unittest.main()
