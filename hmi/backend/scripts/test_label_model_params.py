"""Label DAG node: per-model call params survive compile / validate / project_graph."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestLabelStageExtras(unittest.TestCase):
    def test_omni_keys_only_for_default(self) -> None:
        from hmi.platform.label_model_params import label_stage_extras

        extras = label_stage_extras(
            {
                "model": "default",
                "omni_model_id": "qwen3.5-omni-plus",
                "omni_label_prompt": {"system_role": "舱内标注助手", "unknown": "drop"},
                "bbox_in_label_prompt": False,
                "temperature": 0.3,
                "max_tokens": 2048,
                "ast_top_k": 9,
                "reference_constraints": "NVH only",
            }
        )
        self.assertEqual(extras["omni_model_id"], "qwen3.5-omni-plus")
        self.assertEqual(extras["omni_label_prompt"], {"system_role": "舱内标注助手"})
        self.assertFalse(extras["bbox_in_label_prompt"])
        self.assertEqual(extras["temperature"], 0.3)
        self.assertEqual(extras["max_tokens"], 2048)
        self.assertNotIn("ast_top_k", extras)
        self.assertNotIn("reference_constraints", extras)

    def test_nvh_ast_does_not_leak_omni(self) -> None:
        from hmi.platform.label_model_params import label_stage_extras

        extras = label_stage_extras(
            {
                "model": "nvh_sem_ast",
                "omni_label_prompt": {"system_role": "should not copy"},
                "ast_top_k": 7,
                "reference_constraints": "  只写假设  ",
            }
        )
        self.assertEqual(extras, {"ast_top_k": 7, "reference_constraints": "只写假设"})


class TestCompileAndValidateKeepOmni(unittest.TestCase):
    def test_compile_steps_copies_omni_prompt(self) -> None:
        from hmi.platform.recipe_pipeline import compile_steps, new_source_card, new_step_from_op

        src = new_source_card(key="src", title="源", kinds=[".mp4"])
        label = new_step_from_op("label", key="stage-label", slots=[], upstream=[src])
        label["params"] = {
            "model": "default",
            "omni_label_prompt": {"system_role": "舱内标注助手", "labeling_rules": "一条规则"},
            "omni_model_id": "qwen3.5-omni-plus",
            "bbox_in_label_prompt": True,
            "ast_top_k": 3,
        }
        compiled = compile_steps([src, label])
        stage = compiled["stages"]["label"]
        self.assertTrue(stage["enabled"])
        self.assertEqual(stage["model"], "default")
        self.assertEqual(stage["omni_model_id"], "qwen3.5-omni-plus")
        self.assertEqual(stage["omni_label_prompt"]["system_role"], "舱内标注助手")
        self.assertTrue(stage["bbox_in_label_prompt"])
        self.assertNotIn("ast_top_k", stage)

    def test_validate_recipe_keeps_omni_without_graph(self) -> None:
        from hmi.platform.recipe import validate_recipe

        rec = {
            "id": "label_omni_keep",
            "title": "keep omni",
            "purpose": "validate extras",
            "owner": "qa",
            "taxonomy_id": "oms",
            "overview_view": "custom",
            "status": "draft",
            "require_any_kinds": [[".mp4"]],
            "slots": [
                {
                    "id": "src",
                    "kinds": [".mp4"],
                    "cardinality_min": 1,
                    "cardinality_max": 1,
                    "role": "primary",
                    "required": True,
                }
            ],
            "preprocess": [],
            "products": [],
            "stages": {
                "label": {
                    "enabled": True,
                    "model": "default",
                    "omni_label_prompt": {"system_role": "舱内标注助手"},
                    "temperature": 0.2,
                },
                "embed": {"enabled": False},
            },
            "bbox": {"enabled": False, "detector": "opencv", "yolo_classes": ""},
        }
        out = validate_recipe(rec)
        self.assertEqual(out["stages"]["label"]["omni_label_prompt"]["system_role"], "舱内标注助手")
        self.assertEqual(out["stages"]["label"]["temperature"], 0.2)


class TestProjectGraphLabelNode(unittest.TestCase):
    def test_label_node_params_not_only_prefix_ops(self) -> None:
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = {
            "nodes": [
                {
                    "key": "src",
                    "type": "source",
                    "op_id": "source",
                    "title": "源",
                    "params": {"kinds": [".mp4"], "required": True},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "key": "lab",
                    "type": "label",
                    "op_id": "label",
                    "title": "AI打标器",
                    "params": {
                        "model": "default",
                        "omni_label_prompt": {"system_role": "从图节点来"},
                        "omni_model_id": "qwen3.5-omni-plus",
                    },
                    "position": {"x": 0, "y": 80},
                },
            ],
            "edges": [
                {
                    "id": "e1",
                    "source": "src",
                    "source_port": "out",
                    "target": "lab",
                    "target_port": "in",
                }
            ],
        }
        proj = project_graph(validate_graph(g))
        stage = proj["stages"]["label"]
        self.assertTrue(stage["enabled"])
        self.assertEqual(stage["model"], "default")
        self.assertEqual(stage["omni_label_prompt"]["system_role"], "从图节点来")
        self.assertEqual(stage["omni_model_id"], "qwen3.5-omni-plus")
        self.assertEqual(proj["preprocess"], [])

    def test_validate_recipe_projects_graph_label_params(self) -> None:
        from hmi.platform.recipe import validate_recipe

        rec = {
            "id": "graph_label_params",
            "title": "graph label",
            "purpose": "project from type=label node",
            "owner": "qa",
            "taxonomy_id": "oms",
            "overview_view": "custom",
            "status": "draft",
            "require_any_kinds": [[".mp4"]],
            "slots": [
                {
                    "id": "src",
                    "kinds": [".mp4"],
                    "cardinality_min": 1,
                    "cardinality_max": 1,
                    "role": "primary",
                    "required": True,
                }
            ],
            "preprocess": [],
            "products": [],
            "stages": {"label": {"enabled": True}, "embed": {"enabled": False}},
            "bbox": {"enabled": False, "detector": "opencv"},
            "graph": {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "源",
                        "params": {"kinds": [".mp4"], "required": True, "cardinality_min": 1, "cardinality_max": 1},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "lab",
                        "type": "label",
                        "op_id": "label",
                        "title": "AI打标器",
                        "params": {
                            "model": "nvh_sem_ast",
                            "ast_top_k": 4,
                            "reference_constraints": "AST 备注",
                            "omni_label_prompt": {"system_role": "leak"},
                        },
                        "position": {"x": 0, "y": 80},
                    },
                ],
                "edges": [
                    {"id": "e1", "source": "src", "source_port": "out", "target": "lab", "target_port": "in"}
                ],
            },
        }
        out = validate_recipe(rec)
        stage = out["stages"]["label"]
        self.assertEqual(stage["model"], "nvh_sem_ast")
        self.assertEqual(stage["ast_top_k"], 4)
        self.assertEqual(stage["reference_constraints"], "AST 备注")
        self.assertNotIn("omni_label_prompt", stage)


class TestCatalogLabelCallFields(unittest.TestCase):
    def test_label_catalog_exposes_call_and_omni_fields(self) -> None:
        from hmi.platform.operators import list_operators

        catalog = {op["op_id"]: op for op in list_operators()}
        label = catalog["label"]
        self.assertIn("nvh_sem_vl", {m["id"] for m in label["models"]})
        self.assertIn("omni_label_prompt", [f["key"] for f in label["call_fields_by_model"]["default"]])
        self.assertIn("ast_top_k", [f["key"] for f in label["call_fields_by_model"]["nvh_sem_ast"]])
        self.assertTrue(any(f["key"] == "system_role" for f in label["omni_prompt_fields"]))


if __name__ == "__main__":
    unittest.main()
