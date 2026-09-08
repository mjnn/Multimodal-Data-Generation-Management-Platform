"""UI-NVH-REVIEW-SAVE: human L6 writeback must not clobber objective NVH leaves."""

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


def _base_labels() -> dict:
    return {
        "nvh.clip.spl.leq_db_mean": 94.5,
        "nvh.clip.spl.level_class": "high",
        "nvh.sem.noise_category": "tonal",
        "nvh.sem.quality_grade": "C",
        "_meta": {
            "taxonomy_version_code": "audio_nvh-v2",
            "deriver_version": "nvh_deriver-v1",
            "label_source": "derive_nvh_labels+nvh_ai_label",
        },
    }


class TestNvhL6Writeback(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        os.environ.setdefault("HMI_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
        self.tmp = Path(tempfile.mkdtemp())
        import hmi.app_db as app_db
        import hmi.data_source as ds
        import hmi.local.store as local_store

        self._app = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = self.tmp / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._app))
        app_db.ensure_schema()
        from hmi.platform.store import ensure_platform_schema

        ensure_platform_schema()

        self._root = ds.LOCAL_ROOT
        ds.LOCAL_ROOT = self.tmp / "runtime"
        ds.LOCAL_ARTIFACTS_ROOT = ds.LOCAL_ROOT / "artifacts"
        local_store.LOCAL_ROOT = ds.LOCAL_ROOT
        local_store.LOCAL_DB_PATH = ds.LOCAL_ROOT / "hmi.db"
        self.addCleanup(lambda: setattr(ds, "LOCAL_ROOT", self._root))
        self.addCleanup(lambda: setattr(ds, "LOCAL_ARTIFACTS_ROOT", self._root / "artifacts"))
        local_store.ensure_db()

        self.clip_id = "sha256:nvh_review_save"
        self.run_id = "run-nvh-review"
        self.ds_day = "20260904"
        from hmi.local import pipeline_run as pr

        pr.upsert_clip_row(
            clip_id=self.clip_id,
            clip_dir_name="nvh_review",
            content_hash="abc",
            bag_oss_key="local://sources/x/source_manifest.json",
            active_run_id=self.run_id,
        )
        pr.upsert_run(run_id=self.run_id, clip_id=self.clip_id, ds=self.ds_day, status="completed")
        from hmi.data_source import artifacts_dir
        from hmi.local.nvh_deriver import apply_nvh_labels_to_facts, persist_nvh_labels_artifact

        root = artifacts_dir(self.clip_id, self.run_id)
        persist_nvh_labels_artifact(root, _base_labels())
        apply_nvh_labels_to_facts(
            clip_id=self.clip_id,
            run_id=self.run_id,
            ds=self.ds_day,
            labels=_base_labels(),
            update_platform_run=False,
        )

    def test_writeback_merges_l6_keeps_objective(self) -> None:
        from hmi.clip_facts import get_clip_label_row
        from hmi.labels_util import parse_labels_json
        from hmi.review.nvh_writeback import writeback_nvh_l6
        from hmi.taxonomy_db import get_published_version, get_version_by_code

        before_pub = get_published_version()
        out = writeback_nvh_l6(
            clip_id=self.clip_id,
            run_id=self.run_id,
            labels_json={
                "nvh.sem.quality_grade": "A",
                "nvh.sem.annotator_notes": "人工确认",
                "nvh.clip.spl.leq_db_mean": 1.0,
            },
        )
        self.assertIsNotNone(out)
        row = get_clip_label_row(self.clip_id, self.run_id, ds=self.ds_day)
        assert row is not None
        labels = parse_labels_json(row.get("labels_json"))
        self.assertEqual(labels["nvh.sem.quality_grade"], "A")
        self.assertEqual(labels["nvh.sem.annotator_notes"], "人工确认")
        self.assertEqual(labels["nvh.clip.spl.leq_db_mean"], 94.5)
        self.assertIn("human", str(row.get("label_source") or ""))
        from hmi.data_source import artifacts_dir

        art = json.loads((artifacts_dir(self.clip_id, self.run_id) / "nvh_labels.json").read_text(encoding="utf-8"))
        self.assertEqual(art["nvh.sem.quality_grade"], "A")
        self.assertEqual(art["nvh.clip.spl.leq_db_mean"], 94.5)
        after_pub = get_published_version()
        if before_pub:
            self.assertEqual(before_pub["id"], after_pub["id"] if after_pub else None)
        nvh = get_version_by_code("audio_nvh-v2")
        self.assertIsNotNone(nvh)
        assert nvh is not None
        self.assertEqual(nvh["status"], "draft")

    def test_oms_labels_are_noop(self) -> None:
        from hmi.review.nvh_writeback import writeback_nvh_l6

        self.assertIsNone(
            writeback_nvh_l6(
                clip_id=self.clip_id,
                run_id=self.run_id,
                labels_json={"values": {"L1.1.day_period": {"value": "morning"}}},
            )
        )

    def test_nvh_rollup_only_requires_semantic_keys(self) -> None:
        from hmi.review.merge import all_ai_labels_field_reviewed, get_ai_label_ids
        from hmi.review.nvh_writeback import rollup_label_ids

        ids = get_ai_label_ids(self.clip_id, self.run_id)
        self.assertIn("nvh.clip.spl.leq_db_mean", ids)
        scoped = rollup_label_ids(self.clip_id, self.run_id)
        self.assertIn("nvh.sem.quality_grade", scoped)
        self.assertNotIn("nvh.clip.spl.leq_db_mean", scoped)
        self.assertFalse(all_ai_labels_field_reviewed(self.clip_id, self.run_id))


if __name__ == "__main__":
    unittest.main()
