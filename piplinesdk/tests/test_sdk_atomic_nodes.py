"""Smoke tests: atomic SDK DataWorks nodes import and expose main()."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_DATAWORKS = Path(__file__).resolve().parents[2] / "pipeline" / "dataworks"
sys.path.insert(0, str(_DATAWORKS))

import sdk_asr_node  # noqa: E402
import sdk_embed_node  # noqa: E402
import sdk_extract_node  # noqa: E402
import sdk_label_node  # noqa: E402
import sdk_node_common  # noqa: E402
import sdk_preview_node  # noqa: E402


class TestSdkAtomicNodes(unittest.TestCase):
    def test_nodes_have_main(self) -> None:
        for mod in (
            sdk_extract_node,
            sdk_asr_node,
            sdk_preview_node,
            sdk_label_node,
            sdk_embed_node,
        ):
            self.assertTrue(callable(getattr(mod, "main", None)), mod.__name__)

    def test_common_helpers(self) -> None:
        self.assertEqual(sdk_node_common.resolve_media_mode.__defaults__, ("local",))
        self.assertIn("local", {"local", "oss", "auto"})


if __name__ == "__main__":
    unittest.main()
