"""Execution progress cards expand from DataType DAG, not a fixed 4-step SDK list."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


def _chain() -> dict:
    return {
        "nodes": [
            {
                "key": "src",
                "type": "source",
                "op_id": "source",
                "title": "源",
                "params": {},
                "position": {"x": 0, "y": 0},
            },
            {
                "key": "asr",
                "type": "op",
                "op_id": "transcribe",
                "title": "音频 ASR",
                "params": {},
                "position": {"x": 0, "y": 80},
            },
            {
                "key": "lab",
                "type": "label",
                "op_id": "label",
                "title": "打标器",
                "params": {},
                "position": {"x": 0, "y": 160},
            },
        ],
        "edges": [
            {"id": "e1", "source": "src", "source_port": "out", "target": "asr", "target_port": "in"},
            {"id": "e2", "source": "asr", "source_port": "out", "target": "lab", "target_port": "in"},
        ],
    }


class TestExpandProgressSteps(unittest.TestCase):
    def test_no_graph_hides_infra_steps(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps

        steps = expand_progress_steps(graph=None, step_map={}, local=True)
        self.assertEqual([s["step_id"] for s in steps], ["sdk_infer"])
        self.assertEqual(steps[0]["label"], "SDK 打标与向量")

    def test_dag_replaces_sdk_infer_and_hides_infra(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps

        steps = expand_progress_steps(
            graph=_chain(),
            step_map={"sdk_infer": {"status": "running"}},
            local=True,
        )
        ids = [s["step_id"] for s in steps]
        labels = [s["label"] for s in steps]
        self.assertEqual(ids, ["dag:asr", "dag:lab"])
        self.assertEqual(labels, ["音频 ASR", "AI打标器"])
        self.assertNotIn("SDK 打标与向量", labels)
        self.assertNotIn("SQLite 写入", labels)
        self.assertNotIn("OSS 上传", labels)
        self.assertNotIn("调度发布", labels)
        self.assertEqual(steps[0]["status"], "running")
        self.assertEqual(steps[1]["status"], "pending")

    def test_per_node_dag_steps_win_over_sdk_infer_blob(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps

        steps = expand_progress_steps(
            graph=_chain(),
            step_map={
                "sdk_infer": {"status": "running"},
                "dag:asr": {"status": "success"},
                "dag:lab": {"status": "running"},
            },
            local=True,
        )
        by_id = {s["step_id"]: s for s in steps}
        self.assertEqual(by_id["dag:asr"]["status"], "success")
        self.assertEqual(by_id["dag:lab"]["status"], "running")

    def test_infer_success_marks_dag_done(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps

        steps = expand_progress_steps(
            graph=_chain(),
            step_map={
                "sdk_infer": {"status": "success"},
                "sdk_mc_write": {"status": "running"},
            },
            local=True,
        )
        by_id = {s["step_id"]: s for s in steps}
        self.assertEqual(by_id["dag:asr"]["status"], "success")
        self.assertEqual(by_id["dag:lab"]["status"], "success")
        self.assertNotIn("sdk_mc_write", by_id)

    def test_import_failure_attaches_to_last_dag_node(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps

        steps = expand_progress_steps(
            graph=_chain(),
            step_map={
                "sdk_infer": {"status": "success"},
                "sdk_mc_write": {
                    "status": "failed",
                    "error_message": "no importable runs under /tmp/out",
                },
            },
            local=True,
        )
        self.assertEqual(steps[0]["status"], "success")
        self.assertIsNone(steps[0]["error_message"])
        self.assertEqual(steps[1]["status"], "failed")
        self.assertIn("no importable runs", steps[1]["error_message"] or "")
        self.assertEqual(steps[1]["label"], "AI打标器")
        self.assertEqual(len(steps), 2)

    def test_legacy_import_error_on_sdk_infer_not_blamed_on_parser(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps

        steps = expand_progress_steps(
            graph=_chain(),
            step_map={
                "sdk_infer": {
                    "status": "failed",
                    "error_message": "error: no importable runs under D:/tmp/out",
                },
                "sdk_mc_write": {"status": "failed", "error_message": "error: no importable runs"},
            },
            local=True,
        )
        self.assertEqual(steps[0]["status"], "success")
        self.assertEqual(steps[0]["label"], "音频 ASR")
        self.assertEqual(steps[1]["status"], "failed")
        self.assertEqual(steps[1]["label"], "AI打标器")
        self.assertIn("no importable runs", steps[1]["error_message"] or "")

    def test_infer_failed_attaches_error_to_first_dag_node(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps

        steps = expand_progress_steps(
            graph=_chain(),
            step_map={"sdk_infer": {"status": "failed", "error_message": "boom"}},
            local=True,
        )
        self.assertEqual(steps[0]["status"], "failed")
        self.assertEqual(steps[0]["error_message"], "boom")
        self.assertEqual(steps[1]["status"], "pending")
        self.assertIsNone(steps[1]["error_message"])

    def test_skips_if_review_export(self) -> None:
        from hmi.platform.progress_steps import graph_work_nodes

        g = _chain()
        g["nodes"].append(
            {
                "key": "rev",
                "type": "review",
                "op_id": "review",
                "title": "校核",
                "params": {},
                "position": {"x": 0, "y": 240},
            }
        )
        g["edges"].append(
            {"id": "e3", "source": "lab", "source_port": "out", "target": "rev", "target_port": "in"}
        )
        keys = [n["key"] for n in graph_work_nodes(g)]
        self.assertEqual(keys, ["asr", "lab"])

    def test_oms_cabin_seed_titles(self) -> None:
        from hmi.platform.progress_steps import expand_progress_steps
        from hmi.platform.recipe import _oms_cabin_graph

        steps = expand_progress_steps(
            graph=_oms_cabin_graph(),
            step_map={"sdk_infer": {"status": "pending"}},
            local=True,
        )
        labels = [s["label"] for s in steps]
        self.assertIn("ROSBAG 解析器", labels)
        self.assertIn("视频抽帧", labels)
        self.assertIn("AI打标器", labels)
        self.assertNotIn("SQLite 写入", labels)
        self.assertNotIn("OSS 上传", labels)
        self.assertNotIn("调度发布", labels)
        self.assertNotIn("SDK 打标与向量", labels)
        self.assertTrue(any(s["step_id"].startswith("dag:") for s in steps))


if __name__ == "__main__":
    unittest.main()
