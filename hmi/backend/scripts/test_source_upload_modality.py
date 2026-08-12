"""Smoke: source upload + planner modality gating (no DashScope)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT.parent / "piplinesdk"))


class TestSourceUploadModality(unittest.TestCase):
    def test_classify_and_save_sources(self) -> None:
        from hmi.data_source import LOCAL_OSS_ROOT
        from hmi.local import store
        from hmi.local.source_upload import classify_source_filename, save_uploaded_sources

        self.assertEqual(classify_source_filename("a.mp4"), "video")
        self.assertEqual(classify_source_filename("b.WAV"), "audio")
        self.assertEqual(classify_source_filename("c.txt"), "text")
        self.assertEqual(classify_source_filename("d.bag"), "bag")
        self.assertIsNone(classify_source_filename("x.bin"))

        store.ensure_db()
        with tempfile.TemporaryDirectory() as tmp:
            # Point LOCAL_OSS_ROOT via monkeypatch of module attribute used by save
            import hmi.local.source_upload as su

            prev = su.LOCAL_OSS_ROOT
            try:
                su.LOCAL_OSS_ROOT = Path(tmp) / "oss"
                su.LOCAL_OSS_ROOT.mkdir(parents=True, exist_ok=True)
                out = save_uploaded_sources(
                    [
                        ("demo/clip.mp4", b"fake-mp4-bytes"),
                        ("demo/note.txt", b"hello modality"),
                    ]
                )
                self.assertEqual(out["source_kind"], "raw_media")
                self.assertIn("video", out["modalities"])
                self.assertIn("text", out["modalities"])
                man = Path(out["local_path"])
                self.assertTrue(man.is_file())
                payload = json.loads(man.read_text(encoding="utf-8"))
                self.assertTrue(payload["has_preencoded_video"])
                self.assertTrue(out["bag_oss_key"].startswith("local://sources/"))
            finally:
                su.LOCAL_OSS_ROOT = prev

    def test_ingest_text_only(self) -> None:
        from oms_multimodal.capabilities import RunContext, ingest_sources
        from oms_multimodal.config import ClipConfig

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            text = root / "note.txt"
            text.write_text("event A\nevent B", encoding="utf-8")
            man = {
                "clip_id": "sha256:test",
                "modalities": ["text"],
                "text": str(text),
                "has_preencoded_video": False,
            }
            (root / "source_manifest.json").write_text(json.dumps(man), encoding="utf-8")
            ctx = RunContext(run_dir=root / "run", work_dir=root / "work", clip_id="sha256:test")
            result = ingest_sources(ctx, manifest=man, clip_config=ClipConfig(sample_fps=1.0))
            self.assertEqual(result.clip_rows, 1)
            self.assertTrue(ctx.clips_index_path.is_file())
            line = ctx.clips_index_path.read_text(encoding="utf-8").strip().splitlines()[0]
            row = json.loads(line)
            asr = (row.get("asr_text") or "").replace("\r", "")
            self.assertEqual(asr, "event A\nevent B")
            self.assertFalse(row.get("frames"))


if __name__ == "__main__":
    unittest.main()
