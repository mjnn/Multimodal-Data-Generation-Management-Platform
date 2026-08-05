"""Atomic capabilities unit tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from oms_multimodal.capabilities.clip_manifest import (
    clip_from_manifest,
    clip_to_manifest,
    write_clips_index,
)
from oms_multimodal.capabilities.types import RunContext
from oms_multimodal.rosbag_parser import AudioPayload, Clip, FramePayload


class TestRunContext(unittest.TestCase):
    def test_resolved_media_local(self) -> None:
        ctx = RunContext(run_dir=Path("/tmp/run"), media_mode="local")
        self.assertEqual(ctx.resolved_media_mode(), "local")

    def test_resolved_media_oss_when_prefix(self) -> None:
        ctx = RunContext(
            run_dir=Path("/tmp/run"),
            media_mode="auto",
            oss_bucket="b",
            oss_run_prefix="clips/x/runs/y/",
        )
        self.assertEqual(ctx.resolved_media_mode(), "oss")


class TestClipManifest(unittest.TestCase):
    def test_roundtrip(self) -> None:
        clip = Clip(
            clip_id="bag_0000",
            bag_name="bag.bag",
            start_timestamp_ns=0,
            end_timestamp_ns=int(18e9),
            duration_sec=18.0,
            frames=[FramePayload(topic="/cam", timestamp_ns=0, image_path="/tmp/f.jpg")],
            audio=AudioPayload(
                topic="/audio",
                timestamp_ns=0,
                audio_path="/tmp/a.wav",
                format="wav",
                duration_sec=18.0,
            ),
        )
        row = clip_to_manifest(clip)
        restored = clip_from_manifest(row)
        self.assertEqual(restored.clip_id, clip.clip_id)
        self.assertEqual(restored.frames[0].image_path, "/tmp/f.jpg")
        self.assertIsNotNone(restored.audio)

    def test_write_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = RunContext(run_dir=root)
            clip = Clip(
                clip_id="c0",
                bag_name="b.bag",
                start_timestamp_ns=0,
                end_timestamp_ns=1,
                duration_sec=1.0,
            )
            n = write_clips_index(ctx.clips_index_path, iter([clip]))
            self.assertEqual(n, 1)
            row = json.loads(ctx.clips_index_path.read_text(encoding="utf-8").strip())
            self.assertEqual(row["clip_id"], "c0")


if __name__ == "__main__":
    unittest.main()
