"""User-deleted taxonomy version_code can be reused; superseded codes cannot."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestReuseArchivedTaxonomyCode(unittest.TestCase):
    def setUp(self) -> None:
        import hmi.app_db as app_db

        self._orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._orig))
        app_db.ensure_schema()

    def test_user_deleted_v1_can_be_recreated(self) -> None:
        from hmi.taxonomy_db import (
            archive_version,
            create_version,
            get_version,
            get_version_by_code,
        )

        first = create_version("v1")
        archive_version(first["id"])
        self.assertIsNone(get_version_by_code("v1"))

        second = create_version("v1")
        self.assertEqual(second["version_code"], "v1")
        self.assertEqual(second["status"], "draft")
        self.assertNotEqual(second["id"], first["id"])
        self.assertEqual(get_version_by_code("v1")["id"], second["id"])

        archived = get_version(first["id"])
        assert archived is not None
        self.assertEqual(archived["status"], "archived")
        self.assertTrue(str(archived["version_code"]).startswith("v1__archived_"))

    def test_live_duplicate_still_rejected(self) -> None:
        from hmi.taxonomy_db import create_version

        create_version("v1")
        with self.assertRaises(ValueError) as ctx:
            create_version("v1")
        self.assertIn("already exists", str(ctx.exception))

    def test_superseded_code_still_blocked(self) -> None:
        from hmi.taxonomy_db import create_version, get_version_by_code, publish_version

        old = create_version("cabin-v1")
        publish_version(old["id"])
        nxt = create_version("cabin-v2")
        publish_version(nxt["id"])

        superseded = get_version_by_code("cabin-v1")
        assert superseded is not None
        self.assertEqual(superseded["status"], "archived")
        with self.assertRaises(ValueError) as ctx:
            create_version("cabin-v1")
        self.assertIn("already exists", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
