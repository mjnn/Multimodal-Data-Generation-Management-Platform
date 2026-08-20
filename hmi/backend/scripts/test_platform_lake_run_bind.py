"""PLAT-LAKE-RUN-BIND + slots + lineage."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class BindTestCase(unittest.TestCase):
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


class TestRecipeSlots(BindTestCase):
    def test_seeds_have_slots_and_products(self) -> None:
        from hmi.platform.recipe import eligible_kinds_for_recipe, seed_recipes

        seeds = seed_recipes()
        audio = seeds["audio_array_spec"]
        self.assertEqual(audio["slots"][0]["id"], "audio_primary")
        self.assertTrue(audio["products"])
        self.assertEqual(eligible_kinds_for_recipe(audio), {"audio"})
        ivi = seeds["ivi_ui_stub"]
        self.assertEqual(eligible_kinds_for_recipe(ivi), {"video", "image"})


class TestLakeRunBind(BindTestCase):
    def test_collection_id_shared_on_batch(self) -> None:
        from hmi.platform.store import put_source

        a = put_source(content=b"a", kind="video", filename="a.mp4", collection_id="col-1")
        b = put_source(content=b"b", kind="video", filename="b.mp4", collection_id="col-1")
        self.assertEqual(a["collection_id"], "col-1")
        self.assertEqual(b["collection_id"], "col-1")

    def test_list_sources_eligible_for_filters(self) -> None:
        from hmi.platform.store import list_sources, put_source

        put_source(content=b"txt", kind="text", filename="n.txt", text_schema_id="generic_text")
        put_source(content=b"vid", kind="video", filename="v.mp4")
        all_items = list_sources(limit=50)
        self.assertGreaterEqual(len(all_items), 2)
        ivi_only = list_sources(limit=50, eligible_for="ivi_ui_stub")
        kinds = {r["kind"] for r in ivi_only}
        self.assertIn("video", kinds)
        self.assertNotIn("text", kinds)

    def test_create_run_from_sources_auto_sample(self) -> None:
        from hmi.platform.store import create_run_from_sources, get_run, put_source

        video = put_source(content=b"fake-mp4", kind="video", filename="clip.mp4")
        run = create_run_from_sources([video["source_id"]], "ivi_ui_stub")
        self.assertTrue(run["run_id"])
        self.assertTrue(run["sample_id"])
        self.assertEqual(run["source_ids"], [video["source_id"]])
        row = get_run(run["run_id"])
        assert row is not None
        self.assertEqual(row["status"], "queued")


class TestProductLineage(BindTestCase):
    def test_lineage_for_source(self) -> None:
        from hmi.platform.store import lineage_for_source, lookup_or_record_product, put_source

        src = put_source(content=b"audio-bytes", kind="audio", filename="a.wav")
        hit = lookup_or_record_product(
            input_ids=[src["source_id"]],
            op_id="mel_spectrogram",
            params={"n_mels": 64},
            artifact_path="runs/x/audio_spec/mel.png",
            run_id="run-demo",
        )
        self.assertFalse(hit["skipped"])
        tree = lineage_for_source(src["source_id"])
        self.assertEqual(tree["product_count"], 1)
        self.assertEqual(tree["products"][0]["op_id"], "mel_spectrogram")
        self.assertEqual(tree["products"][0]["artifact_path"], "runs/x/audio_spec/mel.png")
        again = lookup_or_record_product(
            input_ids=[src["source_id"]],
            op_id="mel_spectrogram",
            params={"n_mels": 64},
        )
        self.assertTrue(again["skipped"])


if __name__ == "__main__":
    unittest.main()
