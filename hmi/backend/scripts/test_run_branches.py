"""PLAT-RUN-BRANCHES: every pipeline run is a live branch of the same clip."""

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


class TestRunBranches(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        self.tmp = Path(tempfile.mkdtemp())
        import hmi.data_source as ds
        import hmi.local.store as local_store

        self._root = local_store.LOCAL_ROOT
        self._db = local_store.LOCAL_DB_PATH
        local_store.LOCAL_ROOT = self.tmp / "runtime"
        local_store.LOCAL_DB_PATH = local_store.LOCAL_ROOT / "hmi.db"
        ds.LOCAL_ROOT = local_store.LOCAL_ROOT
        ds.LOCAL_ARTIFACTS_ROOT = local_store.LOCAL_ROOT / "artifacts"
        self.addCleanup(lambda: setattr(local_store, "LOCAL_ROOT", self._root))
        self.addCleanup(lambda: setattr(local_store, "LOCAL_DB_PATH", self._db))
        local_store.ensure_db()

        from hmi.local import pipeline_execution as pe
        from hmi.local import pipeline_run as pr

        self.clip_id = "sha256:branch_clip_1"
        self.run_a = "run-branch-a"
        self.run_b = "run-branch-b"
        pr.upsert_clip_row(
            clip_id=self.clip_id,
            clip_dir_name="branch_bag",
            content_hash="branch",
            bag_oss_key="rosbags/branch.bag",
            active_run_id=self.run_b,
        )
        for rid, started in (
            (self.run_a, "2026-09-07T01:00:00Z"),
            (self.run_b, "2026-09-07T02:00:00Z"),
        ):
            pe.create_execution_record(
                run_id=rid,
                label="oms-branch",
                started_at=started,
                data_type_id="oms_cabin",
            )
            pr.upsert_run(run_id=rid, clip_id=self.clip_id, ds="20260907", status="completed")
            local_store.execute(
                """
                INSERT OR REPLACE INTO fact_clip_label (
                  clip_id, run_id, ds, labels_json, anchor_timestamp_ns
                ) VALUES (?, ?, '20260907', ?, 1)
                """,
                (self.clip_id, rid, json.dumps({"L1.1.day_period": "night" if rid == self.run_a else "day"})),
            )

    def test_same_type_two_runs_are_two_overview_rows(self) -> None:
        from hmi.services.clips_local import list_clips_light, list_clips_light_for_data_type

        rows = list_clips_light_for_data_type("oms_cabin", refresh=True)
        keys = {(r["clip_id"], r.get("run_id") or r["active_run_id"]) for r in rows}
        self.assertIn((self.clip_id, self.run_a), keys)
        self.assertIn((self.clip_id, self.run_b), keys)
        self.assertEqual(len([r for r in rows if r["clip_id"] == self.clip_id]), 2)

        oms = list_clips_light(refresh=True)
        oms_keys = {(r["clip_id"], r.get("run_id") or r["active_run_id"]) for r in oms}
        self.assertEqual(oms_keys, keys)

    def test_oms_branch_survives_later_nvh_active_pointer(self) -> None:
        from hmi.local import pipeline_execution as pe
        from hmi.local import pipeline_run as pr
        from hmi.services.clips_local import list_clips_light, list_clips_light_for_data_type

        nvh_run = "run-branch-nvh"
        pr.upsert_clip_row(
            clip_id=self.clip_id,
            clip_dir_name="branch_bag",
            content_hash="branch",
            bag_oss_key="rosbags/branch.bag",
            active_run_id=nvh_run,
        )
        pe.create_execution_record(
            run_id=nvh_run,
            label="nvh",
            started_at="2026-09-07T03:00:00Z",
            data_type_id="audio_array_spec",
        )
        pr.upsert_run(run_id=nvh_run, clip_id=self.clip_id, ds="20260907", status="completed")

        oms = list_clips_light(refresh=True)
        oms_runs = {r.get("run_id") or r["active_run_id"] for r in oms if r["clip_id"] == self.clip_id}
        self.assertIn(self.run_a, oms_runs)
        self.assertIn(self.run_b, oms_runs)
        self.assertNotIn(nvh_run, oms_runs)

        nvh = list_clips_light_for_data_type("audio_array_spec", refresh=True)
        nvh_runs = {r.get("run_id") or r["active_run_id"] for r in nvh if r["clip_id"] == self.clip_id}
        self.assertEqual(nvh_runs, {nvh_run})

    def test_overview_search_returns_both_runs(self) -> None:
        from hmi.services.search_local import query_overview_clips

        res = query_overview_clips(label_filters={"L1.1.day_period": ["night", "day"]})
        pairs = {(i["clip_id"], i["run_id"]) for i in res["items"]}
        self.assertIn((self.clip_id, self.run_a), pairs)
        self.assertIn((self.clip_id, self.run_b), pairs)

    def test_dataset_pool_includes_both_labeled_runs(self) -> None:
        from hmi.dataset.assemble import _local_active_clip_pairs

        pairs = {(p["clip_id"], p["run_id"]) for p in _local_active_clip_pairs()}
        self.assertIn((self.clip_id, self.run_a), pairs)
        self.assertIn((self.clip_id, self.run_b), pairs)

    def test_review_candidates_are_not_collapsed_to_active(self) -> None:
        from hmi.review.v2_tasks import _active_label_candidate_pairs

        pairs = {(p["clip_id"], p["run_id"]) for p in _active_label_candidate_pairs()}
        self.assertIn((self.clip_id, self.run_a), pairs)
        self.assertIn((self.clip_id, self.run_b), pairs)

    def test_retry_allows_non_active_failed_run(self) -> None:
        from unittest.mock import patch

        from hmi.local import pipeline_run as pr
        from hmi.local.pipeline_retry import reset_local_pipeline_to_post_upload

        pr.upsert_run(run_id=self.run_a, clip_id=self.clip_id, ds="20260907", status="failed")
        with patch("hmi.local.pipeline_retry.resolve_local_bag_path", return_value=Path("x.bag")):
            with patch("hmi.local.pipeline_retry._purge_run_files"):
                out = reset_local_pipeline_to_post_upload(clip_id=self.clip_id, run_id=self.run_a)
        self.assertEqual(out["run_id"], self.run_a)
        self.assertEqual(out.get("pipeline_status"), "pending")


if __name__ == "__main__":
    unittest.main()
