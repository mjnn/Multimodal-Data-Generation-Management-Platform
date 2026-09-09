"""PLAT-SOURCE-UNIT: lake groups and multi-slot run lock."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class SourceUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        self.tmp = Path(tempfile.mkdtemp())

        import hmi.app_db as app_db
        import hmi.local.store as local_store
        import hmi.local.bag_upload as bag_upload
        import hmi.local.source_upload as source_upload

        self._app_db = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = self.tmp / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._app_db))
        app_db.ensure_schema()

        self._local_root = local_store.LOCAL_ROOT
        self._local_db = local_store.LOCAL_DB_PATH
        local_store.LOCAL_ROOT = self.tmp / "runtime"
        local_store.LOCAL_DB_PATH = local_store.LOCAL_ROOT / "hmi.db"
        self.addCleanup(lambda: setattr(local_store, "LOCAL_ROOT", self._local_root))
        self.addCleanup(lambda: setattr(local_store, "LOCAL_DB_PATH", self._local_db))

        bag_upload.LOCAL_OSS_ROOT = local_store.LOCAL_ROOT / "oss"
        source_upload.LOCAL_OSS_ROOT = local_store.LOCAL_ROOT / "oss"
        local_store.ensure_db()

    def _wav_json(self) -> tuple[dict, dict]:
        from hmi.platform.store import put_source

        wav = put_source(content=b"audio-bytes", kind="audio", filename="clip.wav")
        js = put_source(
            content=b'{"tag":"x"}',
            kind=".json",
            filename="clip.json",
            text_schema_id="generic_json",
        )
        return wav, js

    def test_seed_types_multi_slot_flag(self) -> None:
        from hmi.platform.recipe import seed_recipes
        from hmi.platform.source_unit import recipe_uses_source_units

        seeds = seed_recipes()
        self.assertTrue(recipe_uses_source_units(seeds["oms_cabin"]))
        self.assertTrue(recipe_uses_source_units(seeds["audio_defect"]))
        self.assertFalse(recipe_uses_source_units(seeds["ivi_ui_stub"]))
        self.assertFalse(recipe_uses_source_units(seeds["audio_array_spec"]))

    def test_create_unit_min_two_and_multi_membership(self) -> None:
        from hmi.platform.store import create_source_unit, list_sources, put_source

        wav, js = self._wav_json()
        js2 = put_source(
            content=b'{"tag":"y"}',
            kind=".json",
            filename="other.json",
            text_schema_id="generic_json",
        )
        with self.assertRaises(ValueError):
            create_source_unit([wav["source_id"]])
        a = create_source_unit([wav["source_id"], js["source_id"]], title="pair-a")
        b = create_source_unit([wav["source_id"], js2["source_id"]], title="pair-b")
        self.assertEqual(a["title"], "pair-a")
        self.assertEqual({m["source_id"] for m in a["members"]}, {wav["source_id"], js["source_id"]})
        self.assertNotEqual(a["unit_id"], b["unit_id"])
        listed = list_sources()
        wav_row = next(x for x in listed if x["source_id"] == wav["source_id"])
        self.assertEqual(set(wav_row.get("unit_ids") or []), {a["unit_id"], b["unit_id"]})

    def test_audio_defect_run_requires_unit(self) -> None:
        from hmi.platform.source_unit import SourceUnitError
        from hmi.platform.store import create_run_from_sources, create_source_unit

        wav, js = self._wav_json()
        assignments = [
            {"slot_id": "src-1", "source_ids": [wav["source_id"]]},
            {"slot_id": "op-source-1788845633260", "source_ids": [js["source_id"]]},
        ]
        with self.assertRaises(SourceUnitError) as ctx:
            create_run_from_sources([], "audio_defect", assignments=assignments)
        self.assertEqual(ctx.exception.code, "SOURCE_UNIT_REQUIRED")

        unit = create_source_unit([wav["source_id"], js["source_id"]])
        run = create_run_from_sources(
            [],
            "audio_defect",
            assignments=assignments,
            unit_id=unit["unit_id"],
        )
        self.assertTrue(run["run_id"])

    def test_oms_cabin_two_slots_need_unit_one_slot_does_not(self) -> None:
        from hmi.platform.source_unit import SourceUnitError
        from hmi.platform.store import create_run_from_sources, create_source_unit, put_source

        bag = put_source(content=b"bag-bytes", kind="rosbag", filename="a.bag")
        wav = put_source(content=b"audio-bytes", kind="audio", filename="a.wav")
        one = create_run_from_sources(
            [],
            "oms_cabin",
            assignments=[{"slot_id": "rosbag", "source_ids": [bag["source_id"]]}],
        )
        self.assertTrue(one["run_id"])

        mixed = [
            {"slot_id": "rosbag", "source_ids": [bag["source_id"]]},
            {"slot_id": "audio", "source_ids": [wav["source_id"]]},
        ]
        with self.assertRaises(SourceUnitError) as ctx:
            create_run_from_sources([], "oms_cabin", assignments=mixed)
        self.assertEqual(ctx.exception.code, "SOURCE_UNIT_REQUIRED")

        unit = create_source_unit([bag["source_id"], wav["source_id"]])
        other_wav = put_source(content=b"other-audio", kind="audio", filename="b.wav")
        with self.assertRaises(SourceUnitError) as ctx2:
            create_run_from_sources(
                [],
                "oms_cabin",
                assignments=[
                    {"slot_id": "rosbag", "source_ids": [bag["source_id"]]},
                    {"slot_id": "audio", "source_ids": [other_wav["source_id"]]},
                ],
                unit_id=unit["unit_id"],
            )
        self.assertEqual(ctx2.exception.code, "SOURCE_UNIT_MISMATCH")

        ok = create_run_from_sources([], "oms_cabin", assignments=mixed, unit_id=unit["unit_id"])
        self.assertTrue(ok["run_id"])

    def test_single_slot_types_ignore_unit(self) -> None:
        from hmi.platform.store import create_run_from_sources, put_source

        wav = put_source(content=b"audio-bytes", kind="audio", filename="solo.wav")
        run = create_run_from_sources([wav["source_id"]], "audio_array_spec")
        self.assertTrue(run["run_id"])


if __name__ == "__main__":
    unittest.main()
