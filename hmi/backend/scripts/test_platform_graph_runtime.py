"""UI-DTYPE-DAG-CANVAS: graph_runtime execute_graph + fake adapters."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


def _source_kind_if_graph() -> dict:
    return {
        "nodes": [
            {
                "key": "src",
                "type": "source",
                "op_id": "source",
                "title": "s",
                "params": {"required": True, "kinds": ["audio"]},
                "position": {"x": 0, "y": 0},
            },
            {
                "key": "iff",
                "type": "if",
                "title": "if",
                "params": {},
                "condition": {"all": [{"field": "source.kind", "op": "eq", "value": "audio"}]},
                "position": {"x": 0, "y": 80},
            },
            {"key": "asr", "type": "op", "op_id": "transcribe", "title": "ASR", "params": {}, "position": {"x": 0, "y": 160}},
            {"key": "fr", "type": "op", "op_id": "extract_frames", "title": "抽帧", "params": {}, "position": {"x": 160, "y": 160}},
            {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 240}},
            {"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 320}},
        ],
        "edges": [
            {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
            {"id": "b", "source": "iff", "source_port": "then", "target": "asr", "target_port": "in"},
            {"id": "c", "source": "iff", "source_port": "else", "target": "fr", "target_port": "in"},
            {"id": "d", "source": "asr", "source_port": "out", "target": "lab", "target_port": "in"},
            {"id": "e", "source": "fr", "source_port": "out", "target": "lab", "target_port": "in"},
            {"id": "f", "source": "lab", "source_port": "out", "target": "rev", "target_port": "in"},
        ],
    }


def _linear_ops_graph() -> dict:
    return {
        "nodes": [
            {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True, "kinds": ["video"]}, "position": {"x": 0, "y": 0}},
            {"key": "bb", "type": "op", "op_id": "detect_bbox", "title": "bbox", "params": {}, "position": {"x": 0, "y": 80}},
            {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 160}},
            {"key": "emb", "type": "op", "op_id": "embed", "title": "向量", "params": {}, "position": {"x": 0, "y": 240}},
        ],
        "edges": [
            {"id": "a", "source": "src", "source_port": "out", "target": "bb", "target_port": "in"},
            {"id": "b", "source": "bb", "source_port": "out", "target": "lab", "target_port": "in"},
            {"id": "c", "source": "lab", "source_port": "out", "target": "emb", "target_port": "in"},
        ],
    }


def _if_branch_graph() -> dict:
    return {
        "nodes": [
            {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True, "kinds": ["audio"]}, "position": {"x": 0, "y": 0}},
            {
                "key": "iff",
                "type": "if",
                "title": "if",
                "params": {},
                "condition": {"all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.9}]},
                "position": {"x": 0, "y": 80},
            },
            {"key": "fr", "type": "op", "op_id": "extract_frames", "title": "抽帧", "params": {}, "position": {"x": 0, "y": 160}},
            {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 240}},
        ],
        "edges": [
            {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
            {"id": "b", "source": "iff", "source_port": "then", "target": "fr", "target_port": "in"},
            {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
            {"id": "d", "source": "fr", "source_port": "out", "target": "lab", "target_port": "in"},
        ],
    }


class TestGraphRuntime(unittest.TestCase):
    def test_if_false_skips_then_op(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True, "kinds": ["audio"]}, "position": {"x": 0, "y": 0}},
                {
                    "key": "iff",
                    "type": "if",
                    "title": "if",
                    "params": {},
                    "condition": {"all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.9}]},
                    "position": {"x": 0, "y": 80},
                },
                {"key": "fr", "type": "op", "op_id": "extract_frames", "title": "抽帧", "params": {}, "position": {"x": 0, "y": 160}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 240}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "fr", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
                {"id": "d", "source": "fr", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        })
        ran = []

        def frames(_n, ctx):
            ran.append("frames")
            return ctx

        def label(_n, ctx):
            ran.append("label")
            ctx = dict(ctx)
            ctx["labels"] = {"ok": True}
            return ctx

        out = execute_graph(
            g,
            ctx0={"source": {"kind": "audio", "slot_id": "src"}, "asr": {"avg_confidence": 0.1}},
            adapters={"extract_frames": frames, "label": label},
        )
        self.assertEqual(ran, ["label"])
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["fr"], "skipped")
        self.assertEqual(statuses["lab"], "success")

    def test_review_sets_pending(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 80}},
                {"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 160}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "lab", "target_port": "in"},
                {"id": "b", "source": "lab", "source_port": "out", "target": "rev", "target_port": "in"},
            ],
        })
        out = execute_graph(
            g,
            ctx0={"source": {"kind": "video", "slot_id": "src"}},
            adapters={"label": lambda n, c: {**c, "labels": {}}},
        )
        self.assertEqual(out["ctx"].get("review_status"), "pending_review")

    def test_export_registers_selected_products(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 80}},
                {
                    "key": "exp",
                    "type": "export",
                    "title": "导出",
                    "params": {"exported_product_ids": ["labels_tree", "mel_matrix"]},
                    "position": {"x": 0, "y": 160}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "lab", "target_port": "in"},
                {"id": "b", "source": "lab", "source_port": "out", "target": "exp", "target_port": "in"},
            ],
        })
        out = execute_graph(
            g,
            ctx0={"source": {"kind": "video", "slot_id": "src"}},
            adapters={"label": lambda n, c: {**c, "labels": {}}},
        )
        self.assertEqual(out["ctx"].get("exported_product_ids"), ["labels_tree", "mel_matrix"])

    def test_if_true_runs_then_op(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_if_branch_graph())
        ran = []

        def frames(_n, ctx):
            ran.append("frames")
            return ctx

        def label(_n, ctx):
            ran.append("label")
            return {**ctx, "labels": {"ok": True}}

        out = execute_graph(
            g,
            ctx0={"source": {"kind": "audio", "slot_id": "src"}, "asr": {"avg_confidence": 0.95}},
            adapters={"extract_frames": frames, "label": label},
        )
        self.assertEqual(ran, ["frames", "label"])
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["fr"], "success")
        self.assertEqual(statuses["lab"], "success")

    def test_missing_adapter_raises(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 80}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        })
        with self.assertRaises(RuntimeError) as ctx:
            execute_graph(g, ctx0={"source": {"kind": "audio", "slot_id": "src"}}, adapters={})
        self.assertIn("missing adapter for op_id=label", str(ctx.exception))

    def test_assert_blocks_asr_if(self) -> None:
        from hmi.platform.graph_runtime import assert_runnable_locally
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph({
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "s", "params": {"required": True}, "position": {"x": 0, "y": 0}},
                {
                    "key": "iff",
                    "type": "if",
                    "title": "if",
                    "params": {},
                    "condition": {"all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.9}]},
                    "position": {"x": 0, "y": 80},
                },
                {"key": "lab", "type": "label", "op_id": "label", "title": "打标", "params": {}, "position": {"x": 0, "y": 160}},
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "b", "source": "iff", "source_port": "then", "target": "lab", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
            ],
        })
        with self.assertRaises(RuntimeError) as ctx:
            assert_runnable_locally(g)
        self.assertEqual(str(ctx.exception), "本地尚未拆分 plan_and_run：不能在 ASR/打标之后分支")

    def test_assert_allows_source_kind_if(self) -> None:
        from hmi.platform.graph_runtime import assert_runnable_locally
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_source_kind_if_graph())
        assert_runnable_locally(g)

    def test_preview_taken_op_ids(self) -> None:
        from hmi.platform.graph_runtime import preview_taken_op_ids
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_source_kind_if_graph())
        taken = preview_taken_op_ids(g, {})
        self.assertIn("transcribe", taken)
        self.assertIn("label", taken)
        self.assertNotIn("extract_frames", taken)
        self.assertIn("source", taken)
        self.assertIn("review", taken)

    def test_apply_graph_to_run_request(self) -> None:
        from hmi.platform.graph_runtime import apply_graph_to_run_request
        from hmi.platform.recipe import SEED_RECIPES
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_linear_ops_graph())
        out = apply_graph_to_run_request(
            g,
            SEED_RECIPES["oms_cabin"],
            {"bbox_enabled": False, "bbox_detector": "yolo", "bbox_yolo_classes": "person"},
        )
        self.assertTrue(out["need_label"])
        self.assertTrue(out["need_embed"])
        self.assertTrue(out["bbox_enabled"])
        self.assertEqual(out["bbox_detector"], "yolo")
        self.assertEqual(out["bbox_yolo_classes"], "person")
        self.assertEqual(
            set(out),
            {"need_label", "need_embed", "bbox_enabled", "bbox_detector", "bbox_yolo_classes"},
        )

        no_bbox = apply_graph_to_run_request(
            validate_graph(_source_kind_if_graph()),
            SEED_RECIPES["oms_cabin"],
            {"bbox_enabled": False, "bbox_detector": "opencv"},
        )
        self.assertTrue(no_bbox["need_label"])
        self.assertFalse(no_bbox["need_embed"])
        self.assertFalse(no_bbox["bbox_enabled"])
        self.assertEqual(no_bbox["bbox_detector"], "opencv")

        forced = apply_graph_to_run_request(
            validate_graph(_source_kind_if_graph()),
            SEED_RECIPES["oms_cabin"],
            {"bbox_enabled": True, "bbox_detector": "yolo"},
        )
        self.assertTrue(forced["bbox_enabled"])
        self.assertEqual(forced["bbox_detector"], "yolo")

        ivi = apply_graph_to_run_request(
            validate_graph(_source_kind_if_graph()),
            SEED_RECIPES["ivi_ui_stub"],
            {"bbox_enabled": False, "bbox_detector": "yolo"},
        )
        self.assertTrue(ivi["bbox_enabled"])
        self.assertEqual(ivi["bbox_detector"], "opencv")


if __name__ == "__main__":
    unittest.main()
