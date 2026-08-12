"""HMI-SDK-BBOX: pipeline bbox settings + preview manifest + enum_tree insights."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "piplinesdk"))
sys.path.insert(0, str(REPO / "shared"))


class TestPipelineBboxSettings(unittest.TestCase):
    def test_defaults_and_save_roundtrip(self) -> None:
        from hmi.local import pipeline_settings as ps

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pipeline_settings.json"
            ps._SETTINGS_PATH = path  # type: ignore[attr-defined]
            cfg = ps.get_pipeline_settings()
            self.assertFalse(cfg["bbox_enabled"])
            self.assertEqual(cfg["bbox_detector"], "opencv")
            self.assertTrue(cfg["encode_plain"])
            self.assertFalse(cfg["encode_bbox"])

            saved = ps.save_pipeline_settings(
                {
                    "bbox_enabled": True,
                    "bbox_detector": "opencv",
                    "bbox_element": "face",
                    "encode_plain": True,
                    "encode_bbox": False,
                    "bbox_in_label_prompt": True,
                    "bbox_face_attrs": True,
                }
            )
            self.assertTrue(saved["bbox_enabled"])
            self.assertEqual(saved["bbox_detector"], "opencv")
            self.assertEqual(saved["bbox_element"], "face")
            # Opening bbox forces encode_bbox
            self.assertTrue(saved["encode_bbox"])
            self.assertTrue(saved["bbox_in_label_prompt"])
            self.assertTrue(saved["bbox_face_attrs"])

            applied = ps.apply_bbox_settings_to_environ(saved)
            self.assertEqual(applied.get("BBOX_IN_LABEL_PROMPT"), "1")
            self.assertEqual(applied.get("BBOX_FACE_ATTRS"), "1")
            self.assertEqual(applied["BBOX_ENABLED"], "1")
            self.assertEqual(applied["BBOX_DETECTOR"], "opencv")
            self.assertEqual(applied["BBOX_ELEMENT"], "face")
            self.assertEqual(applied["ENCODE_BBOX"], "1")
            self.assertEqual(applied["ENCODE_PLAIN"], "1")
            self.assertEqual(applied.get("BBOX_YOLO_CLASSES", ""), "")

            # SDK smoke backends (stub) still accepted by apply_* for tests; not persisted via UI.
            applied_stub = ps.apply_bbox_settings_to_environ(
                {**saved, "bbox_detector": "stub"}
            )
            self.assertEqual(applied_stub["BBOX_DETECTOR"], "stub")

            # Legacy stub/noop migrate to opencv on save / get.
            migrated = ps.save_pipeline_settings({"bbox_detector": "stub"})
            self.assertEqual(migrated["bbox_detector"], "opencv")

            applied_off = ps.apply_bbox_settings_to_environ(
                {**saved, "bbox_face_attrs": False, "bbox_detector": "opencv"}
            )
            self.assertEqual(applied_off["BBOX_FACE_ATTRS"], "0")
            self.assertEqual(applied_off["BBOX_DETECTOR"], "opencv")

    def test_yolo_classes_roundtrip(self) -> None:
        from hmi.local import pipeline_settings as ps

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "pipeline_settings.json"
            ps._SETTINGS_PATH = path  # type: ignore[attr-defined]
            saved = ps.save_pipeline_settings(
                {
                    "bbox_enabled": True,
                    "bbox_detector": "yolo",
                    "bbox_yolo_classes": ["person", "cell phone", "car"],
                }
            )
            self.assertEqual(saved["bbox_yolo_classes"], "person,cell phone,car")
            applied = ps.apply_bbox_settings_to_environ(saved)
            self.assertEqual(applied["BBOX_YOLO_CLASSES"], "person,cell phone,car")
            self.assertEqual(applied["BBOX_DETECTOR"], "yolo")

            catalog = ps.get_bbox_yolo_class_catalog()
            self.assertGreaterEqual(len(catalog), 80)
            names = {c["name"] for c in catalog}
            self.assertIn("person", names)
            self.assertIn("cell phone", names)

            presets = {p["id"]: p for p in ps.get_bbox_yolo_class_presets()}
            self.assertIn("cabin_leftover", presets)
            cabin = presets["cabin_leftover"]
            self.assertEqual(cabin["mode"], "replace")
            self.assertIn("cell phone", cabin["names"])
            self.assertIn("laptop", cabin["names"])
            self.assertNotIn("face", cabin["names"])
            self.assertIn("OpenCV", cabin.get("hint", ""))

    def test_yolo_availability_helpers(self) -> None:
        from hmi.local import pipeline_settings as ps
        from oms_multimodal.bbox import yolo_available

        # After oms-multimodal-sdk[bbox] install this should be True in CI/dev.
        # Soft-assert shape only when missing so smoke envs without torch still pass catalog tests.
        ready = ps.is_yolo_ready()
        self.assertEqual(ready, yolo_available())
        if ready:
            ps.assert_bbox_settings_runnable(
                {"bbox_enabled": True, "bbox_detector": "yolo"}
            )
        else:
            with self.assertRaises(RuntimeError) as ctx:
                ps.assert_bbox_settings_runnable(
                    {"bbox_enabled": True, "bbox_detector": "yolo"}
                )
            self.assertIn("ultralytics", str(ctx.exception).lower())

    def test_detector_catalog(self) -> None:
        from hmi.local.pipeline_settings import get_bbox_detector_options

        ids = {d["id"] for d in get_bbox_detector_options()}
        self.assertNotIn("noop", ids)
        self.assertNotIn("stub", ids)
        self.assertIn("opencv", ids)
        self.assertIn("yolo", ids)


class TestPreviewManifestBbox(unittest.TestCase):
    def test_sdk_split_cameras(self) -> None:
        from oms_multimodal.capabilities.preview import (
            _split_cameras_from_preview_dir,
            write_preview_manifest,
        )

        with tempfile.TemporaryDirectory() as td:
            preview = Path(td) / "preview"
            preview.mkdir()
            (preview / "clip_preview_camera0.mp4").write_bytes(b"0")
            (preview / "clip_preview_camera1.mp4").write_bytes(b"1")
            (preview / "clip_preview_bbox_camera0.mp4").write_bytes(b"b0")
            (preview / "clip_preview_bbox_camera1.mp4").write_bytes(b"b1")
            plain, bbox = _split_cameras_from_preview_dir(preview)
            self.assertEqual(set(plain), {"camera0", "camera1"})
            self.assertEqual(set(bbox), {"camera0", "camera1"})
            path = write_preview_manifest(preview, clip_count=1)
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["bbox_camera_count"], 2)
            self.assertIn("cameras_bbox", doc)

    def test_manifest_for_api_bbox_url(self) -> None:
        from hmi.media import preview_manifest as pm

        doc = {
            "mode": "mp4",
            "fps": 15,
            "frame_count": 10,
            "start_time_ns": 0,
            "end_time_ns": 1_000_000_000,
            "grid_relpath": "preview/grid.mp4",
            "cameras": {
                "camera0": {"relpath": "preview/clip_preview_camera0.mp4", "frame_count": 10},
            },
            "cameras_bbox": {
                "camera0": {
                    "relpath": "preview/clip_preview_bbox_camera0.mp4",
                    "frame_count": 10,
                },
            },
        }
        api = pm.manifest_for_api("sha256:abc", "run-1", doc)
        self.assertTrue(api["has_bbox_preview"])
        self.assertTrue(api["has_plain_preview"])
        self.assertEqual(len(api["cameras"]), 1)
        self.assertIn("bbox_url", api["cameras"][0])
        self.assertIn("clip_preview_bbox_camera0.mp4", api["cameras"][0]["bbox_url"])

    def test_manifest_for_api_identical_plain_treated_as_bbox_only(self) -> None:
        """Legacy import copied bbox bytes into plain filenames — API must not enable 原图."""
        import tempfile
        from pathlib import Path

        from hmi.media import preview_manifest as pm

        clip_id = "sha256:plainbboxdup"
        run_id = "run-dup"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            art = root / "artifacts" / "clips" / "sha256__plainbboxdup" / "runs" / run_id / "preview"
            art.mkdir(parents=True)
            payload = b"fake-bbox-mp4-bytes"
            (art / "clip_preview_camera0.mp4").write_bytes(payload)
            (art / "clip_preview_bbox_camera0.mp4").write_bytes(payload)

            real_artifacts = pm.artifact_path

            def fake_ap(cid: str, rid: str, rel: str) -> Path:
                base = root / "artifacts" / "clips" / "sha256__plainbboxdup" / "runs" / rid
                return base.joinpath(*Path(rel).parts) if rel else base

            pm.artifact_path = fake_ap  # type: ignore[attr-defined]
            try:
                doc = {
                    "mode": "mp4",
                    "fps": 15,
                    "frame_count": 10,
                    "start_time_ns": 0,
                    "end_time_ns": 1_000_000_000,
                    "grid_relpath": "preview/grid.mp4",
                    "cameras": {
                        "camera0": {
                            "relpath": "preview/clip_preview_camera0.mp4",
                            "frame_count": 10,
                        },
                    },
                    "cameras_bbox": {
                        "camera0": {
                            "relpath": "preview/clip_preview_bbox_camera0.mp4",
                            "frame_count": 10,
                        },
                    },
                }
                api = pm.manifest_for_api(clip_id, run_id, doc)
                self.assertFalse(api["has_plain_preview"])
                self.assertTrue(api["has_bbox_preview"])
                self.assertEqual(api["cameras"][0]["url"], "")
                self.assertIn("bbox_url", api["cameras"][0])
            finally:
                pm.artifact_path = real_artifacts  # type: ignore[attr-defined]

    def test_manifest_for_api_bbox_only_disables_plain(self) -> None:
        from hmi.media import preview_manifest as pm

        doc = {
            "mode": "mp4",
            "fps": 15,
            "frame_count": 10,
            "start_time_ns": 0,
            "end_time_ns": 1_000_000_000,
            "grid_relpath": "preview/grid.mp4",
            "cameras": {},
            "cameras_bbox": {
                "camera0": {
                    "relpath": "preview/clip_preview_bbox_camera0.mp4",
                    "frame_count": 10,
                },
            },
        }
        api = pm.manifest_for_api("sha256:abc", "run-2", doc)
        self.assertTrue(api["has_bbox_preview"])
        self.assertFalse(api["has_plain_preview"])
        self.assertEqual(api["cameras"][0]["url"], "")
        self.assertIn("bbox_url", api["cameras"][0])


class TestEnumTreeInsights(unittest.TestCase):
    def test_enum_tree_leaf_ids(self) -> None:
        from hmi.taxonomy.insights import _enum_values

        node = {
            "dtype": "enum_tree",
            "value_schema": {
                "type": "enum_tree",
                "values": [
                    {"id": "group_a", "children": [{"id": "a1"}, {"id": "a2"}]},
                    {"id": "group_b"},
                ],
            },
        }
        self.assertEqual(_enum_values(node), ["a1", "a2", "group_b"])


if __name__ == "__main__":
    unittest.main()
