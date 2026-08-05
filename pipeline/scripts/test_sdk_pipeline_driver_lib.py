from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline" / "dataworks"))
sys.path.insert(0, str(REPO / "piplinesdk"))

from sdk_pipeline_driver_lib import (  # noqa: E402
    batch_summary,
    build_job_rows,
    chunk_output_dtypes,
    content_hash_to_clip_id,
    make_run_id,
    run_oss_prefix_from_relpath,
    split_stages,
)


class TestDriverLib(unittest.TestCase):
    def test_split_stages(self) -> None:
        d, u = split_stages("discover,extract,asr,mc_write")
        self.assertEqual(d, frozenset({"discover", "mc_write"}))
        self.assertEqual(u, frozenset({"extract", "asr"}))

    def test_build_job_rows(self) -> None:
        rows = build_job_rows(
            [{"clip_id": "sha256:a", "run_id": "r1", "bag_oss_key": "rosbags/a.bag"}],
            ds="20260804",
        )
        self.assertEqual(rows[0]["run_relpath"], "clips/sha256:a/runs/r1")
        self.assertEqual(rows[0]["ds"], "20260804")

    def test_run_oss_prefix_from_relpath(self) -> None:
        self.assertEqual(
            run_oss_prefix_from_relpath("clips/sha256:a/runs/r1"),
            "clips/sha256:a/runs/r1/",
        )
        self.assertEqual(
            run_oss_prefix_from_relpath("clips/sha256:a/runs/r1/"),
            "clips/sha256:a/runs/r1/",
        )

    def test_dtypes_keys(self) -> None:
        d = chunk_output_dtypes()
        for k in ("clip_id", "ds", "ok", "error", "stages_done", "labels_relpath"):
            self.assertIn(k, d)

    def test_summary(self) -> None:
        s = batch_summary(
            [
                {"ok": True, "clip_id": "a"},
                {"ok": False, "clip_id": "b", "error": "x"},
            ]
        )
        self.assertEqual(s["ok_count"], 1)
        self.assertEqual(s["fail_count"], 1)

    def test_content_hash_to_clip_id_normalizes_digest(self) -> None:
        self.assertEqual(content_hash_to_clip_id(" SHA256:AbC "), "sha256:abc")

    def test_make_run_id_returns_uuid(self) -> None:
        import uuid

        run_id = make_run_id()
        self.assertEqual(str(uuid.UUID(run_id)), run_id)


if __name__ == "__main__":
    unittest.main()
