"""Catalog ops: json_extract path walk + label_tree_input payload + condition bind."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestJsonExtractPath(unittest.TestCase):
    def test_nested_and_plus_level_path(self) -> None:
        from hmi.platform.operators import extract_json_path, normalize_path_keys

        data = {"a": {"b": {"c": 7, "arr": [0, {"k": "v"}]}}}
        self.assertEqual(extract_json_path(data, ["a", "b", "c"]), 7)
        self.assertEqual(extract_json_path(data, normalize_path_keys("a.b.c")), 7)
        self.assertEqual(extract_json_path(data, ["a", "b", "arr", "1", "k"]), "v")
        self.assertEqual(extract_json_path(data, normalize_path_keys(["a", "", "b", "c"])), 7)

    def test_missing_key_returns_none(self) -> None:
        from hmi.platform.operators import extract_json_path

        self.assertIsNone(extract_json_path({"a": 1}, ["b"]))
        self.assertIsNone(extract_json_path({"a": {"b": 1}}, ["a", "c"]))
        self.assertIsNone(extract_json_path([1, 2], ["9"]))
        self.assertIsNone(extract_json_path("not-json", ["a"]))

    def test_parse_json_string(self) -> None:
        from hmi.platform.operators import extract_json_path

        self.assertEqual(extract_json_path('{"x": {"y": true}}', ["x", "y"]), True)


class TestLabelTreeInput(unittest.TestCase):
    def test_const_and_upstream_assignments(self) -> None:
        from hmi.platform.operators import apply_label_tree_assignments

        def resolve(bind: dict) -> object:
            if bind.get("step_key") == "ext":
                return "highway"
            return None

        out = apply_label_tree_assignments(
            [
                {"label_id": "weather", "mode": "const", "value": "rain"},
                {"label_id": "scene", "mode": "upstream", "bind_step_key": "ext", "bind_port_id": "out"},
            ],
            resolve_upstream=resolve,
        )
        self.assertEqual(out["values"]["weather"]["value"], "rain")
        self.assertEqual(out["values"]["scene"]["value"], "highway")


class TestCompileCatalogOps(unittest.TestCase):
    def test_compile_keeps_path_keys_and_assignments(self) -> None:
        from hmi.platform.recipe_pipeline import compile_steps, new_source_card, new_step_from_op

        src = new_source_card(key="txt", title="json", kinds=[".json"])
        ext = new_step_from_op("json_extract", key="ext", slots=[], upstream=[src])
        ext["params"] = {"path_keys": ["a", "b"]}
        ext["bindings"] = {"in": {"kind": "slot", "slot_id": "txt"}}
        fill = new_step_from_op("label_tree_input", key="fill", slots=[], upstream=[ext])
        fill["params"] = {
            "assignments": [
                {
                    "label_id": "scene",
                    "mode": "upstream",
                    "bind_step_key": "ext",
                    "bind_port_id": "out",
                }
            ]
        }
        compiled = compile_steps([src, ext, fill])
        ops = {p["op_id"]: p for p in compiled["preprocess"]}
        self.assertEqual(ops["json_extract"]["params"]["path_keys"], ["a", "b"])
        self.assertEqual(ops["json_extract"]["produces"], ["json_value"])
        self.assertEqual(ops["label_tree_input"]["params"]["assignments"][0]["label_id"], "scene")
        self.assertEqual(ops["label_tree_input"]["produces"], ["labels_tree"])


class TestExtractDrivesCondition(unittest.TestCase):
    def test_json_extract_value_in_if(self) -> None:
        from hmi.platform.graph_expr import eval_condition, validate_condition
        from hmi.platform.graph_runtime import execute_graph

        cond = validate_condition(
            {"all": [{"field": "json_extract.value", "op": "eq", "value": "go"}]},
            after_label=False,
        )
        self.assertTrue(eval_condition(cond, {"json_extract": {"value": "go"}}))
        self.assertFalse(eval_condition(cond, {"json_extract": {"value": "stop"}}))

        node_cond = validate_condition(
            {"all": [{"field": "ext.value", "op": "eq", "value": 3}]},
            after_label=False,
        )
        graph = {
            "nodes": [
                {
                    "key": "src",
                    "type": "source",
                    "op_id": "source",
                    "title": "s",
                    "params": {"required": True, "kinds": [".json"]},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "key": "ext",
                    "type": "op",
                    "op_id": "json_extract",
                    "title": "JSON 值提取",
                    "params": {"path_keys": ["a", "b"]},
                    "position": {"x": 0, "y": 80},
                },
                {
                    "key": "iff",
                    "type": "if",
                    "title": "if",
                    "params": {},
                    "condition": {"all": [{"field": "json_extract.value", "op": "eq", "value": 3}]},
                    "position": {"x": 0, "y": 160},
                },
                {
                    "key": "then_op",
                    "type": "op",
                    "op_id": "text_to_json",
                    "title": "t",
                    "params": {},
                    "position": {"x": 0, "y": 240},
                },
                {
                    "key": "else_op",
                    "type": "op",
                    "op_id": "extract_frames",
                    "title": "f",
                    "params": {},
                    "position": {"x": 0, "y": 240},
                },
                {
                    "key": "lab",
                    "type": "label",
                    "op_id": "label",
                    "title": "AI打标器",
                    "params": {},
                    "position": {"x": 0, "y": 320},
                },
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "ext", "target_port": "in"},
                {"id": "b", "source": "ext", "source_port": "out", "target": "iff", "target_port": "in"},
                {"id": "c", "source": "iff", "source_port": "then", "target": "then_op", "target_port": "in"},
                {"id": "d", "source": "iff", "source_port": "else", "target": "else_op", "target_port": "in"},
                {"id": "e", "source": "then_op", "source_port": "out", "target": "lab", "target_port": "in"},
                {"id": "f", "source": "else_op", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        }
        out = execute_graph(
            graph,
            ctx0={"json": {"a": {"b": 3}}},
            adapters={"text_to_json": lambda n, c: {}, "extract_frames": lambda n, c: {}, "label": lambda n, c: {}},
            enforce_io=False,
        )
        by_key = {row["key"]: row["status"] for row in out["run"]}
        self.assertEqual(by_key["ext"], "success")
        self.assertEqual(by_key["then_op"], "success")
        self.assertEqual(by_key["else_op"], "skipped")
        self.assertTrue(eval_condition(node_cond, out["ctx"]))
        self.assertEqual(out["ctx"]["json_extract"]["value"], 3)

    def test_extract_feeds_label_tree_input(self) -> None:
        from hmi.platform.graph_runtime import execute_graph

        graph = {
            "nodes": [
                {
                    "key": "src",
                    "type": "source",
                    "op_id": "source",
                    "title": "s",
                    "params": {"required": True, "kinds": [".json"]},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "key": "ext",
                    "type": "op",
                    "op_id": "json_extract",
                    "title": "JSON 值提取",
                    "params": {"path_keys": ["a", "b"]},
                    "position": {"x": 0, "y": 80},
                },
                {
                    "key": "fill",
                    "type": "op",
                    "op_id": "label_tree_input",
                    "title": "标签树输入",
                    "params": {
                        "assignments": [
                            {
                                "label_id": "scene",
                                "mode": "upstream",
                                "bind_step_key": "ext",
                                "bind_port_id": "out",
                            },
                            {"label_id": "weather", "mode": "const", "value": "rain"},
                        ]
                    },
                    "position": {"x": 0, "y": 160},
                },
                {
                    "key": "lab",
                    "type": "label",
                    "op_id": "label",
                    "title": "AI打标器",
                    "params": {},
                    "position": {"x": 0, "y": 240},
                },
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "ext", "target_port": "in"},
                {"id": "b", "source": "ext", "source_port": "out", "target": "fill", "target_port": "in"},
                {"id": "c", "source": "fill", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        }
        out = execute_graph(
            graph,
            ctx0={"json": {"a": {"b": "highway"}}},
            adapters={"label": lambda n, c: {}},
            enforce_io=False,
        )
        by_key = {row["key"]: row["status"] for row in out["run"]}
        self.assertEqual(by_key["ext"], "success")
        self.assertEqual(by_key["fill"], "success")
        self.assertEqual(out["ctx"]["json_extract"]["value"], "highway")
        self.assertEqual(out["ctx"]["labels"]["values"]["scene"]["value"], "highway")
        self.assertEqual(out["ctx"]["labels"]["values"]["weather"]["value"], "rain")

    def test_label_tree_input_can_be_terminal_without_ai_label(self) -> None:
        from hmi.platform.graph_runtime import execute_graph

        graph = {
            "nodes": [
                {
                    "key": "src",
                    "type": "source",
                    "op_id": "source",
                    "title": "s",
                    "params": {"required": True, "kinds": [".json"]},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "key": "fill",
                    "type": "op",
                    "op_id": "label_tree_input",
                    "title": "标签树输入",
                    "params": {"assignments": [{"label_id": "scene", "mode": "const", "value": "highway"}]},
                    "position": {"x": 0, "y": 80},
                },
            ],
            "edges": [
                {"id": "a", "source": "src", "source_port": "out", "target": "fill", "target_port": "in"},
            ],
        }
        out = execute_graph(graph, ctx0={}, adapters={}, enforce_io=False)
        by_key = {row["key"]: row["status"] for row in out["run"]}
        self.assertNotIn("lab", by_key)
        self.assertEqual(by_key["fill"], "success")
        self.assertEqual(out["ctx"]["labels"]["values"]["scene"]["value"], "highway")
        self.assertIn("labels_tree", out["ctx"])


class TestDisplayOpTitle(unittest.TestCase):
    def test_legacy_labeler_name(self) -> None:
        from hmi.platform.operators import display_op_title

        self.assertEqual(display_op_title("label"), "AI打标器")
        self.assertEqual(display_op_title("label", "打标器"), "AI打标器")
        self.assertEqual(display_op_title("label", "自定义名"), "自定义名")
        self.assertEqual(display_op_title("json_extract"), "JSON 值提取")
        self.assertEqual(display_op_title("text_to_json", "prep-5-text_to_json"), "文本结构化")
        self.assertEqual(display_op_title("detect_bbox", "prep-6-detect_bbox"), "BBox 检测器")
        self.assertEqual(display_op_title("embed", "stage-embed"), "向量化器")


class TestLabelCatalogCallFields(unittest.TestCase):
    def test_label_has_per_model_call_fields(self) -> None:
        from hmi.platform.operators import list_operators

        label = next(op for op in list_operators() if op["op_id"] == "label")
        self.assertIn("default", label["call_fields_by_model"])
        self.assertIn("nvh_sem_vl", label["call_fields_by_model"])
        keys = [f["key"] for f in label["omni_prompt_fields"]]
        self.assertIn("system_role", keys)
        self.assertIn("labeling_rules", keys)


if __name__ == "__main__":
    unittest.main()
