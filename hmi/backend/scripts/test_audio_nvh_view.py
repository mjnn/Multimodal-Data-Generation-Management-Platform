"""UI-NVH-OVERVIEW: audio_nvh view bootstrap + typed clip list."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestAudioNvhViewTemplates(unittest.TestCase):
    def test_view_and_recipe(self) -> None:
        from hmi.platform.recipe import seed_recipes
        from hmi.platform.views import VIEW_TEMPLATE_IDS

        self.assertIn("audio_nvh_timeline", VIEW_TEMPLATE_IDS)
        self.assertIn("audio_spec_asr", VIEW_TEMPLATE_IDS)
        rec = seed_recipes()["audio_array_spec"]
        self.assertEqual(rec["overview_view"], "audio_nvh_timeline")


class TestAudioNvhBootstrap(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        self.tmp = Path(tempfile.mkdtemp())
        import hmi.data_source as ds
        import hmi.local.store as local_store

        self._root = ds.LOCAL_ROOT
        ds.LOCAL_ROOT = self.tmp / "runtime"
        ds.LOCAL_ARTIFACTS_ROOT = ds.LOCAL_ROOT / "artifacts"
        local_store.LOCAL_ROOT = ds.LOCAL_ROOT
        local_store.LOCAL_DB_PATH = ds.LOCAL_ROOT / "hmi.db"
        self.addCleanup(lambda: setattr(ds, "LOCAL_ROOT", self._root))
        self.addCleanup(lambda: setattr(ds, "LOCAL_ARTIFACTS_ROOT", self._root / "artifacts"))

        clip_id = "sha256:nvh_test_clip"
        run_id = "run-nvh-1"
        root = ds.LOCAL_ARTIFACTS_ROOT / "clips" / "sha256__nvh_test_clip" / "runs" / run_id
        # artifact path uses safe clip dir
        from hmi.data_source import artifacts_dir

        root = artifacts_dir(clip_id, run_id)
        spec = root / "audio_spec"
        for ch in ("VL", "VR", "HL", "HR"):
            d = spec / ch
            d.mkdir(parents=True, exist_ok=True)
            (d / "mel.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (d / "stft.png").write_bytes(b"\x89PNG\r\n\x1a\n")
            (d / "waveform.json").write_text(
                json.dumps({"fs_display": 200, "samples": [0.1, -0.2, 0.0]}),
                encoding="utf-8",
            )
            with (d / "spl_timeline.jsonl").open("w", encoding="utf-8") as f:
                f.write(json.dumps({"t_s": 0.05, "spl_db": 90.0}) + "\n")
                f.write(json.dumps({"t_s": 0.15, "spl_db": 91.0}) + "\n")
        (spec / "summary.json").write_text(
            json.dumps(
                {
                    "fs_hz": 44100,
                    "duration_s": 1.0,
                    "unit": "Pa",
                    "channels": [
                        {"name": "VL", "leq_db": 94.1, "rms_pa": 1.0},
                        {"name": "VR", "leq_db": 94.2, "rms_pa": 1.0},
                        {"name": "HL", "leq_db": 94.0, "rms_pa": 1.0},
                        {"name": "HR", "leq_db": 94.3, "rms_pa": 1.0},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (root / "preview").mkdir(parents=True, exist_ok=True)
        (root / "preview" / "audio.wav").write_bytes(b"RIFF....WAVE")
        (root / "nvh_labels.json").write_text(
            json.dumps({"nvh.clip.spl.leq_db_mean": 94.15, "nvh.sem.noise_category": None}),
            encoding="utf-8",
        )
        self.clip_id = clip_id
        self.run_id = run_id

    def test_bootstrap(self) -> None:
        from hmi.local.audio_nvh_view import build_audio_nvh_bootstrap

        boot = build_audio_nvh_bootstrap(self.clip_id, self.run_id)
        self.assertIsNotNone(boot)
        assert boot is not None
        self.assertEqual(boot["view"], "audio_nvh_timeline")
        self.assertEqual(len(boot["channels"]), 4)
        self.assertTrue(boot["channels"][0]["mel_url"])
        self.assertAlmostEqual(boot["leq_db_mean"], 94.15, places=2)
        self.assertIn("nvh.clip.spl.leq_db_mean", boot["labels"])


class TestTypedClipList(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        self.tmp = Path(tempfile.mkdtemp())
        import hmi.local.store as local_store
        import hmi.data_source as ds

        self._root = local_store.LOCAL_ROOT
        self._db = local_store.LOCAL_DB_PATH
        local_store.LOCAL_ROOT = self.tmp / "runtime"
        local_store.LOCAL_DB_PATH = local_store.LOCAL_ROOT / "hmi.db"
        ds.LOCAL_ROOT = local_store.LOCAL_ROOT
        ds.LOCAL_ARTIFACTS_ROOT = local_store.LOCAL_ROOT / "artifacts"
        self.addCleanup(lambda: setattr(local_store, "LOCAL_ROOT", self._root))
        self.addCleanup(lambda: setattr(local_store, "LOCAL_DB_PATH", self._db))
        local_store.ensure_db()

        from hmi.local import pipeline_run as pr
        from hmi.local import pipeline_execution as pe

        clip_id = "sha256:audio_list_1"
        run_id = "run-audio-list"
        ds_day = "20260820"
        pr.upsert_clip_row(
            clip_id=clip_id,
            clip_dir_name="boardline_dat",
            content_hash="abc",
            bag_oss_key="local://sources/x/source_manifest.json",
            active_run_id=run_id,
        )
        pe.create_execution_record(
            run_id=run_id,
            label="test",
            started_at="2026-08-20T00:00:00Z",
            data_type_id="audio_array_spec",
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds_day, status="completed")
        self.clip_id = clip_id
        self.run_id = run_id

    def test_list_filters_by_data_type(self) -> None:
        from hmi.services.clips_local import list_clips_light_for_data_type

        rows = list_clips_light_for_data_type("audio_array_spec", refresh=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clip_id"], self.clip_id)
        self.assertEqual(rows[0]["data_type_id"], "audio_array_spec")
        empty = list_clips_light_for_data_type("ivi_ui_stub", refresh=True)
        self.assertEqual(empty, [])

    def test_ivi_list_also_filters_by_data_type(self) -> None:
        from hmi.local import pipeline_execution as pe
        from hmi.local import pipeline_run as pr
        from hmi.services.clips_local import list_clips_light_for_data_type

        clip_id = "sha256:ivi_list_1"
        run_id = "run-ivi-list"
        pr.upsert_clip_row(
            clip_id=clip_id,
            clip_dir_name="ivi_stub",
            content_hash="def",
            bag_oss_key="local://sources/y/source_manifest.json",
            active_run_id=run_id,
        )
        pe.create_execution_record(
            run_id=run_id,
            label="ivi",
            started_at="2026-08-20T01:00:00Z",
            data_type_id="ivi_ui_stub",
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds="20260820", status="completed")
        rows = list_clips_light_for_data_type("ivi_ui_stub", refresh=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["clip_id"], clip_id)
        self.assertEqual(rows[0]["data_type_id"], "ivi_ui_stub")
        # audio list still only the setUp row
        audio = list_clips_light_for_data_type("audio_array_spec", refresh=True)
        self.assertEqual([r["clip_id"] for r in audio], [self.clip_id])

    def test_oms_excludes_audio_and_ivi(self) -> None:
        """oms_cabin must not leak mic-array / IVI clips; audio channel still lists them."""
        from hmi.local import pipeline_execution as pe
        from hmi.local import pipeline_run as pr
        from hmi.services.clips_local import list_clips_light, list_clips_light_for_data_type

        oms_clip = "sha256:oms_legacy_1"
        oms_run = "run-oms-legacy"
        pr.upsert_clip_row(
            clip_id=oms_clip,
            clip_dir_name="demo_oms_bag",
            content_hash="oms",
            bag_oss_key="rosbags/demo.bag",
            active_run_id=oms_run,
        )
        # Legacy OMS: execution row without data_type_id
        pe.create_execution_record(
            run_id=oms_run,
            label="oms",
            started_at="2026-08-20T02:00:00Z",
            data_type_id=None,
        )
        pr.upsert_run(run_id=oms_run, clip_id=oms_clip, ds="20260820", status="completed")

        oms_typed = "sha256:oms_typed_1"
        oms_typed_run = "run-oms-typed"
        pr.upsert_clip_row(
            clip_id=oms_typed,
            clip_dir_name="oms_cabin_clip",
            content_hash="oms2",
            bag_oss_key="rosbags/oms2.bag",
            active_run_id=oms_typed_run,
        )
        pe.create_execution_record(
            run_id=oms_typed_run,
            label="oms",
            started_at="2026-08-20T02:30:00Z",
            data_type_id="oms_cabin",
        )
        pr.upsert_run(
            run_id=oms_typed_run, clip_id=oms_typed, ds="20260820", status="completed"
        )

        ivi_clip = "sha256:ivi_list_iso"
        ivi_run = "run-ivi-iso"
        pr.upsert_clip_row(
            clip_id=ivi_clip,
            clip_dir_name="ivi_stub_iso",
            content_hash="ivi",
            bag_oss_key="local://sources/z/source_manifest.json",
            active_run_id=ivi_run,
        )
        pe.create_execution_record(
            run_id=ivi_run,
            label="ivi",
            started_at="2026-08-20T03:00:00Z",
            data_type_id="ivi_ui_stub",
        )
        pr.upsert_run(run_id=ivi_run, clip_id=ivi_clip, ds="20260820", status="completed")

        oms_ids = {r["clip_id"] for r in list_clips_light(refresh=True)}
        self.assertIn(oms_clip, oms_ids)
        self.assertIn(oms_typed, oms_ids)
        self.assertNotIn(self.clip_id, oms_ids)
        self.assertNotIn(ivi_clip, oms_ids)

        via_dtype = {
            r["clip_id"] for r in list_clips_light_for_data_type("oms_cabin", refresh=True)
        }
        self.assertEqual(oms_ids, via_dtype)

        audio_ids = {
            r["clip_id"]
            for r in list_clips_light_for_data_type("audio_array_spec", refresh=True)
        }
        self.assertIn(self.clip_id, audio_ids)
        self.assertNotIn(oms_clip, audio_ids)
        self.assertNotIn(oms_typed, audio_ids)


if __name__ == "__main__":
    unittest.main()
