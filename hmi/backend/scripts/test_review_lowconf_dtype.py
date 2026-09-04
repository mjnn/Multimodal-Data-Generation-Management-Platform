"""Low-confidence claim queue filters to a DataType's bound taxonomy."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestLowConfidenceDataTypeFilter(unittest.TestCase):
    def setUp(self) -> None:
        import hmi.app_db as app_db

        self._orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._orig))
        app_db.ensure_schema()

    def test_ivi_node_map_excludes_oms_and_nvh(self) -> None:
        from hmi.review.v2_tasks import _taxonomy_node_map

        ivi = _taxonomy_node_map("ivi_ui_stub")
        self.assertIn("ivi.control", ivi)
        self.assertNotIn("nvh.meta.format", ivi)

        nvh = _taxonomy_node_map("audio_array_spec")
        self.assertIn("nvh.meta.format", nvh)
        self.assertNotIn("ivi.control", nvh)

    def test_claim_requires_data_type(self) -> None:
        from hmi.review.assignment_service import claim_low_confidence_batch

        with self.assertRaises(ValueError) as ctx:
            claim_low_confidence_batch(
                assignee_id="u1",
                limit=10,
                created_by="u1",
                data_type_id=None,
            )
        self.assertIn("数据类型", str(ctx.exception))

    def test_build_pending_skips_other_type_labels(self) -> None:
        from hmi.review.v2_tasks import build_pending_tasks

        candidates = [{"clip_id": "c1", "run_id": "r1"}]

        def fake_view(clip_id: str, run_id: str, ds: str | None = None):
            return {
                "clip_id": clip_id,
                "run_id": run_id,
                "clip_label_ready": True,
                "labels_json": {
                    "ivi.control": None,
                    "nvh.meta.format": None,
                    "L1.1.day_period": "morning",
                },
            }

        with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
            with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
                with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                    with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260903"):
                        with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                            with patch("hmi.review.v2_tasks.get_review", return_value=None):
                                with patch("hmi.review.v2_tasks.load_ai_label_hints_local", return_value={}):
                                    with patch(
                                        "hmi.review.v2_tasks._clip_dir_name",
                                        return_value="c1",
                                    ):
                                        ivi_tasks = build_pending_tasks(
                                            "confidence",
                                            include_clip_card=False,
                                            data_type_id="ivi_ui_stub",
                                        )
                                        nvh_tasks = build_pending_tasks(
                                            "confidence",
                                            include_clip_card=False,
                                            data_type_id="audio_array_spec",
                                        )
        self.assertEqual({t["label_id"] for t in ivi_tasks}, {"ivi.control"})
        self.assertIn("nvh.meta.format", {t["label_id"] for t in nvh_tasks})
        self.assertNotIn("ivi.control", {t["label_id"] for t in nvh_tasks})


if __name__ == "__main__":
    unittest.main()
