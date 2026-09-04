"""Platform datatype kernel: recipe, preflight, store, search isolation."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestRecipeValidation(unittest.TestCase):
    def test_seeds_validate(self) -> None:
        from hmi.platform.recipe import seed_recipes

        seeds = seed_recipes()
        self.assertEqual(set(seeds), {"oms_cabin", "ivi_ui_stub", "audio_array_spec"})
        self.assertEqual(seeds["oms_cabin"]["taxonomy_id"], "oms")
        self.assertEqual(seeds["ivi_ui_stub"]["taxonomy_id"], "ivi_ui_stub")
        self.assertNotEqual(seeds["oms_cabin"]["taxonomy_id"], seeds["ivi_ui_stub"]["taxonomy_id"])
        self.assertTrue(seeds["ivi_ui_stub"]["stages"]["label"]["enabled"])
        self.assertTrue(seeds["ivi_ui_stub"]["bbox"]["enabled"])
        self.assertEqual(seeds["ivi_ui_stub"]["bbox"]["detector"], "opencv")

    def test_missing_taxonomy_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        bad = dict(SEED_RECIPES["oms_cabin"])
        bad.pop("taxonomy_id")
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(bad)
        self.assertIn("taxonomy_id", str(ctx.exception))

    def test_unknown_op_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        bad = dict(SEED_RECIPES["oms_cabin"])
        bad["preprocess"] = [{"op_id": "not_a_real_op", "required": False}]
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(bad)
        self.assertIn("unknown op_id", str(ctx.exception))

    def test_unknown_view_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        bad = dict(SEED_RECIPES["oms_cabin"])
        bad["overview_view"] = "not_a_view"
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(bad)
        self.assertIn("overview_view", str(ctx.exception))

    def test_seeds_hydrate_overview_cards(self) -> None:
        from hmi.platform.recipe import seed_recipes

        seeds = seed_recipes()
        oms = seeds["oms_cabin"]["overview"]
        self.assertEqual(oms["preset"], "cabin_timeline")
        self.assertEqual([c["widget_id"] for c in oms["list"]], ["clip_metrics", "label_search", "clip_table"])
        self.assertEqual(
            [c["widget_id"] for c in oms["detail"]],
            ["labels_tree", "cabin_multicam", "asr_panel"],
        )
        nvh = seeds["audio_array_spec"]["overview"]
        self.assertEqual([c["widget_id"] for c in nvh["list"]], ["clip_metrics", "nvh_spl_column", "clip_table"])
        self.assertEqual([c["widget_id"] for c in nvh["detail"]], ["labels_tree", "nvh_spectrum"])
        ivi = seeds["ivi_ui_stub"]["overview"]
        self.assertEqual([c["widget_id"] for c in ivi["detail"]], ["labels_tree", "frame_gallery_bbox"])

    def test_unknown_overview_widget_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        bad = dict(SEED_RECIPES["oms_cabin"])
        bad["overview"] = {
            "preset": "cabin_timeline",
            "list": [{"key": "x", "widget_id": "not_a_widget", "bindings": {}}],
            "detail": [],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(bad)
        self.assertIn("unknown overview widget_id", str(ctx.exception))

    def test_overview_widget_wrong_surface_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        bad = dict(SEED_RECIPES["oms_cabin"])
        bad["overview"] = {
            "preset": "cabin_timeline",
            "list": [{"key": "x", "widget_id": "cabin_multicam", "bindings": {}}],
            "detail": [],
        }
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(bad)
        self.assertIn("belongs on detail", str(ctx.exception))

    def test_explicit_overview_list_kept(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        rec = dict(SEED_RECIPES["oms_cabin"])
        rec["overview"] = {
            "preset": "cabin_timeline",
            "list": [{"key": "t", "widget_id": "clip_table", "bindings": {}}],
            "detail": [{"key": "n", "widget_id": "nvh_spectrum", "bindings": {}}],
        }
        out = validate_recipe(rec)
        self.assertEqual([c["widget_id"] for c in out["overview"]["list"]], ["clip_table"])
        self.assertEqual(
            [c["widget_id"] for c in out["overview"]["detail"]],
            ["labels_tree", "nvh_spectrum"],
        )

    def test_vl_bbox_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        bad = dict(SEED_RECIPES["oms_cabin"])
        bad["bbox"] = {"enabled": True, "detector": "vl"}
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(bad)
        self.assertIn("opencv|yolo", str(ctx.exception))


class TestPreflight(unittest.TestCase):
    def test_text_only_oms_fails(self) -> None:
        from hmi.platform.preflight import preflight
        from hmi.platform.recipe import SEED_RECIPES

        result = preflight(SEED_RECIPES["oms_cabin"], ["text"])
        self.assertFalse(result["ok"])
        self.assertTrue(result["missing"])

    def test_image_ivi_ok(self) -> None:
        from hmi.platform.preflight import preflight
        from hmi.platform.recipe import SEED_RECIPES

        result = preflight(SEED_RECIPES["ivi_ui_stub"], ["image"])
        self.assertTrue(result["ok"])
        self.assertIn("detect_bbox", result["ops"])
        self.assertIn("label", result["ops"])

    def test_text_only_ivi_fails(self) -> None:
        from hmi.platform.preflight import preflight
        from hmi.platform.recipe import SEED_RECIPES

        result = preflight(SEED_RECIPES["ivi_ui_stub"], ["text"])
        self.assertFalse(result["ok"])

    def test_rosbag_oms_ok(self) -> None:
        from hmi.platform.preflight import preflight
        from hmi.platform.recipe import SEED_RECIPES

        result = preflight(SEED_RECIPES["oms_cabin"], ["rosbag"])
        self.assertTrue(result["ok"])
        self.assertIn("parse_bag", result["ops"])
        self.assertIn("label", result["ops"])


class TestProductCacheKey(unittest.TestCase):
    def test_stable_and_param_sensitive(self) -> None:
        from hmi.platform.cache import product_cache_key

        a = product_cache_key(["s2", "s1"], "detect_bbox", {"detector": "opencv"})
        b = product_cache_key(["s1", "s2"], "detect_bbox", {"detector": "opencv"})
        c = product_cache_key(["s1", "s2"], "detect_bbox", {"detector": "yolo"})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class TestStoreAndIsolation(unittest.TestCase):
    def setUp(self) -> None:
        import hmi.app_db as app_db

        self._orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._orig))
        app_db.ensure_schema()

    def test_seed_types_and_unknown_op_put(self) -> None:
        from hmi.platform.store import get_data_type, list_data_types, upsert_data_type

        ids = {t["id"] for t in list_data_types()}
        self.assertIn("oms_cabin", ids)
        self.assertIn("ivi_ui_stub", ids)
        oms = get_data_type("oms_cabin")
        assert oms is not None
        bad = dict(oms)
        bad["preprocess"] = [{"op_id": "nope"}]
        with self.assertRaises(ValueError):
            upsert_data_type(bad)

    def test_same_sample_two_types_two_runs(self) -> None:
        from hmi.platform.store import create_run, create_sample, get_run, put_run_y, put_source

        img = put_source(content=b"fake-jpeg", kind="image", filename="a.jpg")
        sample = create_sample([img["source_id"]])
        oms = create_run(sample["sample_id"], "oms_cabin")
        ivi = create_run(sample["sample_id"], "ivi_ui_stub")
        self.assertNotEqual(oms["run_id"], ivi["run_id"])
        put_run_y(oms["run_id"], {"scene": "oms"})
        put_run_y(ivi["run_id"], {"widget": "button"})
        y_oms = get_run(oms["run_id"])
        y_ivi = get_run(ivi["run_id"])
        assert y_oms and y_ivi
        self.assertEqual(y_oms["data_type_id"], "oms_cabin")
        self.assertEqual(y_ivi["data_type_id"], "ivi_ui_stub")
        self.assertEqual(y_oms["y"], {"scene": "oms"})
        self.assertEqual(y_ivi["y"], {"widget": "button"})
        self.assertEqual(y_oms["taxonomy_id"], "oms")
        self.assertEqual(y_ivi["taxonomy_id"], "ivi_ui_stub")

    def test_preflight_blocks_run(self) -> None:
        from hmi.platform.store import create_run, create_sample, put_source

        src = put_source(
            content=b"hello",
            kind="text",
            filename="a.txt",
            text_schema_id="generic_text",
        )
        sample = create_sample([src["source_id"]])
        with self.assertRaises(ValueError) as ctx:
            create_run(sample["sample_id"], "oms_cabin")
        self.assertIn("preflight failed", str(ctx.exception))

    def test_product_cache_skip(self) -> None:
        from hmi.platform.store import lookup_or_record_product

        first = lookup_or_record_product(input_ids=["a"], op_id="detect_bbox", params={"d": 1})
        second = lookup_or_record_product(input_ids=["a"], op_id="detect_bbox", params={"d": 1})
        self.assertFalse(first["skipped"])
        self.assertTrue(second["skipped"])
        self.assertEqual(first["cache_key"], second["cache_key"])

    def test_search_scope_requires_type(self) -> None:
        from fastapi import HTTPException

        from hmi.platform.search_scope import require_data_type_id, uses_oms_legacy_index

        self.assertEqual(require_data_type_id(None), "oms_cabin")
        with self.assertRaises(HTTPException) as ctx2:
            require_data_type_id("no_such_type")
        self.assertEqual(ctx2.exception.status_code, 404)
        self.assertTrue(uses_oms_legacy_index(require_data_type_id("oms_cabin")))
        self.assertFalse(uses_oms_legacy_index(require_data_type_id("ivi_ui_stub")))


if __name__ == "__main__":
    unittest.main()
