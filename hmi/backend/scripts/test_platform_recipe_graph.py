"""UI-DTYPE-DAG-CANVAS: recipe.graph validate / hydrate / project."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


def _fill_graph(*, extra_wav: bool = False) -> dict:
    nodes = [
        {
            "key": "json_src",
            "type": "source",
            "op_id": "source",
            "title": "问题判断标签",
            "params": {"required": True, "kinds": [".json"]},
            "position": {"x": 0, "y": 0},
        },
        {
            "key": "ext",
            "type": "op",
            "op_id": "json_extract",
            "title": "JSON 值提取",
            "params": {"path_keys": ["tag"]},
            "position": {"x": 0, "y": 80},
        },
        {
            "key": "fill",
            "type": "op",
            "op_id": "label_tree_input",
            "title": "标签树输入",
            "params": {"assignments": [{"label_id": "audio.defect.has_problem", "mode": "upstream"}]},
            "position": {"x": 0, "y": 160},
        },
    ]
    edges = [
        {"id": "j-e", "source": "json_src", "source_port": "out", "target": "ext", "target_port": "in"},
        {"id": "e-f", "source": "ext", "source_port": "out", "target": "fill", "target_port": "in"},
    ]
    if extra_wav:
        nodes.extend(
            [
                {
                    "key": "wav_src",
                    "type": "source",
                    "op_id": "source",
                    "title": "车内录音",
                    "params": {"required": True, "kinds": [".wav"]},
                    "position": {"x": 240, "y": 0},
                },
                {
                    "key": "mel",
                    "type": "op",
                    "op_id": "mel_spectrogram",
                    "title": "梅尔频谱",
                    "params": {},
                    "position": {"x": 240, "y": 80},
                },
            ]
        )
        edges.append(
            {"id": "w-m", "source": "wav_src", "source_port": "out", "target": "mel", "target_port": "in"}
        )
    return {"nodes": nodes, "edges": edges}


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

    def test_requires_labels_tree_producer(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        g = _chain()
        g["nodes"] = [n for n in g["nodes"] if n["type"] != "label"]
        g["edges"] = [e for e in g["edges"] if e["target"] != "lab"]
        with self.assertRaises(ValueError) as ctx:
            validate_graph(g)
        self.assertIn("标签树", str(ctx.exception))

    def test_accepts_label_tree_input_without_ai_label(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        out = validate_graph(_fill_graph())
        self.assertFalse(any(n["type"] == "label" for n in out["nodes"]))
        self.assertTrue(any(n.get("op_id") == "label_tree_input" for n in out["nodes"]))

    def test_required_source_must_connect_downstream(self) -> None:
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
        self.assertIn("下游", str(ctx.exception))

    def test_required_wav_need_not_reach_ai_when_json_fills_tree(self) -> None:
        from hmi.platform.recipe_graph import validate_graph

        out = validate_graph(_fill_graph(extra_wav=True))
        self.assertFalse(any(n["type"] == "label" for n in out["nodes"]))
        self.assertEqual(sum(1 for n in out["nodes"] if n["type"] == "source"), 2)

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
        self.assertIn("标签树", str(ctx.exception))

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
        self.assertIn("标签树", str(ctx.exception))


class TestHydrateGraph(unittest.TestCase):
    def test_oms_cabin_chain_has_label(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph, validate_graph

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        self.assertTrue(rec.get("graph") and rec["graph"]["nodes"])
        g = hydrate_graph(rec)
        validate_graph(g)
        types = [n["type"] for n in g["nodes"]]
        self.assertIn("source", types)
        self.assertEqual(types.count("label"), 1)
        from hmi.platform.operators import CATALOG

        canvas_ops = {n["op_id"] for n in g["nodes"] if n["type"] in {"op", "label"}}
        self.assertTrue(canvas_ops <= set(CATALOG))
        self.assertEqual(
            {n["op_id"]: n["title"] for n in g["nodes"] if n["type"] == "op"},
            {
                "parse_bag": "ROSBAG 解析器",
                "extract_frames": "视频抽帧",
                "encode_preview": "视频编码器",
                "transcribe": "音频 ASR",
                "embed": "向量化器",
            },
        )
        label_node = next(n for n in g["nodes"] if n["type"] == "label")
        self.assertEqual(label_node["op_id"], "label")
        self.assertEqual(label_node["title"], "AI打标器")
        self.assertNotIn("mel_spectrogram", canvas_ops)
        self.assertNotIn("text_to_json", canvas_ops)
        self.assertNotIn("detect_bbox", canvas_ops)
        keys = [n["key"] for n in g["nodes"]]
        idx = {k: i for i, k in enumerate(keys)}
        for e in g["edges"]:
            self.assertLess(idx[e["source"]], idx[e["target"]])

    def test_hydrate_keeps_label_tree_input_without_injecting_ai(self) -> None:
        from hmi.platform.recipe_graph import hydrate_graph

        rec = {
            "id": "fill_only",
            "title": "t",
            "purpose": "p",
            "taxonomy_id": "oms",
            "overview_view": "custom",
            "require_any_kinds": [[".json"]],
            "slots": [{"id": "json_src", "kinds": [".json"], "cardinality_min": 1, "cardinality_max": 1}],
            "graph": _fill_graph(),
        }
        g = hydrate_graph(rec)
        self.assertFalse(any(n["type"] == "label" for n in g["nodes"]))
        self.assertTrue(any(n.get("op_id") == "label_tree_input" for n in g["nodes"]))

    def test_ivi_and_audio_seeds_use_catalog_keys(self) -> None:
        from hmi.platform.operators import CATALOG
        from hmi.platform.recipe import SEED_DATA_TYPE_IDS, seed_recipes
        from hmi.platform.recipe_graph import hydrate_graph, validate_graph

        seeded = seed_recipes()
        self.assertEqual(set(seeded), set(SEED_DATA_TYPE_IDS))
        expected_ops = {
            "ivi_ui_stub": {"extract_frames", "detect_bbox", "label"},
            "audio_array_spec": {
                "parse_head_dat",
                "stft_spectrogram",
                "mel_spectrogram",
                "third_octave",
                "spl_timeline",
                "label",
            },
            "audio_defect": {
                "json_extract",
                "mel_spectrogram",
                "third_octave",
                "spl_timeline",
                "label_tree_input",
            },
        }
        for dtype_id, want in expected_ops.items():
            rec = seeded[dtype_id]
            g = hydrate_graph(rec)
            validate_graph(g)
            keys = [n["key"] for n in g["nodes"]]
            self.assertFalse(any(k.startswith("prep-") for k in keys), keys)
            ops = {n["op_id"] for n in g["nodes"] if n["type"] in {"op", "label"}}
            self.assertEqual(ops, want)
            self.assertTrue(ops <= set(CATALOG))
            self.assertNotIn("transcribe", ops)
            titles = {n["op_id"]: n["title"] for n in g["nodes"] if n["type"] == "op"}
            for op_id, title in titles.items():
                self.assertEqual(title, CATALOG[op_id]["title"])
                self.assertNotEqual(title, f"prep-{op_id}")

    def test_existing_graph_not_rebuilt(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        rec["graph"]["nodes"][0]["title"] = "自定义源名"
        again = hydrate_graph(rec)
        self.assertEqual(again["nodes"][0]["title"], "自定义源名")

    def test_hydrate_without_graph_uses_catalog_keys(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["ivi_ui_stub"]))
        rec.pop("graph", None)
        g = hydrate_graph(rec)
        keys = [n["key"] for n in g["nodes"]]
        self.assertFalse(any(k.startswith("prep-") for k in keys), keys)
        self.assertNotIn("stage-embed", keys)
        self.assertIn("extract_frames", keys)
        self.assertIn("detect_bbox", keys)
        detect = next(n for n in g["nodes"] if n["op_id"] == "detect_bbox")
        self.assertEqual(detect["key"], "detect_bbox")
        self.assertEqual(detect["title"], "BBox 检测器")

    def test_legacy_prep_graph_remapped_to_catalog_keys(self) -> None:
        from hmi.platform.recipe_graph import hydrate_graph

        rec = {
            "slots": [
                {
                    "id": "ui_media",
                    "title": "IVI 画面",
                    "kinds": [".mp4"],
                    "cardinality_min": 1,
                    "cardinality_max": 1,
                    "required": True,
                }
            ],
            "preprocess": [
                {"op_id": "text_to_json", "produces": ["structured_json"]},
                {"op_id": "detect_bbox", "produces": ["bboxes_jsonl"]},
            ],
            "stages": {"label": {"enabled": True}, "embed": {"enabled": True}},
            "bbox": {"enabled": True, "detector": "opencv"},
            "graph": {
                "nodes": [
                    {
                        "key": "ui_media",
                        "type": "source",
                        "op_id": "source",
                        "title": "IVI 画面",
                        "params": {"kinds": [".mp4"], "required": True, "cardinality_min": 1, "cardinality_max": 1},
                        "position": {"x": 80, "y": 0},
                    },
                    {
                        "key": "prep-5-text_to_json",
                        "type": "op",
                        "op_id": "text_to_json",
                        "title": "prep-5-text_to_json",
                        "params": {},
                        "position": {"x": 80, "y": 96},
                    },
                    {
                        "key": "prep-6-detect_bbox",
                        "type": "op",
                        "op_id": "detect_bbox",
                        "title": "prep-6-detect_bbox",
                        "params": {},
                        "position": {"x": 80, "y": 192},
                    },
                    {
                        "key": "stage-embed",
                        "type": "op",
                        "op_id": "embed",
                        "title": "stage-embed",
                        "params": {},
                        "position": {"x": 80, "y": 288},
                    },
                    {
                        "key": "stage-label",
                        "type": "label",
                        "op_id": "label",
                        "title": "打标器",
                        "params": {},
                        "position": {"x": 80, "y": 384},
                    },
                ],
                "edges": [
                    {"id": "a", "source": "ui_media", "source_port": "out", "target": "prep-5-text_to_json", "target_port": "in"},
                    {"id": "b", "source": "prep-5-text_to_json", "source_port": "out", "target": "prep-6-detect_bbox", "target_port": "in"},
                    {"id": "c", "source": "prep-6-detect_bbox", "source_port": "out", "target": "stage-embed", "target_port": "in"},
                    {"id": "d", "source": "stage-embed", "source_port": "out", "target": "stage-label", "target_port": "in"},
                ],
            },
        }
        g = hydrate_graph(rec)
        keys = [n["key"] for n in g["nodes"]]
        self.assertFalse(any(k.startswith("prep-") for k in keys), keys)
        self.assertNotIn("stage-embed", keys)
        self.assertEqual(
            {n["op_id"]: n["key"] for n in g["nodes"] if n["type"] in {"op", "label"}},
            {"text_to_json": "text_to_json", "detect_bbox": "detect_bbox", "embed": "embed", "label": "stage-label"},
        )
        titles = {n["op_id"]: n["title"] for n in g["nodes"] if n["type"] == "op"}
        self.assertEqual(titles["text_to_json"], "文本结构化")
        self.assertEqual(titles["detect_bbox"], "BBox 检测器")
        self.assertEqual(titles["embed"], "向量化器")
        label = next(n for n in g["nodes"] if n["type"] == "label")
        self.assertEqual(label["title"], "AI打标器")


class TestProjectGraph(unittest.TestCase):
    def test_chain_projects_asr_into_preprocess(self) -> None:
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = validate_graph(_chain())
        proj = project_graph(g)
        self.assertEqual(proj["slots"][0]["id"], "src")
        self.assertTrue(proj["stages"]["label"]["enabled"])
        ops = [p["op_id"] for p in proj["preprocess"]]
        self.assertEqual(ops, ["transcribe"])

    def test_label_node_params_fill_stage_not_prefix(self) -> None:
        from hmi.platform.recipe_graph import project_graph, validate_graph

        g = _chain()
        for n in g["nodes"]:
            if n["type"] == "label":
                n["params"] = {
                    "model": "default",
                    "omni_label_prompt": {"system_role": "图节点 prompt"},
                    "temperature": 0.4,
                }
        proj = project_graph(validate_graph(g))
        self.assertEqual(proj["stages"]["label"]["omni_label_prompt"]["system_role"], "图节点 prompt")
        self.assertEqual(proj["stages"]["label"]["temperature"], 0.4)
        self.assertEqual([p["op_id"] for p in proj["preprocess"]], ["transcribe"])

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

    def test_fill_only_graph_does_not_enable_ai_label_stage(self) -> None:
        from hmi.platform.recipe_graph import project_graph, validate_graph

        proj = project_graph(validate_graph(_fill_graph()))
        self.assertFalse(proj["stages"]["label"]["enabled"])
        ops = [p["op_id"] for p in proj["preprocess"]]
        self.assertIn("json_extract", ops)
        self.assertIn("label_tree_input", ops)


class TestRecipeGraphIntegration(unittest.TestCase):
    def test_validate_recipe_projects_graph(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_graph import hydrate_graph

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["graph"] = hydrate_graph(rec)
        out = validate_recipe(rec)
        self.assertTrue(out["graph"]["nodes"])
        self.assertTrue(out["stages"]["label"]["enabled"])
        self.assertEqual(out["overview"]["detail"][0]["widget_id"], "video_timeline")

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


class TestGraphToStepsTopo(unittest.TestCase):
    def test_palette_appended_transcribe_compiles(self) -> None:
        from hmi.platform.recipe_graph import graph_to_steps, validate_graph
        from hmi.platform.recipe_pipeline import compile_steps

        g = {
            "nodes": [
                {
                    "key": "audio",
                    "type": "source",
                    "op_id": "source",
                    "title": "音频",
                    "params": {"kinds": [".wav"], "required": True},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "key": "embed",
                    "type": "op",
                    "op_id": "embed",
                    "title": "向量化器",
                    "params": {},
                    "position": {"x": 0, "y": 80},
                    "bindings": {
                        "in": {"kind": "upstream", "step_key": "op-transcribe-1", "port_id": "asr_jsonl"},
                    },
                },
                {
                    "key": "lab",
                    "type": "label",
                    "op_id": "label",
                    "title": "打标器",
                    "params": {},
                    "position": {"x": 0, "y": 160},
                },
                {
                    "key": "op-transcribe-1",
                    "type": "op",
                    "op_id": "transcribe",
                    "title": "音频 ASR",
                    "params": {},
                    "position": {"x": 0, "y": 240},
                },
            ],
            "edges": [
                {"id": "a", "source": "audio", "source_port": "out", "target": "op-transcribe-1", "target_port": "in"},
                {"id": "b", "source": "op-transcribe-1", "source_port": "out", "target": "embed", "target_port": "in"},
                {"id": "c", "source": "embed", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        }
        g = validate_graph(g)
        self.assertEqual(g["nodes"][1]["bindings"]["in"]["step_key"], "op-transcribe-1")
        steps = graph_to_steps(g)
        keys = [s["key"] for s in steps]
        self.assertLess(keys.index("op-transcribe-1"), keys.index("embed"))
        compile_steps(steps)

    def test_inspector_binding_without_edge_reorders(self) -> None:
        from hmi.platform.recipe_graph import graph_to_steps, validate_graph
        from hmi.platform.recipe_pipeline import compile_steps

        g = {
            "nodes": [
                {
                    "key": "src-1",
                    "type": "source",
                    "op_id": "source",
                    "title": "数据源",
                    "params": {"kinds": [".mp4"], "required": True},
                    "position": {"x": 0, "y": 0},
                },
                {
                    "key": "lab",
                    "type": "label",
                    "op_id": "label",
                    "title": "打标器",
                    "params": {},
                    "position": {"x": 0, "y": 80},
                    "bindings": {
                        "in": {"kind": "upstream", "step_key": "op-transcribe-1", "port_id": "asr_jsonl"},
                    },
                },
                {
                    "key": "op-transcribe-1",
                    "type": "op",
                    "op_id": "transcribe",
                    "title": "音频 ASR",
                    "params": {},
                    "position": {"x": 0, "y": 160},
                },
            ],
            "edges": [
                {"id": "e1", "source": "src-1", "source_port": "out", "target": "lab", "target_port": "in"},
            ],
        }
        g = validate_graph(g)
        steps = graph_to_steps(g)
        keys = [s["key"] for s in steps]
        self.assertLess(keys.index("op-transcribe-1"), keys.index("lab"))
        compile_steps(steps)

    def test_storage_order_would_reject_appended_transcribe(self) -> None:
        from hmi.platform.recipe_pipeline import assert_upward_bindings

        steps = [
            {"key": "audio", "card_kind": "source", "op_id": "source", "kinds": [".wav"], "bindings": {}},
            {
                "key": "embed",
                "op_id": "embed",
                "bindings": {"in": {"kind": "upstream", "step_key": "op-transcribe-1"}},
            },
            {"key": "op-transcribe-1", "op_id": "transcribe", "bindings": {}},
        ]
        with self.assertRaises(ValueError) as ctx:
            assert_upward_bindings(steps)
        self.assertIn("op-transcribe-1", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
