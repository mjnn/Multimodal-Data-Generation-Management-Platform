"""Tests for annotate_bbox + encode_preview + OMNI_VIDEO_VARIANT."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from oms_multimodal.bbox import StubDetector, resolve_detector
from oms_multimodal.capabilities.annotate_bbox import annotate_bboxes
from oms_multimodal.capabilities.clip_manifest import write_clips_index
from oms_multimodal.capabilities.encode_preview import encode_preview_videos
from oms_multimodal.capabilities.planner import CapabilityPlanner, RunRequest
from oms_multimodal.capabilities.types import RunContext
from oms_multimodal.mc.content_parts import omni_frame_paths, pick_preview_video_path
from oms_multimodal.rosbag_parser import AudioPayload, Clip, FramePayload


def _write_jpeg(path: Path, size: tuple[int, int] = (64, 48)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color=(40, 80, 120)).save(path, format="JPEG")


def _make_clip(root: Path) -> Clip:
    frame = root / "frame0.jpg"
    _write_jpeg(frame)
    wav = root / "audio.wav"
    # Minimal silent-ish wav header + a few samples (ffmpeg may still accept empty-ish)
    wav.write_bytes(
        b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
        b"\x80>\x00\x00\x00}\x00\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
    )
    fp = FramePayload(topic="/camera0/image", timestamp_ns=0, image_path=str(frame))
    return Clip(
        clip_id="c0",
        bag_name="demo.bag",
        start_timestamp_ns=0,
        end_timestamp_ns=int(1e9),
        duration_sec=1.0,
        frames=[fp],
        video_frames=[fp],
        audio=AudioPayload(
            topic="/audio",
            timestamp_ns=0,
            audio_path=str(wav),
            format="wav",
            duration_sec=1.0,
            sample_rate=16000,
        ),
    )


class TestBBoxCapability(unittest.TestCase):
    def test_stub_annotate_writes_sidecar_and_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = _make_clip(root / "media")
            ctx = RunContext(run_dir=root)
            write_clips_index(ctx.clips_index_path, iter([clip]))
            result = annotate_bboxes(ctx, detector=StubDetector())
            self.assertGreaterEqual(result.frame_count, 1)
            self.assertGreaterEqual(result.box_count, 1)
            self.assertTrue(ctx.bboxes_path.is_file())
            bbox_jpg = Path(clip.frames[0].image_path).with_name("frame0_bbox.jpg")
            self.assertTrue(bbox_jpg.is_file())
            # original preserved
            self.assertTrue(Path(clip.frames[0].image_path).is_file())

    def test_encode_bbox_after_annotate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = _make_clip(root / "media")
            ctx = RunContext(run_dir=root)
            write_clips_index(ctx.clips_index_path, iter([clip]))
            annotate_bboxes(ctx, detector=StubDetector())

            # Skip real ffmpeg if unavailable — mock encode path
            with patch(
                "oms_multimodal.capabilities.encode_preview.render_clip_preview_video",
                side_effect=lambda clip, out, **kw: self._fake_encode(clip, out, **kw),
            ):
                enc = encode_preview_videos(ctx, variants=("plain", "bbox"))
            self.assertEqual(enc.plain_count, 1)
            self.assertEqual(enc.bbox_count, 1)
            self.assertTrue(ctx.videos_path.is_file())

    def _fake_encode(self, clip, out, **kw):
        out = Path(out)
        if kw.get("filename_stem"):
            out = out.with_name(f"{kw['filename_stem']}{out.suffix or '.mp4'}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"fake-mp4")
        path = str(out.resolve())
        if kw.get("assign_clip_fields", True):
            clip.clip_video_path = path
            clip.clip_video_paths = {"/camera0/image": path}
        clip.clip_video_config = {
            "encoded_cameras": [{"camera_topic": "/camera0/image", "path": path}]
        }
        return path

    def test_planner_inserts_annotate_when_encode_bbox(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = CapabilityPlanner().plan(
                RunRequest(
                    run_dir=root,
                    need_asr=False,
                    need_label=False,
                    need_embed=False,
                    need_preview=False,
                    encode_plain=True,
                    encode_bbox=True,
                    skip_existing=True,
                )
            )
            ids = plan.capability_ids
            self.assertIn("annotate_bbox", ids)
            self.assertIn("encode_preview", ids)
            self.assertLess(ids.index("annotate_bbox"), ids.index("encode_preview"))

    def test_pick_preview_video_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plain = root / "plain.mp4"
            boxed = root / "bbox.mp4"
            plain.write_bytes(b"p")
            boxed.write_bytes(b"b")
            clip = Clip(
                clip_id="c",
                bag_name="b",
                start_timestamp_ns=0,
                end_timestamp_ns=1,
                duration_sec=1.0,
                clip_video_path=str(plain),
                clip_video_bbox_path=str(boxed),
            )
            with patch.dict(os.environ, {"OMNI_VIDEO_VARIANT": "auto"}):
                self.assertEqual(pick_preview_video_path(clip), str(boxed))
            with patch.dict(os.environ, {"OMNI_VIDEO_VARIANT": "plain"}):
                self.assertEqual(pick_preview_video_path(clip), str(plain))
            with patch.dict(os.environ, {"OMNI_VIDEO_VARIANT": "bbox"}):
                self.assertEqual(pick_preview_video_path(clip), str(boxed))

    def test_omni_frame_remap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "a.jpg"
            dst = root / "a_bbox.jpg"
            _write_jpeg(src)
            _write_jpeg(dst)
            clip = Clip(
                clip_id="c",
                bag_name="b",
                start_timestamp_ns=0,
                end_timestamp_ns=1,
                duration_sec=1.0,
                frames=[FramePayload(topic="/c", timestamp_ns=0, image_path=str(src))],
                bbox_frame_paths={str(src): str(dst)},
            )
            with patch.dict(os.environ, {"OMNI_VIDEO_VARIANT": "auto"}):
                self.assertEqual(omni_frame_paths(clip, limit=1), [str(dst)])
            with patch.dict(os.environ, {"OMNI_VIDEO_VARIANT": "plain"}):
                self.assertEqual(omni_frame_paths(clip, limit=1), [str(src)])

    def test_resolve_detector_env(self) -> None:
        with patch.dict(os.environ, {"BBOX_DETECTOR": "stub"}):
            self.assertEqual(resolve_detector().name, "stub")
        with patch.dict(os.environ, {"BBOX_DETECTOR": "noop"}):
            self.assertEqual(resolve_detector().name, "noop")
        with patch.dict(os.environ, {"BBOX_DETECTOR": "face"}):
            self.assertEqual(resolve_detector().name, "opencv")
        with patch.dict(os.environ, {"BBOX_DETECTOR": "opencv"}):
            self.assertEqual(resolve_detector().name, "opencv")
        with patch.dict(os.environ, {"BBOX_DETECTOR": "nope"}):
            with self.assertRaises(ValueError):
                resolve_detector()

    def test_resolve_haar_cascade_prefers_env_file(self) -> None:
        from oms_multimodal.bbox import resolve_haar_cascade_path

        with tempfile.TemporaryDirectory() as tmp:
            cascade = Path(tmp) / "custom_cascade.xml"
            cascade.write_text("<?xml version='1.0'?><opencv_storage></opencv_storage>\n", encoding="utf-8")
            with patch.dict(os.environ, {"BBOX_OPENCV_CASCADE": str(cascade)}):
                resolved = resolve_haar_cascade_path()
            self.assertEqual(resolved, cascade.resolve())

    def test_resolve_haar_cascade_falls_back_to_package(self) -> None:
        from oms_multimodal.bbox import resolve_haar_cascade_path
        from oms_multimodal.bbox.detector import _PKG_CASCADE_DIR

        empty = Path(tempfile.mkdtemp())
        try:
            with patch.dict(os.environ, {"BBOX_OPENCV_CASCADE": ""}, clear=False):
                # Simulate headless wheel: cv2.data.haarcascades points at empty dir
                with patch("cv2.data.haarcascades", str(empty) + os.sep, create=True):
                    resolved = resolve_haar_cascade_path("haarcascade_frontalface_default.xml")
            expected = (_PKG_CASCADE_DIR / "haarcascade_frontalface_default.xml").resolve()
            self.assertEqual(resolved, expected)
            self.assertTrue(resolved.is_file())
        finally:
            empty.rmdir()

    def test_resolve_haar_cascade_missing_actionable_error(self) -> None:
        from oms_multimodal.bbox import resolve_haar_cascade_path

        with self.assertRaises(RuntimeError) as ctx:
            resolve_haar_cascade_path("definitely_missing_cascade_xyz.xml")
        msg = str(ctx.exception)
        self.assertIn("OpenCV Haar cascade not found", msg)
        self.assertIn("BBOX_OPENCV_CASCADE", msg)
        self.assertIn("BBOX_DETECTOR=stub", msg)

    def test_resolve_yunet_model_package_default(self) -> None:
        from oms_multimodal.bbox import resolve_yunet_model_path
        from oms_multimodal.bbox.detector import _PKG_CASCADE_DIR

        with patch.dict(os.environ, {"BBOX_OPENCV_YUNET": ""}, clear=False):
            resolved = resolve_yunet_model_path()
        expected = (_PKG_CASCADE_DIR / "face_detection_yunet_2023mar.onnx").resolve()
        self.assertEqual(resolved, expected)
        self.assertTrue(resolved.is_file())

    def test_yolo_available_helper(self) -> None:
        from oms_multimodal.bbox import list_detectors, require_yolo_extra, yolo_available

        ready = yolo_available()
        yolo_row = next(d for d in list_detectors() if d["id"] == "yolo")
        self.assertEqual(yolo_row.get("available"), "1" if ready else "0")
        if ready:
            require_yolo_extra()
        else:
            with self.assertRaises(RuntimeError) as ctx:
                require_yolo_extra()
            self.assertIn("ultralytics", str(ctx.exception).lower())

    def test_opencv_face_on_blank_image(self) -> None:
        from oms_multimodal.bbox import OpenCvHaarDetector, list_detectors

        ids = {d["id"] for d in list_detectors()}
        self.assertEqual(ids, {"noop", "stub", "opencv", "yolo"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "blank.jpg"
            Image.new("RGB", (320, 240), color=(200, 180, 160)).save(path, format="JPEG")
            with patch.dict(os.environ, {"BBOX_ELEMENT": "element", "BBOX_FACE_ATTRS": "0"}, clear=False):
                # Clear cascade env so package fallback is exercised on headless wheels
                os.environ.pop("BBOX_OPENCV_CASCADE", None)
                os.environ.pop("BBOX_OPENCV_YUNET", None)
                det = OpenCvHaarDetector()
                boxes = det.detect(path)
            self.assertIsInstance(boxes, list)
            self.assertEqual(det.element, "element")
            self.assertIn(det._backend, {"haar", "yunet"})
            if det._backend == "haar":
                self.assertTrue(det.cascade_path is not None and det.cascade_path.is_file())
            else:
                self.assertTrue(det.yunet_path is not None and det.yunet_path.is_file())

    def test_resolve_yolo_class_ids_names_and_ids(self) -> None:
        from oms_multimodal.bbox import list_yolo_class_catalog, resolve_yolo_class_ids

        catalog = list_yolo_class_catalog()
        self.assertEqual(len(catalog), 80)
        self.assertEqual(resolve_yolo_class_ids(""), [])
        ids = resolve_yolo_class_ids("person,car,67")
        # person=0, car=2, 67=cell phone in COCO
        self.assertEqual(ids, [0, 2, 67])
        # duplicate / unknown skipped
        self.assertEqual(resolve_yolo_class_ids("person,person,not_a_class"), [0])

    def test_cabin_leftover_preset_in_coco(self) -> None:
        from oms_multimodal.bbox import (
            CABIN_LEFTOVER_COCO_NAMES,
            COCO80_CLASS_NAMES,
            list_yolo_class_presets,
            resolve_yolo_class_ids,
        )

        for name in CABIN_LEFTOVER_COCO_NAMES:
            self.assertIn(name, COCO80_CLASS_NAMES)
        self.assertNotIn("face", COCO80_CLASS_NAMES)
        presets = {p["id"]: p for p in list_yolo_class_presets()}
        cabin = presets["cabin_leftover"]
        self.assertEqual(cabin["mode"], "replace")
        self.assertEqual(tuple(cabin["names"]), CABIN_LEFTOVER_COCO_NAMES)
        ids = resolve_yolo_class_ids(",".join(CABIN_LEFTOVER_COCO_NAMES))
        self.assertEqual(len(ids), len(CABIN_LEFTOVER_COCO_NAMES))
        expected = [COCO80_CLASS_NAMES.index(n) for n in CABIN_LEFTOVER_COCO_NAMES]
        self.assertEqual(ids, expected)

    def test_bbox_element_field(self) -> None:
        from oms_multimodal.bbox import BBox

        box = BBox(x1=0, y1=0, x2=10, y2=10, element="person")
        self.assertEqual(box.label, "person")
        self.assertEqual(box.to_dict()["element"], "person")
        restored = BBox.from_dict({"x1": 0, "y1": 0, "x2": 1, "y2": 1, "label": "vehicle"})
        self.assertEqual(restored.element, "vehicle")


if __name__ == "__main__":
    unittest.main()
