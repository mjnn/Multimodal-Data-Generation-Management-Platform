from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from oms_multimodal.capabilities.preview import materialize_preview
from oms_multimodal.capabilities.types import RunContext


def _touch_clip(clip_dir: Path, *, cameras: tuple[str, ...] = ("camera0",), with_audio: bool = True) -> None:
    clip_dir.mkdir(parents=True, exist_ok=True)
    for cam in cameras:
        (clip_dir / f"clip_preview_{cam}.mp4").write_bytes(b"mp4-" + cam.encode())
    if with_audio:
        (clip_dir / "audio.wav").write_bytes(b"wav-" + clip_dir.name.encode())


class TestMaterializePreview(unittest.TestCase):
    def test_single_clip_flat_layout_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            work = run_dir / "_sdk_work" / "bag" / "clips" / "output_0000"
            _touch_clip(work, cameras=("camera0", "camera1"))
            ctx = RunContext(run_dir=run_dir, clip_id="c", run_id="r", media_mode="local")
            ctx.work_dir = run_dir / "_sdk_work"

            preview = materialize_preview(ctx)

            self.assertTrue((preview / "clip_preview_camera0.mp4").is_file())
            self.assertTrue((preview / "clip_preview_camera1.mp4").is_file())
            self.assertTrue((preview / "audio.wav").is_file())
            doc = json.loads((preview / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["camera_count"], 2)
            self.assertEqual(doc["cameras"]["camera0"]["relpath"], "preview/clip_preview_camera0.mp4")

    def test_multi_clip_keeps_per_clip_and_promotes_primary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            clips_root = run_dir / "_sdk_work" / "bag" / "clips"
            _touch_clip(clips_root / "output_0000", cameras=("camera0",))
            _touch_clip(clips_root / "output_0001", cameras=("camera0",))
            ctx = RunContext(run_dir=run_dir, clip_id="c", run_id="r", media_mode="local")
            ctx.work_dir = run_dir / "_sdk_work"

            preview = materialize_preview(ctx)

            self.assertTrue((preview / "output_0000" / "clip_preview_camera0.mp4").is_file())
            self.assertTrue((preview / "output_0001" / "clip_preview_camera0.mp4").is_file())
            # Flat primary is first clip, not overwritten by second.
            self.assertEqual(
                (preview / "clip_preview_camera0.mp4").read_bytes(),
                (preview / "output_0000" / "clip_preview_camera0.mp4").read_bytes(),
            )
            self.assertEqual(
                (preview / "audio.wav").read_bytes(),
                (preview / "output_0000" / "audio.wav").read_bytes(),
            )
            doc = json.loads((preview / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(doc["clip_count"], 2)


if __name__ == "__main__":
    unittest.main()
