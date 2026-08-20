"""TAX-AUDIO-NVH-v2: 78-leaf audio NVH taxonomy YAML + seed."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestAudioNvhV2Spec(unittest.TestCase):
    def test_label_count_and_ids(self) -> None:
        from hmi.platform.audio_nvh_v2 import LABEL_COUNT, VERSION_CODE, build_labels

        labels = build_labels()
        self.assertEqual(len(labels), LABEL_COUNT)
        ids = [item["id"] for item in labels]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(VERSION_CODE, "audio_nvh-v2")
        self.assertTrue(all(i.startswith("nvh.") for i in ids))
        by_level = {}
        for item in labels:
            by_level.setdefault(item["level_code"], 0)
            by_level[item["level_code"]] += 1
        self.assertEqual(by_level["L0"], 8)
        self.assertEqual(by_level["L1.1"], 10)
        self.assertEqual(by_level["L1.2"], 6)
        self.assertEqual(by_level["L1.3"], 8)
        self.assertEqual(by_level["L2"], 12)
        self.assertEqual(by_level["L3"], 8)
        self.assertEqual(by_level["L4"], 6)
        self.assertEqual(by_level["L5"], 10)
        self.assertEqual(by_level["L6"], 10)
        deriv = {}
        for item in labels:
            d = item["value_schema"]["derivation"]
            deriv[d] = deriv.get(d, 0) + 1
        self.assertEqual(deriv["auto"] + deriv["semi"] + deriv["human"], LABEL_COUNT)
        self.assertGreaterEqual(deriv["auto"], 50)
        cat = next(x for x in labels if x["id"] == "nvh.sem.noise_category")
        tops = [v["id"] if isinstance(v, dict) else v for v in cat["value_schema"]["values"]]
        self.assertIn("powertrain", tops)
        self.assertIn("unknown", tops)
        self.assertEqual(len(tops), 13)

    def test_yaml_roundtrip_count(self) -> None:
        from hmi.taxonomy_import import parse_taxonomy_yaml, yaml_labels_to_nodes
        from hmi.platform.audio_nvh_v2 import LABEL_COUNT, yaml_document
        from repo_paths import AUDIO_NVH_TAXONOMY_PATH

        doc = yaml_document()
        self.assertEqual(doc["label_count"], LABEL_COUNT)
        self.assertTrue(AUDIO_NVH_TAXONOMY_PATH.is_file(), AUDIO_NVH_TAXONOMY_PATH)
        parsed = parse_taxonomy_yaml(AUDIO_NVH_TAXONOMY_PATH)
        self.assertEqual(parsed.version_code, "audio_nvh-v2")
        self.assertEqual(len(parsed.labels), LABEL_COUNT)
        nodes = yaml_labels_to_nodes(parsed.labels)
        self.assertEqual(len(nodes), LABEL_COUNT)


class TestAudioNvhV2Seed(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["HMI_DATA_SOURCE"] = "local"
        self.tmp = Path(tempfile.mkdtemp())
        import hmi.app_db as app_db

        self._app_db = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = self.tmp / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._app_db))
        app_db.ensure_schema()

    def test_seed_inserts_v2_draft(self) -> None:
        from hmi.platform.audio_nvh_v2 import LABEL_COUNT
        from hmi.taxonomy_db import count_nodes, get_version_by_code

        v1 = get_version_by_code("audio_nvh-v1")
        v2 = get_version_by_code("audio_nvh-v2")
        self.assertIsNotNone(v1)
        self.assertIsNotNone(v2)
        assert v2 is not None
        self.assertEqual(v2["status"], "draft")
        self.assertEqual(count_nodes(v2["id"]), LABEL_COUNT)
        published = None
        from hmi.taxonomy_db import get_published_version

        published = get_published_version()
        if published is not None:
            self.assertNotEqual(published["version_code"], "audio_nvh-v2")


if __name__ == "__main__":
    unittest.main()
