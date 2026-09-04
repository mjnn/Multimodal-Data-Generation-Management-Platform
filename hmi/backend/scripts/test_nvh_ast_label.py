"""PLAT-AUDIO-AST-LABEL: AudioSet-527 → NVH L6 mapping + HF remap + AST fill."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


def _synthetic_labels() -> dict:
    return {
        "nvh.clip.spl.leq_db_mean": 94.5,
        "nvh.clip.spl.leq_db_max": 96.0,
        "nvh.clip.spl.peak_db_max": 98.0,
        "nvh.clip.spl.level_class": "high",
        "nvh.clip.spec.tonality_index": 0.42,
        "nvh.ch.spl.leq_db": {"VL": 94.0, "VR": 95.0, "HL": 94.2, "HR": 94.8},
        "_meta": {
            "taxonomy_version_code": "audio_nvh-v2",
            "deriver_version": "nvh_deriver-v1",
            "label_source": "derive_nvh_labels",
        },
    }


class TestAudiosetNvhMap(unittest.TestCase):
    def test_speech_is_index_0(self) -> None:
        from hmi.local.nvh_ast.labels import AUDIOSET_NAMES

        self.assertEqual(len(AUDIOSET_NAMES), 527)
        self.assertEqual(AUDIOSET_NAMES[0], "Speech")
        self.assertEqual(AUDIOSET_NAMES[343], "Engine")

    def test_engine_maps_category_and_source(self) -> None:
        from hmi.local.nvh_ast.labels import AUDIOSET_NAMES, map_audioset_topk

        probs = [0.0] * 527
        probs[AUDIOSET_NAMES.index("Engine")] = 0.81
        probs[AUDIOSET_NAMES.index("Idling")] = 0.44
        probs[AUDIOSET_NAMES.index("Dog")] = 0.90  # unmapped, ignored for category
        out = map_audioset_topk(probs, k=5, min_score=0.05)
        self.assertEqual(out["noise_category"], "engine")
        self.assertIn("engine", out["noise_sources"])
        names = [row["name"] for row in out["topk"]]
        self.assertIn("Engine", names)
        self.assertTrue(out["mapped"])

    def test_unmapped_keeps_none_category(self) -> None:
        from hmi.local.nvh_ast.labels import map_audioset_topk

        probs = [0.0] * 527
        probs[74] = 0.99  # Dog
        out = map_audioset_topk(probs, k=5, min_score=0.05)
        self.assertIsNone(out["noise_category"])
        self.assertEqual(out["noise_sources"], [])
        self.assertFalse(out["mapped"])
        self.assertEqual(out["topk"][0]["name"], "Dog")


class TestHfRemap(unittest.TestCase):
    def test_concat_qkv_and_rename(self) -> None:
        import torch

        from hmi.local.nvh_ast.remap import remap_hf_to_ast

        q = torch.arange(64, dtype=torch.float32).reshape(8, 8)
        k = q + 1
        v = q + 2
        hf = {
            "audio_spectrogram_transformer.embeddings.cls_token": torch.ones(1, 1, 8),
            "audio_spectrogram_transformer.encoder.layer.0.attention.attention.query.weight": q,
            "audio_spectrogram_transformer.encoder.layer.0.attention.attention.key.weight": k,
            "audio_spectrogram_transformer.encoder.layer.0.attention.attention.value.weight": v,
            "audio_spectrogram_transformer.encoder.layer.0.attention.attention.query.bias": torch.zeros(8),
            "audio_spectrogram_transformer.encoder.layer.0.attention.attention.key.bias": torch.ones(8),
            "audio_spectrogram_transformer.encoder.layer.0.attention.attention.value.bias": torch.full((8,), 2.0),
            "classifier.dense.weight": torch.zeros(527, 8),
        }
        ast = remap_hf_to_ast(hf)
        self.assertIn("v.cls_token", ast)
        qkv = ast["v.blocks.0.attn.qkv.weight"]
        self.assertEqual(tuple(qkv.shape), (24, 8))
        self.assertTrue(torch.equal(qkv[:8], q))
        self.assertTrue(torch.equal(qkv[8:16], k))
        self.assertTrue(torch.equal(qkv[16:], v))
        qkv_b = ast["v.blocks.0.attn.qkv.bias"]
        self.assertEqual(tuple(qkv_b.shape), (24,))
        self.assertIn("mlp_head.1.weight", ast)
        self.assertNotIn("audio_spectrogram_transformer.embeddings.cls_token", ast)


class TestFillAstSemantic(unittest.TestCase):
    def test_ast_overrides_category_keeps_heuristic_grade(self) -> None:
        from hmi.local import nvh_ai_label
        from hmi.local.nvh_ast.labels import AUDIOSET_NAMES

        probs = [0.0] * 527
        probs[AUDIOSET_NAMES.index("Engine")] = 0.81
        orig = nvh_ai_label.infer_audioset_probs

        def _fake(_run_root, _labels):
            return probs

        nvh_ai_label.infer_audioset_probs = _fake  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(nvh_ai_label, "infer_audioset_probs", orig))

        base = _synthetic_labels()
        snap = deepcopy(base["nvh.clip.spl.leq_db_mean"])
        with tempfile.TemporaryDirectory() as td:
            out = nvh_ai_label.fill_nvh_semantic_labels(Path(td), base, model="nvh_sem_ast")
        self.assertEqual(out["nvh.sem.noise_category"], "engine")
        self.assertIn("engine", out["nvh.sem.noise_sources"])
        self.assertEqual(out["nvh.sem.quality_grade"], "C")  # heuristic from level_class=high
        self.assertEqual(out["nvh.clip.spl.leq_db_mean"], snap)
        self.assertIn("Engine=", out["nvh.sem.ai_hypothesis"])
        self.assertEqual(out["_meta"]["ai_model"], "nvh_sem_ast")
        self.assertEqual(out["_meta"]["ai_mode"], "ast")

    def test_missing_infer_falls_back_heuristic(self) -> None:
        from hmi.local import nvh_ai_label

        orig = nvh_ai_label.infer_audioset_probs

        def _fail(_run_root, _labels):
            return None

        nvh_ai_label.infer_audioset_probs = _fail  # type: ignore[method-assign]
        self.addCleanup(lambda: setattr(nvh_ai_label, "infer_audioset_probs", orig))
        with tempfile.TemporaryDirectory() as td:
            out = nvh_ai_label.fill_nvh_semantic_labels(
                Path(td), _synthetic_labels(), model="nvh_sem_ast"
            )
        self.assertEqual(out["_meta"]["ai_mode"], "heuristic_fallback")
        self.assertIn("nvh.sem.noise_category", out)
        self.assertEqual(out["_meta"]["ai_model"], "nvh_sem_ast")

    def test_recipe_uses_ast_model(self) -> None:
        from hmi.platform.recipe import seed_recipes

        rec = seed_recipes()["audio_array_spec"]
        self.assertEqual(rec["stages"]["label"]["model"], "nvh_sem_ast")


if __name__ == "__main__":
    unittest.main()
