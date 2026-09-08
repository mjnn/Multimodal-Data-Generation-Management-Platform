"""Unit checks for HMI test mode + reset gate (no cloud I/O)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "hmi" / "backend"
for p in (str(BACKEND), str(REPO / "shared")):
    if p not in sys.path:
        sys.path.insert(0, p)


class TestModeFlag(unittest.TestCase):
    def test_is_test_mode_truthy(self) -> None:
        from hmi.test_mode import is_test_mode

        for val in ("1", "true", "YES", "on"):
            with mock.patch.dict(os.environ, {"HMI_TEST_MODE": val}, clear=False):
                self.assertTrue(is_test_mode(), val)

    def test_is_test_mode_falsy(self) -> None:
        from hmi.test_mode import is_test_mode

        for val in ("", "0", "false", "no"):
            with mock.patch.dict(os.environ, {"HMI_TEST_MODE": val}, clear=False):
                self.assertFalse(is_test_mode(), repr(val))

    def test_reset_requires_test_mode(self) -> None:
        from hmi.hmi_baseline_reset import reset_hmi_artifacts_to_baseline

        with mock.patch.dict(os.environ, {"HMI_TEST_MODE": "0"}, clear=False):
            with self.assertRaises(PermissionError):
                reset_hmi_artifacts_to_baseline()


class ResetLakeAndSeedDataTypes(unittest.TestCase):
    def test_cloud_oss_prefixes_include_lake(self) -> None:
        from hmi.hmi_baseline_reset import _CLOUD_OSS_PREFIXES, _LAKE_OSS_PREFIXES

        for prefix in ("sources/", "lake_images/", "platform_runs/"):
            self.assertIn(prefix, _CLOUD_OSS_PREFIXES)
        self.assertEqual(_LAKE_OSS_PREFIXES, ("sources", "lake_images", "platform_runs"))

    def test_clear_oss_subtree_wipes_lake_prefixes(self) -> None:
        from hmi import hmi_baseline_reset as reset

        tmp = Path(tempfile.mkdtemp())
        oss = tmp / "oss"
        (oss / "sources" / "coll__abc").mkdir(parents=True)
        (oss / "sources" / "coll__abc" / "audio.wav").write_bytes(b"x")
        (oss / "lake_images" / "img").mkdir(parents=True)
        (oss / "lake_images" / "img" / "a.jpg").write_bytes(b"y")
        (oss / "platform_runs" / "run1").mkdir(parents=True)
        (oss / "platform_runs" / "run1" / "source_manifest.json").write_text("{}", encoding="utf-8")

        with (
            mock.patch.object(reset, "is_local_mode", return_value=True),
            mock.patch.object(reset, "LOCAL_OSS_ROOT", oss),
        ):
            self.assertGreater(reset._clear_oss_subtree("sources"), 0)
            self.assertGreater(reset._clear_oss_subtree("lake_images"), 0)
            self.assertGreater(reset._clear_oss_subtree("platform_runs"), 0)

        self.assertFalse((oss / "sources" / "coll__abc").exists())
        self.assertFalse((oss / "lake_images" / "img").exists())
        self.assertFalse((oss / "platform_runs" / "run1").exists())

    def test_purge_local_pipeline_clears_lake_oss(self) -> None:
        from hmi import hmi_baseline_reset as reset

        tmp = Path(tempfile.mkdtemp())
        oss = tmp / "oss"
        lake = oss / "sources" / "pack"
        lake.mkdir(parents=True)
        (lake / "audio.wav").write_bytes(b"wav")
        artifacts = tmp / "artifacts"
        artifacts.mkdir()
        (tmp / "work" / "sdk_runs").mkdir(parents=True)

        with (
            mock.patch.object(reset, "is_local_mode", return_value=True),
            mock.patch.object(reset, "LOCAL_OSS_ROOT", oss),
            mock.patch.object(reset, "LOCAL_ROOT", tmp),
            mock.patch.object(reset, "LOCAL_ARTIFACTS_ROOT", artifacts),
            mock.patch.object(reset, "LOCAL_DB_PATH", tmp / "missing.db"),
            mock.patch("hmi.db.cache_clear"),
            mock.patch("hmi.local.store.ensure_db"),
            mock.patch("hmi.services.upload.clear_upload_tasks", return_value=0),
        ):
            out = reset._purge_local_pipeline_runtime()

        self.assertFalse(out.get("skipped"))
        self.assertGreater(out["oss_entries_removed"]["sources"], 0)
        self.assertFalse(lake.exists())

    def test_reset_platform_kernel_drops_extra_types_and_sources(self) -> None:
        import hmi.app_db as app_db
        from hmi.app_db import ensure_schema
        from hmi.platform.recipe import SEED_DATA_TYPE_IDS, SEED_RECIPES, validate_recipe
        from hmi.platform.store import list_data_types, reset_platform_kernel_to_seeds, upsert_data_type

        orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", orig))
        ensure_schema()

        extra = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        extra["id"] = "user_created_cabin"
        extra["title"] = "用户新建"
        upsert_data_type(extra)

        edited = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        edited["title"] = "被改过的舱内"
        upsert_data_type(edited)

        with app_db.db_conn() as conn:
            conn.execute(
                """
                INSERT INTO platform_source (source_id, kind, filename, created_at)
                VALUES (?, ?, ?, ?)
                """,
                ("sha256:deadbeef", ".wav", "noise.wav", "2026-01-01T00:00:00+00:00"),
            )
            out = reset_platform_kernel_to_seeds(conn)

        ids = {item["id"] for item in list_data_types()}
        self.assertEqual(ids, set(SEED_DATA_TYPE_IDS))
        self.assertEqual(out["extra_data_types_removed"], ["user_created_cabin"])
        cabin = next(item for item in list_data_types() if item["id"] == "oms_cabin")
        self.assertEqual(cabin["title"], SEED_RECIPES["oms_cabin"]["title"])
        defect = next(item for item in list_data_types() if item["id"] == "audio_defect")
        self.assertEqual(defect["title"], SEED_RECIPES["audio_defect"]["title"])
        self.assertEqual(defect["taxonomy_version_code"], "audio_defect-v1")
        with app_db.db_conn() as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM platform_source").fetchone()
            self.assertEqual(int(n[0]), 0)
            tax = conn.execute(
                "SELECT status FROM label_taxonomy_version WHERE version_code = ?",
                ("audio_defect-v1",),
            ).fetchone()
            self.assertIsNotNone(tax)
            self.assertEqual(str(tax[0]), "draft")
            node = conn.execute(
                """
                SELECT label_id, dtype FROM label_taxonomy_node
                WHERE taxonomy_version_id = (
                  SELECT id FROM label_taxonomy_version WHERE version_code = ?
                )
                """,
                ("audio_defect-v1",),
            ).fetchone()
            self.assertEqual(str(node[0]), "audio.defect.has_problem")
            self.assertEqual(str(node[1]), "bool")

    def test_reset_platform_kernel_clears_products(self) -> None:
        import hmi.app_db as app_db
        from hmi.app_db import ensure_schema
        from hmi.platform.store import (
            list_products,
            record_product,
            reset_platform_kernel_to_seeds,
        )

        orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", orig))
        ensure_schema()

        record_product(
            input_ids=["sha256:deadbeef"],
            op_id="spl_timeline",
            artifact_path="/app/data/hmi_runtime/work/sdk_runs/run1/audio_spec",
            run_id="91fe2831-26b4-4aaa-bbbb-cccccccccccc",
        )
        self.assertEqual(len(list_products(limit=50)), 1)

        with app_db.db_conn() as conn:
            out = reset_platform_kernel_to_seeds(conn)

        self.assertEqual(out["sqlite_rows_removed"]["platform_product"], 1)
        self.assertEqual(list_products(limit=50), [])

    def test_pause_product_writes_blocks_insert(self) -> None:
        import hmi.app_db as app_db
        from hmi.app_db import ensure_schema
        from hmi.platform.store import (
            list_products,
            pause_product_writes,
            record_product,
            resume_product_writes,
        )

        orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", orig))
        ensure_schema()

        pause_product_writes()
        try:
            record_product(input_ids=["sha256:paused"], op_id="mel_spectrogram")
            self.assertEqual(list_products(limit=50), [])
        finally:
            resume_product_writes()

        record_product(input_ids=["sha256:paused"], op_id="mel_spectrogram")
        self.assertEqual(len(list_products(limit=50)), 1)

    def test_purge_host_runtime_clears_sdk_runs_when_not_local(self) -> None:
        from hmi import hmi_baseline_reset as reset

        tmp = Path(tempfile.mkdtemp())
        artifacts = tmp / "artifacts"
        leftover = artifacts / "clip1"
        leftover.mkdir(parents=True)
        (leftover / "run.json").write_text("{}", encoding="utf-8")
        sdk = tmp / "work" / "sdk_runs" / "349320c9-adc9-4eaf-ab06-349320c9-adc"
        (sdk / "audio_spec").mkdir(parents=True)
        (sdk / "audio_spec" / "spl.npy").write_bytes(b"x")

        with (
            mock.patch.object(reset, "LOCAL_ROOT", tmp),
            mock.patch.object(reset, "LOCAL_ARTIFACTS_ROOT", artifacts),
        ):
            out = reset._purge_host_runtime_leftovers()

        self.assertGreater(out["sdk_work_entries_removed"], 0)
        self.assertGreater(out["artifacts_entries_removed"], 0)
        self.assertFalse(sdk.exists())
        self.assertFalse(leftover.exists())

    def test_reset_restores_authored_catalog_graphs(self) -> None:
        import hmi.app_db as app_db
        from hmi.app_db import ensure_schema
        from hmi.platform.recipe import SEED_DATA_TYPE_IDS
        from hmi.platform.store import get_data_type, reset_platform_kernel_to_seeds, upsert_data_type

        orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", orig))
        ensure_schema()

        broken = get_data_type("audio_array_spec")
        assert broken is not None
        broken["graph"] = {
            "nodes": [
                {
                    "key": "audio_primary",
                    "type": "source",
                    "op_id": "source",
                    "title": "阵列音频",
                    "params": {"kinds": [".wav"], "required": True, "cardinality_min": 1, "cardinality_max": 1},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "key": "prep-3-transcribe",
                    "type": "op",
                    "op_id": "transcribe",
                    "title": "prep-3-transcribe",
                    "params": {},
                    "position": {"x": 0, "y": 80},
                },
                {
                    "key": "prep-4-mel_spectrogram",
                    "type": "op",
                    "op_id": "mel_spectrogram",
                    "title": "prep-4-mel_spectrogram",
                    "params": {},
                    "position": {"x": 0, "y": 160},
                },
                {
                    "key": "stage-label",
                    "type": "label",
                    "op_id": "label",
                    "title": "打标器",
                    "params": {},
                    "position": {"x": 0, "y": 240},
                },
            ],
            "edges": [
                {
                    "id": "a",
                    "source": "audio_primary",
                    "source_port": "out",
                    "target": "prep-3-transcribe",
                    "target_port": "in",
                },
                {
                    "id": "b",
                    "source": "prep-3-transcribe",
                    "source_port": "out",
                    "target": "prep-4-mel_spectrogram",
                    "target_port": "in",
                },
                {
                    "id": "c",
                    "source": "prep-4-mel_spectrogram",
                    "source_port": "out",
                    "target": "stage-label",
                    "target_port": "in",
                },
            ],
        }
        upsert_data_type(broken)

        with app_db.db_conn() as conn:
            reset_platform_kernel_to_seeds(conn)

        for dtype_id in SEED_DATA_TYPE_IDS:
            rec = get_data_type(dtype_id)
            assert rec is not None
            keys = [n["key"] for n in (rec.get("graph") or {}).get("nodes") or []]
            self.assertTrue(keys, dtype_id)
            self.assertFalse(any(k.startswith("prep-") for k in keys), (dtype_id, keys))

        audio = get_data_type("audio_array_spec")
        assert audio is not None
        ops = {
            n["op_id"]
            for n in audio["graph"]["nodes"]
            if n["type"] in {"op", "label"}
        }
        self.assertIn("mel_spectrogram", ops)
        self.assertNotIn("transcribe", ops)
        mel = next(n for n in audio["graph"]["nodes"] if n["op_id"] == "mel_spectrogram")
        self.assertEqual(mel["key"], "mel_spectrogram")
        self.assertEqual(mel["title"], "梅尔频谱")


if __name__ == "__main__":
    unittest.main()
