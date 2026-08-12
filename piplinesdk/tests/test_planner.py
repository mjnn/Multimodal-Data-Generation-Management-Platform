"""Tests for CapabilityPlanner."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oms_multimodal.capabilities.planner import CapabilityPlanner, RunRequest
from oms_multimodal.rosbag_parser import TopicInfo


class TestCapabilityPlanner(unittest.TestCase):
    def test_skips_asr_when_no_audio_topics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bag = Path(tmp) / "x.bag"
            bag.write_bytes(b"fake")
            topics = [
                TopicInfo(name="/cam", msgtype="sensor_msgs/msg/Image", modality="image", message_count=10)
            ]
            with patch("oms_multimodal.capabilities.planner.inspect_bag", return_value=topics):
                plan = CapabilityPlanner().plan(
                    RunRequest(
                        bag_path=bag,
                        run_dir=tmp,
                        need_label=False,
                        need_embed=False,
                        need_preview=False,
                        encode_plain=False,
                        encode_bbox=False,
                        bbox_enabled=False,
                    )
                )
            self.assertIn("extract", plan.capability_ids)
            self.assertNotIn("transcribe", plan.capability_ids)

    def test_skips_extract_when_clips_index_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clips_index.jsonl").write_text('{"clip_id":"c0"}\n', encoding="utf-8")
            plan = CapabilityPlanner().plan(
                RunRequest(
                    bag_path=None,
                    run_dir=root,
                    need_asr=False,
                    need_label=True,
                    need_embed=False,
                    need_preview=False,
                    encode_plain=False,
                    encode_bbox=False,
                    bbox_enabled=False,
                    skip_existing=True,
                )
            )
            self.assertNotIn("extract", plan.capability_ids)
            self.assertEqual(plan.capability_ids, ["label"])

    def test_encode_bbox_inserts_annotate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=tmp,
                    need_asr=False,
                    need_label=False,
                    need_embed=False,
                    need_preview=False,
                    encode_plain=False,
                    encode_bbox=True,
                )
            )
            self.assertEqual(plan.capability_ids[:2], ["annotate_bbox", "encode_preview"])

    def test_default_includes_encode_plain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bag = Path(tmp) / "x.bag"
            bag.write_bytes(b"x")
            topics = [
                TopicInfo(name="/cam", msgtype="sensor_msgs/msg/Image", modality="image", message_count=1),
                TopicInfo(name="/audio", msgtype="audio_common_msgs/msg/AudioData", modality="audio", message_count=1),
            ]
            with patch("oms_multimodal.capabilities.planner.inspect_bag", return_value=topics):
                with patch.dict("os.environ", {"ENCODE_PLAIN": "true", "ENCODE_BBOX": "false", "BBOX_ENABLED": "false"}):
                    plan = CapabilityPlanner().plan(
                        RunRequest(bag_path=bag, run_dir=tmp, skip_existing=True)
                    )
            ids = plan.capability_ids
            self.assertEqual(ids[0], "extract")
            self.assertIn("encode_preview", ids)
            self.assertNotIn("annotate_bbox", ids)
            self.assertIn("transcribe", ids)

    def test_preencoded_video_skips_encode_keeps_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            video = root / "clip.mp4"
            video.write_bytes(b"fake-mp4")
            manifest = {
                "modalities": ["video"],
                "video": str(video),
                "has_preencoded_video": True,
            }
            (root / "source_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            plan = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=root,
                    need_label=True,
                    need_embed=False,
                    need_preview=False,
                    encode_plain=True,
                    encode_bbox=False,
                    bbox_enabled=False,
                )
            )
            ids = plan.capability_ids
            self.assertIn("ingest_sources", ids)
            self.assertNotIn("extract", ids)
            self.assertNotIn("encode_preview", ids)
            self.assertNotIn("transcribe", ids)
            self.assertIn("label", ids)

    def test_audio_only_skips_video_stages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audio = root / "a.wav"
            audio.write_bytes(b"RIFF")
            (root / "source_manifest.json").write_text(
                json.dumps(
                    {
                        "modalities": ["audio"],
                        "audio": str(audio),
                        "has_preencoded_video": False,
                    }
                ),
                encoding="utf-8",
            )
            plan = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=root,
                    encode_plain=True,
                    encode_bbox=True,
                    bbox_enabled=True,
                    need_preview=False,
                    need_embed=False,
                )
            )
            ids = plan.capability_ids
            self.assertIn("ingest_sources", ids)
            self.assertIn("transcribe", ids)
            self.assertNotIn("encode_preview", ids)
            self.assertNotIn("annotate_bbox", ids)
            self.assertIn("label", ids)

    def test_text_only_skips_asr_and_video(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / "note.txt"
            text.write_text("hello", encoding="utf-8")
            (root / "source_manifest.json").write_text(
                json.dumps({"modalities": ["text"], "text": str(text)}),
                encoding="utf-8",
            )
            plan = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=root,
                    encode_plain=True,
                    bbox_enabled=True,
                    need_embed=True,
                    need_preview=True,
                )
            )
            ids = plan.capability_ids
            self.assertEqual(ids, ["ingest_sources", "label", "embed"])

    def test_explicit_modality_overrides(self) -> None:
        plan = CapabilityPlanner().plan(
            RunRequest(
                has_video=False,
                has_audio=False,
                has_text=True,
                need_preview=False,
                need_embed=False,
                encode_plain=False,
                bbox_enabled=False,
            )
        )
        self.assertEqual(plan.capability_ids, ["label"])


if __name__ == "__main__":
    unittest.main()
