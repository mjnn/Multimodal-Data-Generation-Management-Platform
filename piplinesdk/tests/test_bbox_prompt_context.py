"""Tests for BBox → Omni label prompt injection."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from oms_multimodal.bbox import load_bbox_context_by_clip, summarize_bboxes_for_prompt
from oms_multimodal.capabilities.label import attach_bbox_context_to_clips
from oms_multimodal.capabilities.planner import CapabilityPlanner, RunRequest
from oms_multimodal.capabilities.types import RunContext
from oms_multimodal.label_prompt import build_omni_user_text
from oms_multimodal.rosbag_parser import Clip


def _bbox_row(clip_id: str, boxes: list[dict]) -> dict:
    return {
        "clip_id": clip_id,
        "topic": "/cam",
        "timestamp_ns": 1,
        "image_path": "f.jpg",
        "boxes": boxes,
        "elements": boxes,
    }


class TestBBoxPromptContext(unittest.TestCase):
    def test_summarize_unique_elements_with_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bboxes.jsonl"
            rows = [
                _bbox_row(
                    "c1",
                    [
                        {"element": "person", "score": 0.9, "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                        {"element": "person", "score": 0.8, "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                        {"label": "cell phone", "score": 0.7, "x1": 0, "y1": 0, "x2": 1, "y2": 1},
                    ],
                ),
                _bbox_row(
                    "c1",
                    [{"element": "cup", "score": 0.6, "x1": 0, "y1": 0, "x2": 1, "y2": 1}],
                ),
                _bbox_row(
                    "c2",
                    [{"element": "car", "score": 0.95, "x1": 0, "y1": 0, "x2": 1, "y2": 1}],
                ),
            ]
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )
            text = summarize_bboxes_for_prompt(path, clip_id="c1")
            self.assertIn("person×2", text)
            self.assertIn("max=0.90", text)
            self.assertIn("cell phone×1", text)
            self.assertIn("cup×1", text)
            self.assertNotIn("car", text)

            by_clip = load_bbox_context_by_clip(path)
            self.assertIn("c1", by_clip)
            self.assertIn("c2", by_clip)
            self.assertIn("car×1", by_clip["c2"])

    def test_build_omni_user_text_includes_detected_objects(self) -> None:
        user = build_omni_user_text(
            duration_sec=12.0,
            speech_context="[ASR transcript]\nhello",
            event_text="",
            params=None,
            bbox_context="person×3 (max=0.91), cup×1 (max=0.55)",
        )
        self.assertIn("Detected objects:", user)
        self.assertIn("person×3 (max=0.91)", user)
        self.assertIn("BBox", user)  # user_bbox_hint

    def test_build_omni_user_text_omits_block_when_empty(self) -> None:
        user = build_omni_user_text(
            duration_sec=5.0,
            speech_context="",
            event_text="",
            params=None,
            bbox_context="",
        )
        self.assertNotIn("Detected objects:", user)

    def test_attach_bbox_context_respects_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bboxes = root / "bboxes.jsonl"
            boxes = [{"element": "face", "score": 0.88, "x1": 0, "y1": 0, "x2": 1, "y2": 1}]
            bboxes.write_text(
                json.dumps(_bbox_row("clip-a", boxes), ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            ctx = RunContext(run_dir=root)
            clip = Clip(
                clip_id="clip-a",
                bag_name="b",
                start_timestamp_ns=0,
                end_timestamp_ns=1,
                duration_sec=1.0,
            )
            attach_bbox_context_to_clips(ctx, [clip], include_bbox_context=True)
            self.assertEqual(clip.bbox_context_text, "face×1 (max=0.88)")

            clip2 = Clip(
                clip_id="clip-a",
                bag_name="b",
                start_timestamp_ns=0,
                end_timestamp_ns=1,
                duration_sec=1.0,
            )
            attach_bbox_context_to_clips(ctx, [clip2], include_bbox_context=False)
            self.assertIsNone(clip2.bbox_context_text)

    def test_planner_passes_include_bbox_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=tmp,
                    need_asr=False,
                    need_embed=False,
                    need_preview=False,
                    encode_plain=False,
                    encode_bbox=False,
                    bbox_enabled=False,
                    bbox_in_label_prompt=True,
                    has_text=True,
                    has_video=False,
                    has_audio=False,
                )
            )
            self.assertEqual(plan.capability_ids, ["label"])
            self.assertTrue(plan.steps[0].params.get("include_bbox_context"))

            plan_off = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=tmp,
                    need_asr=False,
                    need_embed=False,
                    need_preview=False,
                    encode_plain=False,
                    bbox_enabled=False,
                    bbox_in_label_prompt=False,
                    has_text=True,
                    has_video=False,
                    has_audio=False,
                )
            )
            self.assertFalse(plan_off.steps[0].params.get("include_bbox_context"))

    def test_planner_bbox_before_label_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plan = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=tmp,
                    need_asr=False,
                    need_embed=False,
                    need_preview=False,
                    encode_plain=False,
                    encode_bbox=True,
                    bbox_enabled=True,
                    bbox_in_label_prompt=True,
                    has_video=True,
                    has_audio=False,
                )
            )
            ids = plan.capability_ids
            self.assertIn("annotate_bbox", ids)
            self.assertIn("label", ids)
            self.assertLess(ids.index("annotate_bbox"), ids.index("label"))
            label_step = next(s for s in plan.steps if s.capability_id == "label")
            self.assertTrue(label_step.params.get("include_bbox_context"))


if __name__ == "__main__":
    unittest.main()
