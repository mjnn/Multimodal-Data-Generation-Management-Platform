"""DataType → bound taxonomy version (assignment dispatch tree)."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestTaxonomyDataTypeBind(unittest.TestCase):
    def setUp(self) -> None:
        import hmi.app_db as app_db

        self._orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._orig))
        app_db.ensure_schema()

    def test_unknown_type_returns_none(self) -> None:
        from hmi.taxonomy.data_type_bind import resolve_taxonomy_version_for_data_type

        self.assertIsNone(resolve_taxonomy_version_for_data_type("no_such_type"))
        self.assertIsNone(resolve_taxonomy_version_for_data_type(""))

    def test_ivi_binds_stub_draft_tree(self) -> None:
        from hmi.taxonomy.data_type_bind import (
            label_ids_for_data_type,
            resolve_taxonomy_version_for_data_type,
        )

        version = resolve_taxonomy_version_for_data_type("ivi_ui_stub")
        assert version is not None
        self.assertEqual(version["version_code"], "ivi_ui_stub-v1")
        self.assertEqual(version["status"], "draft")
        ids = label_ids_for_data_type("ivi_ui_stub")
        self.assertIn("ivi.control", ids)
        self.assertIn("ivi.screen", ids)
        self.assertNotIn("nvh.meta.format", ids)

    def test_audio_prefers_explicit_v2_not_v1(self) -> None:
        from hmi.taxonomy.data_type_bind import (
            label_ids_for_data_type,
            resolve_taxonomy_version_for_data_type,
        )

        version = resolve_taxonomy_version_for_data_type("audio_array_spec")
        assert version is not None
        self.assertEqual(version["version_code"], "audio_nvh-v2")
        self.assertEqual(version["status"], "draft")
        ids = label_ids_for_data_type("audio_array_spec")
        self.assertIn("nvh.meta.format", ids)
        self.assertNotIn("ivi.control", ids)

    def test_audio_defect_binds_draft_bool_tree(self) -> None:
        from hmi.taxonomy.data_type_bind import (
            label_ids_for_data_type,
            resolve_taxonomy_version_for_data_type,
        )

        version = resolve_taxonomy_version_for_data_type("audio_defect")
        assert version is not None
        self.assertEqual(version["version_code"], "audio_defect-v1")
        self.assertEqual(version["status"], "draft")
        ids = label_ids_for_data_type("audio_defect")
        self.assertEqual(ids, {"audio.defect.has_problem"})
        self.assertNotIn("ivi.control", ids)

    def test_oms_falls_back_to_published_when_present(self) -> None:
        from hmi.taxonomy.data_type_bind import resolve_taxonomy_version_for_data_type
        from hmi.taxonomy_db import create_version, publish_version

        created = create_version("v2-oms-test", created_by="test")
        publish_version(created["id"])
        version = resolve_taxonomy_version_for_data_type("oms_cabin")
        assert version is not None
        self.assertEqual(version["id"], created["id"])
        self.assertEqual(version["status"], "published")

    def test_oms_and_ivi_trees_differ(self) -> None:
        from hmi.taxonomy.data_type_bind import label_ids_for_data_type
        from hmi.taxonomy_db import create_version, publish_version, replace_nodes

        created = create_version("v2-oms-leaves", created_by="test")
        replace_nodes(
            created["id"],
            [
                {
                    "parent_id": None,
                    "level_code": "L1.1",
                    "level_name": "时间维度",
                    "label_id": "L1.1.day_period",
                    "name": "日时段",
                    "definition": None,
                    "dtype": "enum",
                    "value_schema": None,
                    "sort_order": 0,
                    "is_active": True,
                }
            ],
        )
        publish_version(created["id"])
        oms_ids = label_ids_for_data_type("oms_cabin")
        ivi_ids = label_ids_for_data_type("ivi_ui_stub")
        self.assertIn("L1.1.day_period", oms_ids)
        self.assertNotIn("ivi.control", oms_ids)
        self.assertIn("ivi.control", ivi_ids)
        self.assertNotIn("L1.1.day_period", ivi_ids)


if __name__ == "__main__":
    unittest.main()
