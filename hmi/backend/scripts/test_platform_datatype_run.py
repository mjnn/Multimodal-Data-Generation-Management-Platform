"""PLAT-DTYPE-RUN: DataType preflight before pipeline enqueue + recipe overlay."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestRunBindPreflight(unittest.TestCase):
    def setUp(self) -> None:
        import hmi.app_db as app_db

        self._orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._orig))
        app_db.ensure_schema()

    def test_missing_type_rejected(self) -> None:
        from hmi.platform.run_bind import PreflightError, require_published_preflight

        with self.assertRaises(PreflightError) as ctx:
            require_published_preflight("", ["a.bag"])
        self.assertIn("请选择", str(ctx.exception))

    def test_text_only_oms_fails(self) -> None:
        from hmi.platform.run_bind import PreflightError, require_published_preflight

        with self.assertRaises(PreflightError) as ctx:
            require_published_preflight("oms_cabin", ["note.txt"])
        self.assertTrue(ctx.exception.missing)
        self.assertIn("预检失败", str(ctx.exception))

    def test_bag_oms_ok(self) -> None:
        from hmi.platform.run_bind import require_published_preflight

        pf = require_published_preflight("oms_cabin", ["clip.bag"])
        self.assertTrue(pf["ok"])
        self.assertIn(".bag", pf["source_kinds"])
        self.assertIn("parse_bag", pf["ops"])

    def test_video_ivi_ok(self) -> None:
        from hmi.platform.run_bind import require_published_preflight

        pf = require_published_preflight("ivi_ui_stub", ["screen.mp4"])
        self.assertTrue(pf["ok"])
        self.assertIn("detect_bbox", pf["ops"])

    def test_bag_ivi_fails(self) -> None:
        from hmi.platform.run_bind import PreflightError, require_published_preflight

        with self.assertRaises(PreflightError) as ctx:
            require_published_preflight("ivi_ui_stub", ["clip.bag"])
        self.assertIn("ivi", ctx.exception.data_type_id)


class TestRecipeOverlay(unittest.TestCase):
    def test_ivi_forces_bbox_and_disables_label(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES
        from hmi.platform.run_bind import overlay_run_request

        out = overlay_run_request(
            SEED_RECIPES["ivi_ui_stub"],
            {"bbox_enabled": False, "bbox_detector": "yolo"},
        )
        self.assertFalse(out["need_label"])
        self.assertFalse(out["need_embed"])
        self.assertTrue(out["bbox_enabled"])
        self.assertEqual(out["bbox_detector"], "opencv")

    def test_oms_keeps_optional_bbox_from_settings(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES
        from hmi.platform.run_bind import overlay_run_request

        off = overlay_run_request(SEED_RECIPES["oms_cabin"], {"bbox_enabled": False})
        self.assertTrue(off["need_label"])
        self.assertTrue(off["need_embed"])
        self.assertFalse(off["bbox_enabled"])
        on = overlay_run_request(
            SEED_RECIPES["oms_cabin"],
            {"bbox_enabled": True, "bbox_detector": "yolo"},
        )
        self.assertTrue(on["bbox_enabled"])
        self.assertEqual(on["bbox_detector"], "yolo")


class TestSameSampleTwoTypes(unittest.TestCase):
    def setUp(self) -> None:
        import hmi.app_db as app_db

        self._orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._orig))
        app_db.ensure_schema()

    def test_record_two_runs_do_not_clobber_y(self) -> None:
        from hmi.platform.run_bind import record_execution_platform_run
        from hmi.platform.store import get_run, put_run_y

        files = [("cabin.mp4", b"fake-mp4-bytes")]
        oms = record_execution_platform_run(
            files=files,
            data_type_id="oms_cabin",
            pipeline_run_id="pipe-oms",
            sample_id="sample-shared",
        )
        ivi = record_execution_platform_run(
            files=files,
            data_type_id="ivi_ui_stub",
            pipeline_run_id="pipe-ivi",
            sample_id="sample-shared",
        )
        self.assertEqual(oms["sample_id"], ivi["sample_id"])
        self.assertNotEqual(oms["run_id"], ivi["run_id"])
        put_run_y(oms["run_id"], {"scene": "oms"})
        put_run_y(ivi["run_id"], {"widget": "button"})
        y_oms = get_run(oms["run_id"])
        y_ivi = get_run(ivi["run_id"])
        assert y_oms and y_ivi
        self.assertEqual(y_oms["y"], {"scene": "oms"})
        self.assertEqual(y_ivi["y"], {"widget": "button"})
        self.assertEqual(oms["preflight"].get("pipeline_run_id"), "pipe-oms")
        self.assertEqual(ivi["preflight"].get("pipeline_run_id"), "pipe-ivi")


if __name__ == "__main__":
    unittest.main()
