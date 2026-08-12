"""Tests for face age/gender attribute formatting and bbox schema (no model download)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from oms_multimodal.bbox import (
    BBox,
    age_approx_from_range,
    box_prompt_name,
    face_attrs_enabled,
    format_face_attr_label,
    reset_face_attr_estimator,
    summarize_bboxes_for_prompt,
)
from oms_multimodal.bbox.face_attrs import enrich_face_boxes


class TestFaceAttrFormatting(unittest.TestCase):
    def test_format_face_female_approx(self) -> None:
        self.assertEqual(
            format_face_attr_label("face", gender="female", age_range="25-32"),
            "face/female/~28y",
        )
        self.assertEqual(
            format_face_attr_label("face", gender="male", age_approx=40),
            "face/male/~40y",
        )
        self.assertEqual(format_face_attr_label("face"), "face")
        self.assertEqual(
            format_face_attr_label("element", gender="Female", age_range="(15-20)"),
            "element/female/~17y",
        )

    def test_age_approx_from_range(self) -> None:
        self.assertEqual(age_approx_from_range("25-32"), 28)
        self.assertEqual(age_approx_from_range("(60-100)"), 80)
        self.assertIsNone(age_approx_from_range("nope"))

    def test_bbox_schema_roundtrip(self) -> None:
        box = BBox(
            x1=1,
            y1=2,
            x2=3,
            y2=4,
            element="face",
            score=0.9,
            class_id=0,
            gender="female",
            age_range="25-32",
            age_approx=28,
        )
        self.assertEqual(box.display_name(), "face/female/~28y")
        self.assertEqual(box.base_name(), "face")
        d = box.to_dict()
        self.assertEqual(d["element"], "face")
        self.assertEqual(d["gender"], "female")
        self.assertEqual(d["age_range"], "25-32")
        self.assertEqual(d["age_approx"], 28)
        restored = BBox.from_dict(d)
        self.assertEqual(restored.display_name(), "face/female/~28y")
        # stub/yolo path: no attrs
        plain = BBox(0, 0, 1, 1, element="person", score=0.5)
        pd = plain.to_dict()
        self.assertNotIn("gender", pd)
        self.assertEqual(plain.display_name(), "person")

    def test_prompt_summary_uses_attr_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bboxes.jsonl"
            row = {
                "clip_id": "c1",
                "boxes": [
                    {
                        "element": "face",
                        "gender": "female",
                        "age_range": "25-32",
                        "age_approx": 28,
                        "score": 0.91,
                        "x1": 0,
                        "y1": 0,
                        "x2": 1,
                        "y2": 1,
                    },
                    {
                        "element": "face",
                        "gender": "female",
                        "age_range": "25-32",
                        "age_approx": 28,
                        "score": 0.8,
                        "x1": 0,
                        "y1": 0,
                        "x2": 1,
                        "y2": 1,
                    },
                ],
            }
            path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            text = summarize_bboxes_for_prompt(path, clip_id="c1")
            self.assertIn("face/female/~28y×2", text)
            self.assertIn("max=0.91", text)
            self.assertEqual(
                box_prompt_name(row["boxes"][0]),
                "face/female/~28y",
            )

    def test_face_attrs_env_toggle(self) -> None:
        with patch.dict(os.environ, {"BBOX_FACE_ATTRS": "0"}):
            self.assertFalse(face_attrs_enabled())
        with patch.dict(os.environ, {"BBOX_FACE_ATTRS": "1"}):
            self.assertTrue(face_attrs_enabled())

    def test_enrich_with_mock_estimator(self) -> None:
        import numpy as np

        reset_face_attr_estimator()
        img = np.zeros((100, 100, 3), dtype=np.uint8)
        box = BBox(10, 10, 50, 50, element="face")
        est = MagicMock()
        est.predict_bgr_crop.return_value = {
            "gender": "male",
            "age_range": "38-43",
            "age_approx": 40,
            "gender_score": 0.88,
            "age_score": 0.71,
        }
        enrich_face_boxes(img, [box], estimator=est)
        self.assertEqual(box.gender, "male")
        self.assertEqual(box.age_range, "38-43")
        self.assertEqual(box.age_approx, 40)
        self.assertEqual(box.gender_score, 0.88)
        self.assertEqual(box.age_score, 0.71)
        self.assertEqual(box.display_name(), "face/male/~40y")
        d = box.to_dict()
        self.assertEqual(d["gender_score"], 0.88)
        self.assertEqual(d["age_score"], 0.71)

    def test_opencv_detect_skips_attrs_when_disabled(self) -> None:
        from PIL import Image

        from oms_multimodal.bbox import OpenCvHaarDetector

        reset_face_attr_estimator()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.jpg"
            Image.new("RGB", (320, 240), color=(200, 180, 160)).save(path, format="JPEG")
            with patch.dict(
                os.environ,
                {"BBOX_FACE_ATTRS": "0", "BBOX_ELEMENT": "face"},
                clear=False,
            ):
                os.environ.pop("BBOX_OPENCV_CASCADE", None)
                os.environ.pop("BBOX_OPENCV_YUNET", None)
                det = OpenCvHaarDetector()
                boxes = det.detect(path)
            for b in boxes:
                self.assertIsNone(b.gender)
                self.assertIsNone(b.age_range)


if __name__ == "__main__":
    unittest.main()
