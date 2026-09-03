"""UI-DTYPE-EDITOR: custom recipe upsert via store validate path."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestDataTypeEditorUpsert(unittest.TestCase):
    def setUp(self) -> None:
        import hmi.app_db as app_db

        self._orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = Path(tempfile.mkdtemp()) / "app.db"
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", self._orig))
        app_db.ensure_schema()

    def test_upsert_custom_draft_with_slots_and_stages(self) -> None:
        from hmi.platform.store import get_data_type, upsert_data_type

        recipe = {
            "id": "custom_audio_demo",
            "title": "自定义音频演示",
            "purpose": "编辑器创建的 draft 配方",
            "owner": "qa",
            "taxonomy_id": "audio_nvh",
            "overview_view": "audio_nvh_timeline",
            "status": "draft",
            "require_any_kinds": [["audio"]],
            "slots": [
                {
                    "id": "audio_primary",
                    "kinds": ["audio"],
                    "cardinality_min": 1,
                    "cardinality_max": 1,
                    "role": "primary",
                    "required": True,
                }
            ],
            "preprocess": [
                {
                    "op_id": "mel_spectrogram",
                    "when_kind": "audio",
                    "required": True,
                    "inputs": ["audio_primary"],
                    "produces": ["mel_matrix"],
                }
            ],
            "products": [{"id": "mel_matrix", "from_op": "mel_spectrogram", "reusable": True}],
            "stages": {"label": {"enabled": True, "model": "nvh_sem_heuristic"}, "embed": {"enabled": False}},
            "bbox": {"enabled": False, "detector": "opencv", "yolo_classes": ""},
        }
        saved = upsert_data_type(recipe)
        self.assertEqual(saved["id"], "custom_audio_demo")
        self.assertEqual(saved["status"], "draft")
        self.assertFalse(saved["stages"]["embed"]["enabled"])
        self.assertTrue(saved["stages"]["label"]["enabled"])
        loaded = get_data_type("custom_audio_demo")
        assert loaded is not None
        self.assertEqual(loaded["slots"][0]["id"], "audio_primary")
        self.assertEqual(loaded["preprocess"][0]["op_id"], "mel_spectrogram")

    def test_reject_unknown_operator(self) -> None:
        from hmi.platform.store import upsert_data_type

        bad = {
            "id": "bad_op",
            "title": "x",
            "purpose": "y",
            "taxonomy_id": "oms",
            "overview_view": "cabin_timeline",
            "status": "draft",
            "require_any_kinds": [["video"]],
            "slots": [{"id": "v", "kinds": ["video"], "cardinality_min": 1, "cardinality_max": 1}],
            "preprocess": [{"op_id": "not_a_real_op", "when_kind": "video"}],
            "products": [],
            "stages": {"label": {"enabled": False}, "embed": {"enabled": False}},
            "bbox": {"enabled": False, "detector": "opencv"},
        }
        with self.assertRaises(ValueError):
            upsert_data_type(bad)

    def test_reject_stage_op_in_preprocess(self) -> None:
        from hmi.platform.store import upsert_data_type

        bad = {
            "id": "bad_stage",
            "title": "x",
            "purpose": "y",
            "taxonomy_id": "oms",
            "overview_view": "cabin_timeline",
            "status": "draft",
            "require_any_kinds": [["video"]],
            "slots": [{"id": "v", "kinds": ["video"], "cardinality_min": 1, "cardinality_max": 1}],
            "preprocess": [{"op_id": "label", "when_kind": "video"}],
            "products": [],
            "stages": {"label": {"enabled": True}, "embed": {"enabled": False}},
            "bbox": {"enabled": False, "detector": "opencv"},
        }
        with self.assertRaises(ValueError) as ctx:
            upsert_data_type(bad)
        self.assertIn("cannot appear in preprocess", str(ctx.exception))

    def test_reject_unknown_preprocess_param(self) -> None:
        from hmi.platform.store import upsert_data_type

        bad = {
            "id": "bad_param",
            "title": "x",
            "purpose": "y",
            "taxonomy_id": "oms",
            "overview_view": "cabin_timeline",
            "status": "draft",
            "require_any_kinds": [["video"]],
            "slots": [{"id": "v", "kinds": ["video"], "cardinality_min": 1, "cardinality_max": 1}],
            "preprocess": [
                {
                    "op_id": "extract_frames",
                    "when_kind": "video",
                    "params": {"not_a_real_key": 1},
                }
            ],
            "products": [],
            "stages": {"label": {"enabled": False}, "embed": {"enabled": False}},
            "bbox": {"enabled": False, "detector": "opencv"},
        }
        with self.assertRaises(ValueError) as ctx:
            upsert_data_type(bad)
        self.assertIn("unknown key", str(ctx.exception))

    def test_accept_preprocess_params(self) -> None:
        from hmi.platform.store import get_data_type, upsert_data_type

        recipe = {
            "id": "ok_params",
            "title": "x",
            "purpose": "y",
            "taxonomy_id": "oms",
            "overview_view": "cabin_timeline",
            "status": "draft",
            "require_any_kinds": [["video"]],
            "slots": [{"id": "v", "kinds": ["video"], "cardinality_min": 1, "cardinality_max": 1}],
            "preprocess": [
                {
                    "op_id": "extract_frames",
                    "when_kind": "video",
                    "produces": ["frames"],
                    "params": {"sample_fps": 2},
                }
            ],
            "products": [{"id": "frames", "from_op": "extract_frames"}],
            "stages": {"label": {"enabled": False}, "embed": {"enabled": False}},
            "bbox": {"enabled": False, "detector": "opencv"},
        }
        saved = upsert_data_type(recipe)
        loaded = get_data_type("ok_params")
        assert loaded is not None
        self.assertEqual(saved["preprocess"][0]["params"]["sample_fps"], 2)
        self.assertEqual(loaded["preprocess"][0]["params"]["sample_fps"], 2)

    def test_slot_title_and_output_labels_roundtrip(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        rec = dict(SEED_RECIPES["oms_cabin"])
        rec = validate_recipe(rec)
        rec["slots"][0]["title"] = "舱内 bag"
        parse = next(s for s in rec["preprocess"] if s["op_id"] == "parse_bag")
        parse["produces"] = ["frames", ".wav", ".json"]
        parse["output_labels"] = {"frames": "舱内连续帧"}
        out = validate_recipe(rec)
        self.assertEqual(out["slots"][0]["title"], "舱内 bag")
        parse_out = next(s for s in out["preprocess"] if s["op_id"] == "parse_bag")
        self.assertEqual(parse_out["output_labels"]["frames"], "舱内连续帧")

    def test_output_labels_unknown_port_rejected(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        parse = next(s for s in rec["preprocess"] if s["op_id"] == "parse_bag")
        parse["produces"] = ["frames", ".wav", ".json"]
        parse["output_labels"] = {"not_a_port": "x"}
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(rec)
        self.assertIn("output_labels", str(ctx.exception))

    def test_duplicate_slot_title_rejected(self) -> None:
        from hmi.platform.recipe import validate_recipe

        recipe = {
            "id": "dup_title",
            "title": "x",
            "purpose": "y",
            "taxonomy_id": "oms",
            "overview_view": "cabin_timeline",
            "status": "draft",
            "require_any_kinds": [["video"], ["audio"]],
            "slots": [
                {
                    "id": "a",
                    "title": "Primary",
                    "kinds": ["video"],
                    "cardinality_min": 1,
                    "cardinality_max": 1,
                },
                {
                    "id": "b",
                    "title": "primary",
                    "kinds": ["audio"],
                    "cardinality_min": 1,
                    "cardinality_max": 1,
                },
            ],
            "preprocess": [],
            "products": [],
            "stages": {"label": {"enabled": False}, "embed": {"enabled": False}},
            "bbox": {"enabled": False, "detector": "opencv"},
        }
        with self.assertRaises(ValueError) as ctx:
            validate_recipe(recipe)
        self.assertIn("duplicate slot title", str(ctx.exception))


class TestRecipePipelineCompile(unittest.TestCase):
    def test_hydrate_compile_oms_cabin_stages(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, hydrate_recipe_to_steps

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        steps = hydrate_recipe_to_steps(rec)
        op_ids = [s["op_id"] for s in steps]
        self.assertIn("parse_bag", op_ids)
        self.assertIn("label", op_ids)
        self.assertIn("embed", op_ids)
        compiled = compile_steps(steps, rec["slots"])
        self.assertTrue(compiled["stages"]["label"]["enabled"])
        self.assertTrue(compiled["stages"]["embed"]["enabled"])
        self.assertFalse(compiled["bbox"]["enabled"])
        prep_ids = [s["op_id"] for s in compiled["preprocess"]]
        self.assertEqual(prep_ids, [s["op_id"] for s in rec["preprocess"]])
        validate_recipe({**rec, **compiled})

    def test_compile_label_and_mel_cards(self) -> None:
        from hmi.platform.recipe import validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, new_step_from_op

        slots = [
            {
                "id": "audio_primary",
                "kinds": ["audio"],
                "cardinality_min": 1,
                "cardinality_max": 1,
                "role": "primary",
                "required": True,
            }
        ]
        mel = new_step_from_op("mel_spectrogram", key="prep-mel", slots=slots, upstream=[])
        label = new_step_from_op("label", key="stage-label", slots=slots, upstream=[mel])
        label["params"] = {"model": "nvh_sem_ast"}
        compiled = compile_steps([mel, label], slots)
        self.assertEqual(compiled["preprocess"][0]["op_id"], "mel_spectrogram")
        self.assertEqual(compiled["preprocess"][0]["inputs"], ["audio_primary"])
        self.assertTrue(compiled["stages"]["label"]["enabled"])
        self.assertEqual(compiled["stages"]["label"]["model"], "nvh_sem_ast")
        self.assertFalse(compiled["stages"]["embed"]["enabled"])
        recipe = {
            "id": "orch_audio",
            "title": "编排音频",
            "purpose": "卡编译",
            "owner": "qa",
            "taxonomy_id": "audio_nvh",
            "overview_view": "audio_nvh_timeline",
            "status": "draft",
            "require_any_kinds": [["audio"]],
            "slots": slots,
            **compiled,
        }
        norm = validate_recipe(recipe)
        self.assertEqual(norm["preprocess"][0]["op_id"], "mel_spectrogram")

    def test_stft_not_compatible_with_video_slot(self) -> None:
        from hmi.platform.recipe_pipeline import binding_options

        slots = [{"id": "primary", "kinds": ["video"]}]
        opts = binding_options(needed_types=["audio"], slots=slots, upstream=[])
        self.assertEqual(opts, [])

    def test_catalog_includes_stage_ops(self) -> None:
        from hmi.platform.operators import STAGE_OPERATORS, list_operators

        ids = {op["op_id"] for op in list_operators()}
        self.assertIn("label", ids)
        self.assertIn("embed", ids)
        self.assertIn("parse_bag", ids)
        self.assertEqual(STAGE_OPERATORS["label"]["role"], "stage")

    def test_parse_bag_emits_selected_modalities(self) -> None:
        from hmi.platform.recipe import validate_recipe
        from hmi.platform.recipe_pipeline import binding_options, compile_steps, new_step_from_op

        slots = [
            {
                "id": "bag",
                "kinds": ["rosbag"],
                "cardinality_min": 1,
                "cardinality_max": 1,
                "required": True,
            }
        ]
        parse = new_step_from_op("parse_bag", key="prep-parse", slots=slots, upstream=[])
        parse["params"] = {"emit_modalities": ["audio"]}
        parse["produces"] = ["audio"]
        compiled = compile_steps([parse], slots)
        self.assertEqual(compiled["preprocess"][0]["produces"], [".wav"])
        self.assertEqual(compiled["preprocess"][0]["params"]["emit_modalities"], [".wav"])
        self.assertEqual(compiled["products"][0]["id"], ".wav")
        validate_recipe(
            {
                "id": "bag_audio_only",
                "title": "x",
                "purpose": "y",
                "taxonomy_id": "oms",
                "overview_view": "cabin_timeline",
                "status": "draft",
                "require_any_kinds": [["rosbag"]],
                "slots": slots,
                **compiled,
            }
        )
        audio_opts = binding_options(needed_types=["audio"], slots=slots, upstream=[parse])
        video_opts = binding_options(needed_types=["video"], slots=slots, upstream=[parse])
        self.assertTrue(any(o.get("port_id") == ".wav" for o in audio_opts if o.get("kind") == "upstream"))
        self.assertFalse(any(o.get("kind") == "upstream" for o in video_opts))

        asr = new_step_from_op("transcribe", key="prep-asr", slots=slots, upstream=[parse])
        asr["bindings"] = {
            "in": {"kind": "upstream", "step_key": parse["key"], "port_id": ".wav"}
        }
        compiled2 = compile_steps([parse, asr], slots)
        trans = next(p for p in compiled2["preprocess"] if p["op_id"] == "transcribe")
        self.assertEqual(trans["inputs"], [".wav"])

    def test_hydrate_legacy_parse_bag_multimodal(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import hydrate_recipe_to_steps

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        steps = hydrate_recipe_to_steps(rec)
        parse = next(s for s in steps if s["op_id"] == "parse_bag")
        self.assertEqual(parse["produces"], ["frames", ".wav", ".json"])
        self.assertEqual(parse["params"]["emit_modalities"], ["frames", ".wav", ".json"])
        self.assertNotIn("frames_audio_topics", parse["produces"])
        self.assertNotIn(".mp4", parse["produces"])

    def test_encode_preview_does_not_take_video(self) -> None:
        from hmi.platform.operators import CATALOG
        from hmi.platform.recipe_pipeline import binding_options, new_step_from_op

        op = CATALOG["encode_preview"]
        self.assertNotIn("video", op["input_kinds"])
        self.assertNotIn(".mp4", op["input_kinds"])
        in_types = (op["input_ports"][0]["types"] if op.get("input_ports") else [])
        self.assertNotIn("video", in_types)
        self.assertNotIn(".mp4", in_types)
        self.assertIn("frames", in_types)

        slots = [
            {"id": "vid", "kinds": ["video"]},
            {"id": "img", "kinds": ["image"]},
        ]
        parse = new_step_from_op("parse_bag", key="prep-parse", slots=[], upstream=[])
        parse["params"] = {"emit_modalities": ["video", "audio", "text"]}
        parse["produces"] = ["video", "audio", "text"]
        extract = new_step_from_op("extract_frames", key="prep-frames", slots=slots, upstream=[parse])
        opts = binding_options(
            needed_types=["frames", "image"],
            slots=slots,
            upstream=[parse, extract],
        )
        self.assertFalse(any(o.get("port_id") == "video" for o in opts))
        self.assertFalse(any(o.get("port_id") == ".mp4" for o in opts))
        self.assertFalse(any(o.get("kind") == "slot" and o.get("slot_id") == "vid" for o in opts))
        self.assertTrue(any(o.get("kind") == "slot" and o.get("slot_id") == "img" for o in opts))
        self.assertTrue(
            any(
                o.get("kind") == "upstream"
                and o.get("step_key") == parse["key"]
                and o.get("port_id") == "frames"
                for o in opts
            )
        )
        self.assertTrue(
            any(o.get("kind") == "upstream" and o.get("port_id") == "frames" for o in opts)
        )

    def test_hydrate_oms_cabin_starts_with_source_cards(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, hydrate_recipe_to_steps, slots_from_steps

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        steps = hydrate_recipe_to_steps(rec)
        sources = [s for s in steps if s.get("card_kind") == "source"]
        self.assertEqual([s["key"] for s in sources], ["rosbag", "video", "image", "audio"])
        self.assertTrue(any(s.get("op_id") == "parse_bag" for s in steps))
        self.assertLess(steps.index(sources[0]), next(i for i, s in enumerate(steps) if s.get("op_id") == "parse_bag"))

        compiled = compile_steps(steps)
        self.assertEqual([s["id"] for s in compiled["slots"]], ["rosbag", "video", "image", "audio"])
        self.assertEqual(slots_from_steps(steps)[0]["id"], "rosbag")

    def test_binding_to_later_source_rejected(self) -> None:
        from hmi.platform.recipe_pipeline import assert_upward_bindings, new_source_card, new_step_from_op

        src = new_source_card(key="bag", title="bag", kinds=[".bag"])
        parse = new_step_from_op("parse_bag", key="prep-parse", slots=[], upstream=[])
        parse["bindings"] = {"in": {"kind": "slot", "slot_id": "bag"}}
        with self.assertRaises(ValueError):
            assert_upward_bindings([parse, src])
        assert_upward_bindings([src, parse])  # ok

    def test_hydrate_output_labels_compile_back(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, hydrate_recipe_to_steps, new_source_card

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        parse = next(s for s in rec["preprocess"] if s["op_id"] == "parse_bag")
        parse["produces"] = ["frames", ".wav", ".json"]
        parse["output_labels"] = {"frames": "cabin frames"}
        rec = validate_recipe(rec)
        steps = hydrate_recipe_to_steps(rec)
        parse_card = next(s for s in steps if s.get("op_id") == "parse_bag")
        self.assertEqual(parse_card.get("output_labels"), {"frames": "cabin frames"})

        compiled = compile_steps(steps)
        parse_out = next(s for s in compiled["preprocess"] if s["op_id"] == "parse_bag")
        self.assertEqual(parse_out.get("output_labels"), {"frames": "cabin frames"})
        self.assertNotIn("source", [s["op_id"] for s in compiled["preprocess"]])

        required_src = new_source_card(key="audio_primary", title="mic", kinds=[".wav"], required=True)
        compiled_req = compile_steps([required_src])
        self.assertEqual(compiled_req["require_any_kinds"], [[".wav"]])
        self.assertEqual(compiled_req["slots"][0]["id"], "audio_primary")
        self.assertEqual(compiled_req["slots"][0]["role"], "input")

    def test_catalog_port_multiple_matches_sdk(self) -> None:
        from hmi.platform.operators import CATALOG

        def in_multiple(op_id: str) -> bool:
            ports = CATALOG[op_id].get("input_ports") or []
            return bool(ports and ports[0].get("multiple"))

        self.assertTrue(in_multiple("label"))
        self.assertTrue(in_multiple("embed"))
        self.assertTrue(in_multiple("extract_frames"))
        self.assertTrue(in_multiple("detect_bbox"))
        self.assertTrue(in_multiple("mel_spectrogram"))
        self.assertTrue(in_multiple("stft_spectrogram"))
        self.assertTrue(in_multiple("third_octave"))
        self.assertTrue(in_multiple("spl_timeline"))
        self.assertFalse(in_multiple("parse_bag"))
        self.assertFalse(in_multiple("encode_preview"))
        self.assertFalse(in_multiple("transcribe"))
        self.assertFalse(in_multiple("parse_head_dat"))
        self.assertFalse(in_multiple("text_to_json"))
        self.assertEqual(len(CATALOG["parse_bag"]["output_ports"]), 3)

    def test_label_compiles_multi_bindings_to_stage_inputs(self) -> None:
        from hmi.platform.recipe import validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, new_source_card, new_step_from_op

        bag = new_source_card(key="rosbag", title="bag", kinds=[".bag"])
        parse = new_step_from_op("parse_bag", key="prep-parse", slots=[], upstream=[bag])
        parse["bindings"] = {"in": {"kind": "slot", "slot_id": "rosbag"}}
        asr = new_step_from_op("transcribe", key="prep-asr", slots=[], upstream=[bag, parse])
        asr["bindings"] = {"in": {"kind": "upstream", "step_key": "prep-parse", "port_id": ".wav"}}
        label = new_step_from_op("label", key="stage-label", slots=[], upstream=[bag, parse, asr])
        binds = label["bindings"]["in"]
        self.assertIsInstance(binds, list)
        self.assertGreaterEqual(len(binds), 2)
        compiled = compile_steps([bag, parse, asr, label])
        ins = compiled["stages"]["label"]["inputs"]
        self.assertIn("frames", ins)
        self.assertIn(".wav", ins)
        self.assertIn("asr_jsonl", ins)
        recipe = {
            "id": "multi_label",
            "title": "x",
            "purpose": "y",
            "taxonomy_id": "oms",
            "overview_view": "cabin_timeline",
            "status": "draft",
            "require_any_kinds": [[".bag"]],
            **compiled,
        }
        norm = validate_recipe(recipe)
        self.assertEqual(norm["stages"]["label"]["inputs"], ins)

    def test_hydrate_legacy_label_autofills_compatible(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import hydrate_recipe_to_steps

        rec = validate_recipe(SEED_RECIPES["oms_cabin"])
        self.assertNotIn("inputs", rec["stages"]["label"])
        steps = hydrate_recipe_to_steps(rec)
        label = next(s for s in steps if s.get("op_id") == "label")
        binds = label["bindings"]["in"]
        self.assertIsInstance(binds, list)
        ports = {b.get("port_id") for b in binds if b.get("kind") == "upstream"}
        self.assertIn("frames", ports)
        self.assertIn(".wav", ports)
        self.assertIn("asr_jsonl", ports)

    def test_hydrate_respects_stored_label_inputs(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import hydrate_recipe_to_steps

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        rec["stages"] = dict(rec["stages"])
        rec["stages"]["label"] = {**rec["stages"]["label"], "inputs": ["asr_jsonl"]}
        rec = validate_recipe(rec)
        label = next(s for s in hydrate_recipe_to_steps(rec) if s.get("op_id") == "label")
        binds = label["bindings"]["in"]
        self.assertEqual(len(binds), 1)
        self.assertEqual(binds[0].get("port_id"), "asr_jsonl")

    def test_compile_seed_require_any_kinds_preflight_singleton(self) -> None:
        from hmi.platform.file_kinds import AUDIO_EXTS, IMAGE_EXTS, VIDEO_EXTS, singleton_kind_groups
        from hmi.platform.preflight import preflight
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, hydrate_recipe_to_steps

        audio = validate_recipe(SEED_RECIPES["audio_array_spec"])
        audio_compiled = compile_steps(hydrate_recipe_to_steps(audio))
        self.assertEqual(
            audio_compiled["require_any_kinds"],
            singleton_kind_groups(*sorted(AUDIO_EXTS)),
        )
        audio_recipe = {**audio, **audio_compiled}
        self.assertTrue(preflight(audio_recipe, [".wav"])["ok"])

        ivi = validate_recipe(SEED_RECIPES["ivi_ui_stub"])
        ivi_compiled = compile_steps(hydrate_recipe_to_steps(ivi))
        self.assertEqual(
            ivi_compiled["require_any_kinds"],
            singleton_kind_groups(*sorted(VIDEO_EXTS | IMAGE_EXTS)),
        )
        ivi_recipe = {**ivi, **ivi_compiled}
        self.assertTrue(preflight(ivi_recipe, [".mp4"])["ok"])

    def test_compile_strips_output_labels_not_in_produces(self) -> None:
        from hmi.platform.recipe import SEED_RECIPES, validate_recipe
        from hmi.platform.recipe_pipeline import compile_steps, hydrate_recipe_to_steps

        rec = dict(validate_recipe(SEED_RECIPES["oms_cabin"]))
        parse = next(s for s in rec["preprocess"] if s["op_id"] == "parse_bag")
        parse["produces"] = ["frames", ".wav", ".json"]
        parse["params"] = {"emit_modalities": ["frames", ".wav", ".json"]}
        parse["output_labels"] = {"frames": "cabin frames", ".wav": "mic"}
        rec = validate_recipe(rec)
        steps = hydrate_recipe_to_steps(rec)
        parse_card = next(s for s in steps if s.get("op_id") == "parse_bag")
        parse_card["produces"] = [".wav", ".json"]
        parse_card["params"] = {**(parse_card.get("params") or {}), "emit_modalities": [".wav", ".json"]}
        compiled = compile_steps(steps)
        parse_out = next(s for s in compiled["preprocess"] if s["op_id"] == "parse_bag")
        self.assertEqual(parse_out.get("output_labels"), {".wav": "mic"})
        self.assertNotIn("frames", parse_out.get("output_labels") or {})
        recipe = {
            "id": "strip_labels",
            "title": "x",
            "purpose": "y",
            "taxonomy_id": "oms",
            "overview_view": "cabin_timeline",
            "status": "draft",
            "require_any_kinds": [[".bag"]],
            **compiled,
        }
        norm = validate_recipe(recipe)
        parse_norm = next(s for s in norm["preprocess"] if s["op_id"] == "parse_bag")
        self.assertNotIn("frames", parse_norm.get("output_labels") or {})

    def test_upward_rejects_list_binding_to_later_card(self) -> None:
        from hmi.platform.recipe_pipeline import assert_upward_bindings, new_source_card, new_step_from_op

        src = new_source_card(key="bag", title="bag", kinds=[".bag"])
        parse = new_step_from_op("parse_bag", key="prep-parse", slots=[], upstream=[])
        label = new_step_from_op("label", key="stage-label", slots=[], upstream=[])
        label["bindings"] = {
            "in": [{"kind": "upstream", "step_key": "prep-parse", "port_id": "frames"}]
        }
        with self.assertRaises(ValueError):
            assert_upward_bindings([src, label, parse])
        assert_upward_bindings([src, parse, label])


if __name__ == "__main__":
    unittest.main()
