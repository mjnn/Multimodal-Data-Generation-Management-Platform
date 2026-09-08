"""Labels-only SDK runs must import when embed was not in the recipe."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))

_SCRIPT = REPO / "hmi" / "scripts" / "import_real_data_clips.py"


def _load_import_mod():
    spec = importlib.util.spec_from_file_location("import_real_data_clips", _SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestImportWithoutEmbed(unittest.TestCase):
    def test_labels_only_dir_is_importable(self) -> None:
        mod = _load_import_mod()
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            only_labels = root / "run_a"
            only_labels.mkdir()
            (only_labels / "labels.jsonl").write_text(
                '{"clip_id":"c1","labels":{}}\n', encoding="utf-8"
            )
            empty = root / "run_empty"
            empty.mkdir()
            both = root / "run_both"
            both.mkdir()
            (both / "labels.jsonl").write_text("{}\n", encoding="utf-8")
            (both / "fusion_embeddings.jsonl").write_text("{}\n", encoding="utf-8")

            self.assertTrue(mod._is_importable_run_dir(only_labels))
            self.assertFalse(mod._is_importable_run_dir(empty))
            self.assertTrue(mod._is_importable_run_dir(both))
            found = {p.name for p in mod.list_runs(data_root=root)}
            self.assertEqual(found, {"run_a", "run_both"})

    def test_copy_bundle_skips_missing_embeddings(self) -> None:
        mod = _load_import_mod()
        with tempfile.TemporaryDirectory() as raw:
            src = Path(raw) / "src"
            dest = Path(raw) / "dest"
            src.mkdir()
            dest.mkdir()
            (src / "labels.jsonl").write_text("{}\n", encoding="utf-8")
            (src / "asr.jsonl").write_text("{}\n", encoding="utf-8")
            mod._copy_sdk_jsonl_bundle(src, dest)
            self.assertTrue((dest / "labels.jsonl").is_file())
            self.assertTrue((dest / "asr.jsonl").is_file())
            self.assertFalse((dest / "fusion_embeddings.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
