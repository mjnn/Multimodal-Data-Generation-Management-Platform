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
        from hmi.platform.file_kinds import AUDIO_EXTS, IMAGE_EXTS, VIDEO_EXTS
        from hmi.platform.recipe import eligible_kinds_for_recipe, seed_recipes

        seeds = seed_recipes()
        audio = seeds["audio_array_spec"]
        self.assertEqual(audio["slots"][0]["id"], "audio_primary")
        self.assertTrue(audio["products"])
        self.assertEqual(eligible_kinds_for_recipe(audio), set(AUDIO_EXTS))
        ivi = seeds["ivi_ui_stub"]
        self.assertEqual(eligible_kinds_for_recipe(ivi), set(VIDEO_EXTS) | set(IMAGE_EXTS))


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
        self.assertIn(".mp4", kinds)
        self.assertNotIn(".txt", kinds)
        self.assertNotIn("text", kinds)
        self.assertNotIn("video", kinds)

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

    def test_assignments_required_for_multi_slot(self) -> None:
        from hmi.platform.store import create_run_from_sources, put_source

        bag = put_source(content=b"x", kind="rosbag", filename="a.bag")
        with self.assertRaises(ValueError) as ctx:
            create_run_from_sources([bag["source_id"]], "oms_cabin")
        self.assertIn("assignments", str(ctx.exception).lower())

    def test_preflight_bare_source_ids_require_assignments_for_multi_slot(self) -> None:
        """api_preflight shares resolve_run_source_bindings with create_run_from_sources."""
        from hmi.platform.recipe import seed_recipes
        from hmi.platform.run_bind import resolve_run_source_bindings
        from hmi.platform.store import put_source

        bag = put_source(content=b"x", kind="rosbag", filename="preflight.bag")
        cabin = seed_recipes()["oms_cabin"]
        kind_map = {bag["source_id"]: ".bag"}
        with self.assertRaises(ValueError) as ctx:
            resolve_run_source_bindings(
                cabin,
                source_ids=[bag["source_id"]],
                assignments=None,
                source_kind_by_id=kind_map,
            )
        self.assertIn("assignments", str(ctx.exception).lower())

        # single-slot still auto-wraps (same helper used by preflight)
        wav = put_source(content=b"audio", kind="audio", filename="preflight.wav")
        audio = seed_recipes()["audio_array_spec"]
        ids = resolve_run_source_bindings(
            audio,
            source_ids=[wav["source_id"]],
            assignments=None,
            source_kind_by_id={wav["source_id"]: ".wav"},
        )
        self.assertEqual(ids, [wav["source_id"]])

    def test_single_slot_source_ids_still_works(self) -> None:
        from hmi.platform.store import create_run_from_sources, put_source

        wav = put_source(content=b"audio-bytes", kind="audio", filename="a.wav")
        run = create_run_from_sources([wav["source_id"]], "audio_array_spec")
        self.assertTrue(run["run_id"])

    def test_assignments_maps_wav_to_audio_slot(self) -> None:
        from hmi.platform.store import create_run_from_sources, put_source

        wav = put_source(content=b"audio-bytes", kind="audio", filename="b.wav")
        run = create_run_from_sources(
            [],
            "audio_array_spec",
            assignments=[{"slot_id": "audio_primary", "source_ids": [wav["source_id"]]}],
        )
        self.assertEqual(run["source_ids"], [wav["source_id"]])

    def test_assignment_rejects_wrong_kind_and_duplicate(self) -> None:
        from hmi.platform.run_bind import validate_source_assignments
        from hmi.platform.recipe import seed_recipes
        from hmi.platform.store import put_source

        wav = put_source(content=b"audio-bytes", kind="audio", filename="c.wav")
        mp4 = put_source(content=b"fake-mp4", kind="video", filename="c.mp4")
        recipe = seed_recipes()["audio_array_spec"]
        kinds = {wav["source_id"]: ".wav", mp4["source_id"]: ".mp4"}
        with self.assertRaises(ValueError) as ctx:
            validate_source_assignments(
                recipe,
                [{"slot_id": "audio_primary", "source_ids": [mp4["source_id"]]}],
                source_kind_by_id=kinds,
            )
        self.assertIn("audio_primary", str(ctx.exception))

        bag = put_source(content=b"bag-bytes", kind="rosbag", filename="d.bag")
        kinds[bag["source_id"]] = ".bag"
        cabin = seed_recipes()["oms_cabin"]
        with self.assertRaises(ValueError) as ctx2:
            validate_source_assignments(
                cabin,
                [
                    {"slot_id": "rosbag", "source_ids": [bag["source_id"]]},
                    {"slot_id": "video", "source_ids": [bag["source_id"]]},
                ],
                source_kind_by_id=kinds,
            )
        self.assertIn("multiple", str(ctx2.exception).lower())


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

    def test_list_products_includes_run_step_and_source(self) -> None:
        from hmi.platform.store import (
            create_run_from_sources,
            list_products,
            lookup_or_record_product,
            put_source,
        )

        src = put_source(content=b"audio-bytes", kind="audio", filename="lineage.wav")
        run = create_run_from_sources([src["source_id"]], "audio_array_spec")
        lookup_or_record_product(
            input_ids=[src["source_id"]],
            op_id="mel_spectrogram",
            params={"n_mels": 64},
            artifact_path="runs/x/audio_spec/mel.png",
            run_id=run["run_id"],
        )
        items = list_products(limit=50)
        self.assertGreaterEqual(len(items), 1)
        row = next(p for p in items if p["op_id"] == "mel_spectrogram")
        self.assertEqual(row["op_title"], "梅尔频谱")
        self.assertEqual(row["run_id"], run["run_id"])
        self.assertEqual(row["data_type_id"], "audio_array_spec")
        self.assertIn("麦克风阵列频谱", str(row.get("data_type_title") or ""))
        self.assertEqual(row["sources"][0]["filename"], "lineage.wav")
        self.assertIn(run["run_id"], row["lineage"])
        self.assertIn("梅尔频谱", row["lineage"])
        self.assertIn("lineage.wav", row["lineage"])
        self.assertIn("管线运行", row["lineage"])
        self.assertIn("数据源", row["lineage"])

    def test_list_products_walks_nested_product_to_source(self) -> None:
        from hmi.platform.store import list_products, lookup_or_record_product, put_source

        src = put_source(content=b"audio-bytes", kind="audio", filename="nested.wav")
        first = lookup_or_record_product(
            input_ids=[src["source_id"]],
            op_id="stft_spectrogram",
            artifact_path="runs/x/stft.npy",
        )
        lookup_or_record_product(
            input_ids=[first["cache_key"]],
            op_id="mel_spectrogram",
            artifact_path="runs/x/mel.png",
        )
        items = list_products(limit=50)
        row = next(
            p
            for p in items
            if p["op_id"] == "mel_spectrogram" and first["cache_key"] in p["input_ids"]
        )
        self.assertEqual(row["sources"][0]["filename"], "nested.wav")
        self.assertIn("nested.wav", row["lineage"])
        self.assertIn("未关联管线运行", row["lineage"])


if __name__ == "__main__":
    unittest.main()
