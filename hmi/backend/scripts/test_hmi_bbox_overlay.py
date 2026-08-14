"""HMI-BBOX-OVERLAY: upsert_frame write-back for bboxes.jsonl."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))


class TestBboxJsonlUpsert(unittest.TestCase):
    def test_upsert_preserves_other_frames_and_coords(self) -> None:
        from hmi.media import bbox_jsonl as bj

        clip_id = "sha256:overlaytest"
        run_id = "run-overlay-1"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            art = (
                root
                / "artifacts"
                / "clips"
                / "sha256__overlaytest"
                / "runs"
                / run_id
            )
            art.mkdir(parents=True)
            path = art / "bboxes.jsonl"
            rows = [
                {
                    "clip_id": clip_id,
                    "topic": "/camera0/image_raw/compressed",
                    "timestamp_ns": 1000,
                    "boxes": [
                        {"x1": 10, "y1": 20, "x2": 30, "y2": 40, "element": "face", "score": 0.9}
                    ],
                    "extra_keep": True,
                },
                {
                    "clip_id": clip_id,
                    "topic": "/camera1/image_raw/compressed",
                    "timestamp_ns": 1000,
                    "boxes": [
                        {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "element": "person"}
                    ],
                },
            ]
            path.write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                encoding="utf-8",
            )

            def fake_artifact(cid: str, rid: str, rel: str = "") -> Path:
                base = root / "artifacts" / "clips" / "sha256__overlaytest" / "runs" / rid
                return base.joinpath(*Path(rel).parts) if rel else base

            with mock.patch.object(bj, "artifact_path", side_effect=fake_artifact), mock.patch.object(
                bj, "oss_key_path", side_effect=lambda key: root / "oss" / key
            ):
                got = bj.bboxes_at_timestamp(clip_id, run_id, 1000, window_ms=200)
                self.assertTrue(got["has_bboxes"])
                self.assertEqual(got["frame_count"], 2)
                face = next(d for d in got["detections"] if d["camera"] == "camera0")
                self.assertEqual(face["x1"], 10.0)

                result = bj.upsert_frame_boxes(
                    clip_id,
                    run_id,
                    timestamp_ns=1000,
                    camera="camera0",
                    topic="/camera0/image_raw/compressed",
                    boxes=[
                        {
                            "x1": 50,
                            "y1": 60,
                            "x2": 70,
                            "y2": 80,
                            "element": "face",
                            "display_label": "face/should-drop",
                            "score": 0.95,
                        }
                    ],
                )
                self.assertTrue(result["has_bboxes"])
                self.assertEqual(result["frame"]["boxes"][0]["x1"], 50.0)
                self.assertNotIn("display_label", json.loads(path.read_text(encoding="utf-8").splitlines()[0])["boxes"][0])

                raw = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
                self.assertEqual(len(raw), 2)
                cam0 = next(r for r in raw if "camera0" in r["topic"])
                cam1 = next(r for r in raw if "camera1" in r["topic"])
                self.assertTrue(cam0.get("extra_keep"))
                self.assertEqual(cam0["boxes"][0]["x1"], 50)
                self.assertEqual(cam1["boxes"][0]["x1"], 1)

                again = bj.bboxes_at_timestamp(clip_id, run_id, 1000, window_ms=200)
                face2 = next(d for d in again["detections"] if d["camera"] == "camera0")
                self.assertEqual((face2["x1"], face2["y1"], face2["x2"], face2["y2"]), (50.0, 60.0, 70.0, 80.0))

    def test_upsert_creates_file_when_missing(self) -> None:
        from hmi.media import bbox_jsonl as bj

        clip_id = "sha256:newbbox"
        run_id = "run-new"
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)

            def fake_artifact(cid: str, rid: str, rel: str = "") -> Path:
                base = root / "artifacts" / "clips" / "sha256__newbbox" / "runs" / rid
                return base.joinpath(*Path(rel).parts) if rel else base

            with mock.patch.object(bj, "artifact_path", side_effect=fake_artifact), mock.patch.object(
                bj, "oss_key_path", side_effect=lambda key: root / "oss" / key
            ):
                result = bj.upsert_frame_boxes(
                    clip_id,
                    run_id,
                    timestamp_ns=5000,
                    camera="camera0",
                    boxes=[{"x1": 0, "y1": 0, "x2": 10, "y2": 10, "element": "face"}],
                )
                self.assertTrue(result["has_bboxes"])
                self.assertEqual(result["frame_count"], 1)
                path = fake_artifact(clip_id, run_id, "bboxes.jsonl")
                self.assertTrue(path.is_file())


if __name__ == "__main__":
    unittest.main()
