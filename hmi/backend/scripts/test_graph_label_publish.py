"""Graph labels persist to the recipe taxonomy, not NVH, when fill/AI wrote the tree."""

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


class TestGraphLabelPublish(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        os.environ.setdefault("HMI_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
        self.tmp = Path(tempfile.mkdtemp())
        import hmi.app_db as app_db
        import hmi.data_source as ds

        self._app = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = self.tmp / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._app))
        app_db.ensure_schema()
        from hmi.platform.store import ensure_platform_schema

        ensure_platform_schema()

        import hmi.local.store as local_store

        self._root = ds.LOCAL_ROOT
        ds.LOCAL_ROOT = self.tmp / "runtime"
        ds.LOCAL_ARTIFACTS_ROOT = ds.LOCAL_ROOT / "artifacts"
        ds.LOCAL_OSS_ROOT = ds.LOCAL_ROOT / "oss"
        ds.LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
        local_store.LOCAL_ROOT = ds.LOCAL_ROOT
        local_store.LOCAL_DB_PATH = ds.LOCAL_ROOT / "hmi.db"
        self.addCleanup(lambda: setattr(ds, "LOCAL_ROOT", self._root))
        self.addCleanup(lambda: setattr(ds, "LOCAL_ARTIFACTS_ROOT", self._root / "artifacts"))
        local_store.ensure_db()

    def test_array_spec_uses_nvh_taxonomy(self) -> None:
        from hmi.platform.graph_label_publish import recipe_uses_nvh_taxonomy
        from hmi.platform.recipe import seed_recipes

        seeds = seed_recipes()
        self.assertTrue(recipe_uses_nvh_taxonomy(seeds["audio_array_spec"]))
        self.assertFalse(recipe_uses_nvh_taxonomy(seeds["audio_defect"]))
        self.assertFalse(recipe_uses_nvh_taxonomy(seeds["oms_cabin"]))
        self.assertFalse(recipe_uses_nvh_taxonomy(None))

    def test_decide_fill_on_defect_is_recipe_not_nvh(self) -> None:
        from hmi.platform.graph_label_publish import decide_graph_label_publish
        from hmi.platform.recipe import seed_recipes

        ctx = {"labels": {"values": {"audio.defect.has_problem": {"value": True}}}}
        self.assertEqual(decide_graph_label_publish(seed_recipes()["audio_defect"], ctx), "recipe")
        self.assertEqual(decide_graph_label_publish(seed_recipes()["audio_array_spec"], ctx), "nvh")
        self.assertEqual(decide_graph_label_publish(seed_recipes()["audio_defect"], {}), "none")

    def test_persist_defect_labels_binds_audio_defect_tree(self) -> None:
        from hmi.clip_facts import get_clip_label_row, get_clip_label_view
        from hmi.local.nvh_deriver import apply_nvh_labels_to_facts
        from hmi.platform.graph_label_publish import persist_recipe_clip_labels
        from hmi.platform.recipe import seed_recipes
        from hmi.taxonomy.data_type_bind import resolve_taxonomy_version_for_data_type

        clip_id = "sha256:defect_fill"
        run_id = "run-defect-fill"
        ds_day = "20260908"
        apply_nvh_labels_to_facts(
            clip_id=clip_id,
            run_id=run_id,
            ds=ds_day,
            labels={"nvh.meta.format": "wav", "nvh.clip.spl.leq_db_mean": 90.0},
            update_platform_run=False,
        )
        labels = {"values": {"audio.defect.has_problem": {"value": True}}}
        persist_recipe_clip_labels(
            clip_id=clip_id,
            run_id=run_id,
            ds=ds_day,
            recipe=seed_recipes()["audio_defect"],
            labels=labels,
        )
        bound = resolve_taxonomy_version_for_data_type("audio_defect")
        assert bound is not None
        row = get_clip_label_row(clip_id, run_id, ds=ds_day)
        assert row is not None
        self.assertEqual(row["taxonomy_version_id"], bound["id"])
        payload = json.loads(row["labels_json"]) if isinstance(row["labels_json"], str) else row["labels_json"]
        self.assertEqual(payload["values"]["audio.defect.has_problem"]["value"], True)
        self.assertNotIn("nvh.meta.format", json.dumps(payload))
        view = get_clip_label_view(clip_id, run_id, ds=ds_day)
        self.assertTrue(str(view.get("taxonomy_version_code") or "").startswith("audio_defect-v1"))


if __name__ == "__main__":
    unittest.main()
