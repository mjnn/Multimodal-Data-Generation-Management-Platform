"""UI-DTYPE-DAG-CANVAS: recipe.graph validate / hydrate / project."""

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
            {"key": "src", "type": "source", "op_id": "source", "title": "源", "params": {}, "position": {"x": 0, "y": 0}},
            {"key": "asr", "type": "op", "op_id": "transcribe", "title": "ASR", "params": {}, "position": {"x": 0, "y": 80}},
            {"key": "lab", "type": "label", "op_id": "label", "title": "打标器", "params": {}, "position": {"x": 0, "y": 160}},
        ],
        "edges": [
            {"id": "e1", "source": "src", "source_port": "out", "target": "asr", "target_port": "in"},
            {"id": "e2", "source": "asr", "source_port": "out", "target": "lab", "target_port": "in"},
        ],
    }


class TestValidateGraph(unittest.TestCase):
    def test_valid_chain_roundtrip(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        out = validate_graph(_chain())
        self.assertEqual(len(out["nodes"]), 3)
        self.assertEqual(len(out["edges"]), 2)

    def test_rejects_cycle(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["edges"].append({"id": "loop", "source": "lab", "source_port": "out", "target": "asr", "target_port": "in"})
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        self.assertIn("cycle", str(ctx.exception).lower())

    def test_requires_exactly_one_label(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"] = [n for n in g["nodes"] if n["type"] != "label"]
        g["edges"] = [e for e in g["edges"] if e["target"] != "lab"]
        with self.assertRaises(ValueError):
            validate_graph(g)

    def test_required_source_must_reach_label(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append(
            {
                "key": "orphan",
                "type": "source",
                "op_id": "source",
                "title": "孤立源",
                "params": {"required": True},
                "position": {"x": 200, "y": 0},
            }
        )
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        self.assertIn("打标", str(ctx.exception))

    def test_if_requires_then_else_ports(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].insert(
            2,
            {"key": "iff", "type": "if", "title": "if", "params": {}, "condition": {"all": []}, "position": {"x": 0, "y": 120}},
        )
        g["edges"] = [
            {"id": "e1", "source": "src", "source_port": "out", "target": "asr", "target_port": "in"},
            {"id": "e2", "source": "asr", "source_port": "out", "target": "iff", "target_port": "in"},
            {"id": "e3", "source": "iff", "source_port": "then", "target": "lab", "target_port": "in"},
        ]
        with self.assertRaises(ValueError):
            validate_graph(g)

    def test_review_before_label_rejected(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append({"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 40}})
        g["edges"].append({"id": "bad", "source": "src", "source_port": "out", "target": "rev", "target_port": "in"})
        g["edges"].append({"id": "bad2", "source": "rev", "source_port": "out", "target": "asr", "target_port": "in"})
        with self.assertRaises(ValueError):
            validate_graph(g)

    def test_rejects_parallel_join_of_compute_branches(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append(
            {"key": "ext", "type": "op", "op_id": "extract", "title": "Extract", "params": {}, "position": {"x": 120, "y": 80}}
        )
        g["edges"].append({"id": "e3", "source": "src", "source_port": "out", "target": "ext", "target_port": "in"})
        g["edges"].append({"id": "e4", "source": "ext", "source_port": "out", "target": "lab", "target_port": "in"})
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        msg = str(ctx.exception)
        self.assertTrue("并行" in msg or "join" in msg.lower())

    def test_allows_xor_merge_at_label(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].insert(
            2,
            {"key": "iff", "type": "if", "title": "if", "params": {}, "condition": {"all": []}, "position": {"x": 0, "y": 120}},
        )
        g["nodes"].append(
            {"key": "then_op", "type": "op", "op_id": "audio_asr", "title": "Then", "params": {}, "position": {"x": -80, "y": 200}}
        )
        g["edges"] = [
            {"id": "e1", "source": "src", "source_port": "out", "target": "asr", "target_port": "in"},
            {"id": "e2", "source": "asr", "source_port": "out", "target": "iff", "target_port": "in"},
            {"id": "e3", "source": "iff", "source_port": "then", "target": "then_op", "target_port": "in"},
            {"id": "e4", "source": "then_op", "source_port": "out", "target": "lab", "target_port": "in"},
            {"id": "e5", "source": "iff", "source_port": "else", "target": "lab", "target_port": "in"},
        ]
        out = validate_graph(g)
        self.assertEqual(len(out["nodes"]), 5)

    def test_allows_multi_source_fan_in_to_label(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append(
            {"key": "src2", "type": "source", "op_id": "source", "title": "源2", "params": {}, "position": {"x": 120, "y": 0}}
        )
        g["edges"].append({"id": "e3", "source": "src2", "source_port": "out", "target": "lab", "target_port": "in"})
        out = validate_graph(g)
        self.assertEqual(len(out["nodes"]), 4)

    def test_review_mixed_path_rejected(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append({"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 240}})
        g["edges"].append({"id": "e3", "source": "src", "source_port": "out", "target": "rev", "target_port": "in"})
        g["edges"].append({"id": "e4", "source": "lab", "source_port": "out", "target": "rev", "target_port": "in"})
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        self.assertIn("打标", str(ctx.exception))

    def test_review_only_after_label_passes(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append({"key": "rev", "type": "review", "title": "校核", "params": {}, "position": {"x": 0, "y": 240}})
        g["edges"].append({"id": "e3", "source": "lab", "source_port": "out", "target": "rev", "target_port": "in"})
        out = validate_graph(g)
        self.assertEqual(len(out["nodes"]), 4)

    def test_export_mixed_path_rejected(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"].append({"key": "exp", "type": "export", "title": "导出", "params": {}, "position": {"x": 0, "y": 240}})
        g["edges"].append({"id": "e3", "source": "src", "source_port": "out", "target": "exp", "target_port": "in"})
        g["edges"].append({"id": "e4", "source": "lab", "source_port": "out", "target": "exp", "target_port": "in"})
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        self.assertIn("打标", str(ctx.exception))


class TestHydrateGraph(unittest.TestCase):
    def test_oms_cabin_chain_has_label(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph, validate_graph

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        self.assertFalse(rec.get("graph"))
        g = hydrate_graph(rec)
        validate_graph(g)
        types = [n["type"] for n in g["nodes"]]
        self.assertIn("source", types)
        self.assertEqual(types.count("label"), 1)
        keys = [n["key"] for n in g["nodes"]]
        idx = {k: i for i, k in enumerate(keys)}
        for e in g["edges"]:
            self.assertLess(idx[e["source"]], idx[e["target"]])

    def test_existing_graph_not_rebuilt(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        rec["graph"]["nodes"][0]["title"] = "自定义源名"
        again = hydrate_graph(rec)
        self.assertEqual(again["nodes"][0]["title"], "自定义源名")


class TestProjectGraph(unittest.TestCase):
    def test_chain_projects_asr_into_preprocess(self) -> None:
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = validate_graph(_chain())
        proj = project_graph(g)
        self.assertEqual(proj["slots"][0]["id"], "src")
        self.assertTrue(proj["stages"]["label"]["enabled"])
        ops = [p["op_id"] for p in proj["preprocess"]]
        self.assertEqual(ops, ["transcribe"])

    def test_then_only_op_not_in_preprocess(self) -> None:
        from hmi.platform.recipe_graph import graph_is_lossy, project_graph, validate_graph

        g = {
            "nodes": [
                {"key": "src", "type": "source", "op_id": "source", "title": "源", "params": {}, "position": {"x": 0, "y": 0}},
                {"key": "iff", "type": "if", "title": "if", "condition": {"all": []}, "params": {}, "position": {"x": 0, "y": 80}},
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
        g = validate_graph(g)
        proj = project_graph(g)
        self.assertEqual(proj["preprocess"], [])
        self.assertTrue(graph_is_lossy(g))
        self.assertTrue(proj["stages"]["label"]["enabled"])


class TestRecipeGraphIntegration(unittest.TestCase):
    def test_validate_recipe_projects_graph(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        out = validate_recipe(rec)
        self.assertTrue(out["graph"]["nodes"])
        self.assertTrue(out["stages"]["label"]["enabled"])
        self.assertEqual(out["overview"]["detail"][0]["widget_id"], "labels_tree")

    def test_ivi_seed_label_enabled(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        out = validate_recipe(SEED_RECIPES["ivi_ui_stub"])
        self.assertTrue(out["stages"]["label"]["enabled"])


class TestNodeParamOverrides(unittest.TestCase):
    def test_overrides_params_without_reordering(self) -> None:
        from hmi.platform.recipe_graph import apply_node_param_overrides, ordered_node_keys, validate_graph

        g = validate_graph(_chain())
        before = [n["key"] for n in g["nodes"]]
        out = apply_node_param_overrides(
            g,
            {"asr": {"params": {"model": "paraformer"}}, "src": {"params": {"kinds": [".wav"]}}},
        )
        self.assertEqual([n["key"] for n in out["nodes"]], before)
        asr = next(n for n in out["nodes"] if n["key"] == "asr")
        self.assertEqual(asr["params"]["model"], "paraformer")
        src = next(n for n in out["nodes"] if n["key"] == "src")
        self.assertEqual(src["params"]["kinds"], [".wav"])
        self.assertEqual(ordered_node_keys(out), before)

    def test_recipe_with_dag_overrides_updates_label_model(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph
        from hmi.platform.run_bind import recipe_with_dag_overrides

        rec = dict(validate_recipe(SEED_RECIPES["audio_array_spec"]))
        rec["graph"] = hydrate_graph(rec)
        rec = validate_recipe(rec)
        label = next(n for n in rec["graph"]["nodes"] if n["type"] == "label")
        out = recipe_with_dag_overrides(
            rec,
            {"dag_node_overrides": {rec["id"]: {label["key"]: {"params": {"model": "nvh_sem_heuristic"}}}}},
            rec["id"],
        )
        patched = next(n for n in out["graph"]["nodes"] if n["key"] == label["key"])
        self.assertEqual(patched["params"]["model"], "nvh_sem_heuristic")
        self.assertEqual([n["key"] for n in out["graph"]["nodes"]], [n["key"] for n in rec["graph"]["nodes"]])


class TestGraphExpr(unittest.TestCase):
    def test_empty_all_is_true(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        self.assertTrue(eval_condition({"all": []}, {}))

    def test_and_kind_and_confidence(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        cond = {
            "all": [
                {"field": "source.kind", "op": "in", "value": ["rosbag", "video"]},
                {"field": "asr.avg_confidence", "op": "gte", "value": 0.6},
            ]
        }
        self.assertTrue(eval_condition(cond, {"source": {"kind": "rosbag"}, "asr": {"avg_confidence": 0.9}}))
        self.assertFalse(eval_condition(cond, {"source": {"kind": "audio"}, "asr": {"avg_confidence": 0.9}}))

    def test_missing_field_is_false(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        cond = {"all": [{"field": "asr.has_text", "op": "eq", "value": True}]}
        self.assertFalse(eval_condition(cond, {}))

    def test_labels_dotpath(self) -> None:
        from hmi.platform.graph_expr import eval_condition

        cond = {"all": [{"field": "labels.cabin.scene", "op": "eq", "value": "highway"}]}
        self.assertTrue(eval_condition(cond, {"labels": {"cabin": {"scene": "highway"}}}))

    def test_reject_unknown_field_before_label(self) -> None:
        from hmi.platform.graph_expr import validate_condition

        with self.assertRaises(ValueError):
            validate_condition({"all": [{"field": "labels.x", "op": "eq", "value": 1}]}, after_label=False)

    def test_reject_js(self) -> None:
        from hmi.platform.graph_expr import validate_condition

        with self.assertRaises(ValueError):
            validate_condition({"all": [{"field": "source.kind", "op": "eval", "value": "1"}]}, after_label=False)


if __name__ == "__main__":
    unittest.main()
