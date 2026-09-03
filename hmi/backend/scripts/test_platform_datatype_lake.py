"""PLAT-DTYPE-LAKE: source persistence + platform_run compilation."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class LakeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        self.tmp = Path(tempfile.mkdtemp())

        import hmi.app_db as app_db
        import hmi.local.store as local_store
        from hmi.services import local_sdk_worker
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

        self._bag_oss_root = bag_upload.LOCAL_OSS_ROOT
        self._src_oss_root = source_upload.LOCAL_OSS_ROOT
        bag_upload.LOCAL_OSS_ROOT = local_store.LOCAL_ROOT / "oss"
        source_upload.LOCAL_OSS_ROOT = local_store.LOCAL_ROOT / "oss"
        self.addCleanup(lambda: setattr(bag_upload, "LOCAL_OSS_ROOT", self._bag_oss_root))
        self.addCleanup(lambda: setattr(source_upload, "LOCAL_OSS_ROOT", self._src_oss_root))

        self._worker_root = local_sdk_worker.LOCAL_ROOT
        local_sdk_worker.LOCAL_ROOT = local_store.LOCAL_ROOT
        self.addCleanup(lambda: setattr(local_sdk_worker, "LOCAL_ROOT", self._worker_root))

        local_store.ensure_db()


class TestLakePersistence(LakeTestCase):
    def test_put_source_persists_local_keys(self) -> None:
        from hmi.platform.store import put_source

        bag = put_source(content=b"bag-binary", kind="rosbag", filename="demo/output.bag")
        text = put_source(
            content=b'{"a":1}',
            kind="text",
            filename="note.json",
            text_schema_id="generic_json",
        )
        image = put_source(content=b"fakepng", kind="image", filename="frame.png")

        self.assertEqual(bag["kind"], ".bag")
        self.assertEqual(text["kind"], ".json")
        self.assertEqual(image["kind"], ".png")
        self.assertTrue(str(bag["local_oss_key"]).startswith("local://rosbags/"))
        self.assertTrue(str(text["local_oss_key"]).startswith("local://sources/"))
        self.assertTrue(str(image["local_oss_key"]).startswith("local://lake_images/"))
        self.assertTrue(Path(str(bag["local_path"])).is_file())
        self.assertTrue(Path(str(text["local_path"])).is_file())
        self.assertTrue(Path(str(image["local_path"])).is_file())

    def test_list_sources_returns_persisted_across_calls(self) -> None:
        from hmi.platform.store import create_sample, list_sources, put_source

        a = put_source(content=b"alpha", kind="text", filename="a.txt", text_schema_id="generic_text")
        b = put_source(content=b"beta", kind="video", filename="b.mp4")
        items = list_sources(limit=50)
        ids = {row["source_id"] for row in items}
        self.assertIn(a["source_id"], ids)
        self.assertIn(b["source_id"], ids)
        # Reuse historical sources into a new sample (no re-upload)
        sample = create_sample([a["source_id"], b["source_id"]])
        self.assertEqual(set(sample["source_ids"]), {a["source_id"], b["source_id"]})


class TestPlatformRunCompilation(LakeTestCase):
    def test_compile_media_sample_creates_queue_rows(self) -> None:
        from hmi.platform.store import create_run, create_sample, put_source
        from hmi.services.local_sdk_worker import _compile_platform_run
        from hmi.local import store as local_store

        video = put_source(content=b"fake-mp4", kind="video", filename="clip.mp4")
        text = put_source(
            content=b"hello",
            kind="text",
            filename="note.txt",
            text_schema_id="generic_text",
        )
        sample = create_sample([video["source_id"], text["source_id"]])
        run = create_run(sample["sample_id"], "oms_cabin")

        compiled = _compile_platform_run(run["run_id"])
        self.assertEqual(compiled["clip_count"], 1)

        exec_row = local_store.query_one(
            "SELECT run_id, data_type_id FROM pipeline_execution WHERE run_id = ?",
            (run["run_id"],),
        )
        self.assertIsNotNone(exec_row)
        assert exec_row is not None
        self.assertEqual(exec_row["data_type_id"], "oms_cabin")

        run_rows = local_store.query(
            "SELECT clip_id, status FROM pipeline_run WHERE run_id = ?",
            (run["run_id"],),
        )
        self.assertEqual(len(run_rows), 1)
        self.assertEqual(run_rows[0]["clip_id"], sample["sample_id"])

        from hmi.local import pipeline_run as pr

        needing = pr.list_runs_needing_sdk(limit=5)
        self.assertTrue(any(r["run_id"] == run["run_id"] for r in needing))
        self.assertTrue(
            any(str(r.get("bag_oss_key") or "").startswith("local://platform_runs/") for r in needing)
        )

    def test_compile_two_rosbags_creates_two_clip_rows(self) -> None:
        from hmi.platform.store import create_run, create_sample, put_source
        from hmi.services.local_sdk_worker import _compile_platform_run
        from hmi.local import store as local_store

        bag1 = put_source(content=b"bag-1", kind="rosbag", filename="a/output.bag")
        bag2 = put_source(content=b"bag-2", kind="rosbag", filename="b/output.bag")
        sample = create_sample([bag1["source_id"], bag2["source_id"]])
        run = create_run(sample["sample_id"], "oms_cabin")

        compiled = _compile_platform_run(run["run_id"])
        self.assertEqual(compiled["clip_count"], 2)
        rows = local_store.query("SELECT clip_id FROM pipeline_run WHERE run_id = ?", (run["run_id"],))
        self.assertEqual({row["clip_id"] for row in rows}, {bag1["source_id"], bag2["source_id"]})

    def test_image_sample_fails_compile(self) -> None:
        from hmi.platform.store import create_run, create_sample, get_run, put_source
        from hmi.services.local_sdk_worker import _claim_platform_runs

        image = put_source(content=b"img", kind="image", filename="frame.png")
        sample = create_sample([image["source_id"]])
        run = create_run(sample["sample_id"], "ivi_ui_stub")

        _claim_platform_runs(limit=5)
        row = get_run(run["run_id"])
        assert row is not None
        self.assertEqual(row["status"], "failed")

    def test_sync_platform_run_status_writes_y(self) -> None:
        from hmi.platform.store import create_run, create_sample, get_run, put_source
        from hmi.services.local_sdk_worker import _compile_platform_run, _sync_platform_run_status
        from hmi.local import store as local_store

        video = put_source(content=b"fake-mp4", kind="video", filename="clip.mp4")
        sample = create_sample([video["source_id"]])
        run = create_run(sample["sample_id"], "oms_cabin")
        _compile_platform_run(run["run_id"])

        local_store.execute(
            """
            UPDATE pipeline_run SET status='completed' WHERE run_id=?
            """,
            (run["run_id"],),
        )
        local_store.execute(
            """
            INSERT INTO fact_clip_label (clip_id, run_id, ds, labels_json, created_at, updated_at)
            VALUES (?, ?, '20260818', ?, datetime('now'), datetime('now'))
            """,
            (sample["sample_id"], run["run_id"], '{"scene":"demo"}'),
        )

        _sync_platform_run_status(run["run_id"])
        row = get_run(run["run_id"])
        assert row is not None
        self.assertEqual(row["status"], "labeled")
        self.assertEqual(row["y"], {"scene": "demo"})


if __name__ == "__main__":
    unittest.main()
