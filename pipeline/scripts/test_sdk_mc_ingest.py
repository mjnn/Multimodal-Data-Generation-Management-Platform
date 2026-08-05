from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline" / "dataworks"))

from sdk_mc_ingest import build_ingest_statements  # noqa: E402


class TestSdkMcIngest(unittest.TestCase):
    def test_builds_label_and_embedding_statements_from_run_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            (run_dir / "labels.jsonl").write_text(
                json.dumps(
                    {
                        "start_timestamp_ns": 100,
                        "end_timestamp_ns": 200,
                        "labels": {"scene": {"value": "road"}},
                        "model": "label-model",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "fusion_embeddings.jsonl").write_text(
                json.dumps({"embedding": [0.1, 0.2], "model": "embed-model"}) + "\n",
                encoding="utf-8",
            )
            (run_dir / "run.json").write_text(
                json.dumps({"source_run_dir": "source-run", "bag_oss_key": "rosbags/from-run.bag"}),
                encoding="utf-8",
            )

            statements = build_ingest_statements(
                clip_id="sha256:abc",
                run_id="run-1",
                ds="20260805",
                run_dir=run_dir,
                bag_oss_key="rosbags/explicit.bag",
                now="2026-08-05T00:00:00Z",
            )

        sql = "\n".join(statements)
        self.assertIn("aig_sdk__fact_clip_label", sql)
        self.assertIn("aig_sdk__fact_clip_embedding", sql)
        self.assertIn("'rosbags/explicit.bag'", sql)
        self.assertIn('"scene": "road"', sql)
        for step_id in (
            "sdk_discover",
            "sdk_infer",
            "sdk_upload",
            "sdk_mc_write",
            "sdk_dispatch",
        ):
            self.assertIn(f"'{step_id}'", sql)
        self.assertIn("aig_sdk__pipeline_step", sql)


if __name__ == "__main__":
    unittest.main()
