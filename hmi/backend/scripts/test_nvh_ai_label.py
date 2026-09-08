"""PLAT-AUDIO-AI-LABEL: L6 semantic fill without clobbering objective NVH leaves."""

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
        "nvh.band.tonal_components": {"_ref": "audio_spec/derived/tonal_components.json"},
        "_meta": {
            "taxonomy_version_code": "audio_nvh-v2",
            "deriver_version": "nvh_deriver-v1",
            "label_source": "derive_nvh_labels",
        },
    }


class TestNvhAiLabelMerge(unittest.TestCase):
    def test_merge_fills_sem_keeps_objective(self) -> None:
        from hmi.local.nvh_ai_label import merge_nvh_semantic_labels

        base = _synthetic_labels()
        before_clip = deepcopy(base["nvh.clip.spl.leq_db_mean"])
        before_ch = deepcopy(base["nvh.ch.spl.leq_db"])
        sem = {
            "nvh.sem.noise_category": "tonal",
            "nvh.sem.quality_grade": "C",
            "nvh.clip.spl.leq_db_mean": 1.0,  # must be ignored
            "nvh.evil": "nope",
        }
        out = merge_nvh_semantic_labels(base, sem)
        self.assertEqual(out["nvh.sem.noise_category"], "tonal")
        self.assertEqual(out["nvh.sem.quality_grade"], "C")
        self.assertEqual(out["nvh.clip.spl.leq_db_mean"], before_clip)
        self.assertEqual(out["nvh.ch.spl.leq_db"], before_ch)
        self.assertNotIn("nvh.evil", out)
        self.assertIn("ai_label_version", out["_meta"])

    def test_heuristic_writes_sem_keys(self) -> None:
        from hmi.local.nvh_ai_label import fill_nvh_semantic_labels

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            der = root / "audio_spec" / "derived"
            der.mkdir(parents=True)
            (der / "tonal_components.json").write_text(
                json.dumps([{"prominence_db": 8.0, "fc_hz": 1000.0}]),
                encoding="utf-8",
            )
            base = _synthetic_labels()
            snap = {k: deepcopy(v) for k, v in base.items() if k.startswith("nvh.clip.") or k.startswith("nvh.ch.")}
            out = fill_nvh_semantic_labels(root, base, model="nvh_sem_heuristic")
            self.assertEqual(out["nvh.sem.noise_category"], "tonal")
            self.assertIn(out["nvh.sem.quality_grade"], {"A", "B", "C", "D"})
            self.assertIn("nvh.sem.ai_hypothesis", out)
            for k, v in snap.items():
                self.assertEqual(out[k], v, msg=f"clobbered {k}")
            self.assertEqual(out["_meta"]["ai_mode"], "heuristic")
            self.assertEqual(out["_meta"]["taxonomy_version_code"], "audio_nvh-v2")

    def test_heuristic_appends_reference_constraints(self) -> None:
        from hmi.local.nvh_ai_label import fill_nvh_semantic_labels

        with tempfile.TemporaryDirectory() as td:
            out = fill_nvh_semantic_labels(
                Path(td),
                _synthetic_labels(),
                model="nvh_sem_heuristic",
                reference_constraints="人工备注：只看客观 SPL",
            )
            self.assertIn("人工备注：只看客观 SPL", out.get("nvh.sem.annotator_notes") or "")
            self.assertEqual(out["_meta"]["ai_mode"], "heuristic")

    def test_recipe_label_enabled(self) -> None:
        from hmi.platform.recipe import seed_recipes

        rec = seed_recipes()["audio_array_spec"]
        self.assertTrue(rec["stages"]["label"]["enabled"])
        self.assertEqual(rec["stages"]["label"]["model"], "nvh_sem_ast")

    def test_resolve_draft_taxonomy_no_publish(self) -> None:
        import hmi.app_db as app_db
        from hmi.local.nvh_ai_label import resolve_audio_nvh_taxonomy_version_id
        from hmi.platform.store import ensure_platform_schema
        from hmi.taxonomy_db import get_published_version, get_version_by_code

        tmp = Path(tempfile.mkdtemp()) / "app.db"
        orig = app_db.APP_DB_PATH
        app_db.APP_DB_PATH = tmp
        self.addCleanup(lambda: setattr(app_db, "APP_DB_PATH", orig))
        ensure_platform_schema()
        v2 = get_version_by_code("audio_nvh-v2")
        self.assertIsNotNone(v2)
        assert v2 is not None
        self.assertEqual(v2["status"], "draft")
        vid = resolve_audio_nvh_taxonomy_version_id()
        self.assertEqual(vid, v2["id"])
        pub = get_published_version()
        if pub is not None:
            self.assertNotEqual(pub["version_code"], "audio_nvh-v2")

    def test_end_to_end_derive_then_ai(self) -> None:
        from hmi.local.audio_spectrum import analyze_pcm_pa
        from hmi.local.nvh_ai_label import fill_nvh_semantic_labels
        from hmi.local.nvh_deriver import derive_nvh_labels

        fs = 8000.0
        t = np.arange(0, 1.0, 1.0 / fs)
        # loud-ish tone + noise
        tone = 0.5 * np.sin(2 * np.pi * 1000 * t)
        noise = 0.05 * np.random.default_rng(0).standard_normal(t.shape[0])
        pcm = np.column_stack([tone + noise] * 4).astype(np.float64)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = ["VL", "VR", "HL", "HR"]
            meta = {
                "format": "head_acoustics_hdf_v4",
                "fs_hz": fs,
                "duration_s": 1.0,
                "n_channels": 4,
                "unit": "Pa",
                "channels": [{"name": n, "map_factor": 1.0} for n in names],
            }
            (root / "head_meta.json").write_text(json.dumps(meta), encoding="utf-8")
            np.save(root / "pcm_pa.npy", pcm)
            analyze_pcm_pa(pcm, fs, names, root / "audio_spec")
            derived = derive_nvh_labels(root)
            self.assertNotIn("nvh.sem.noise_category", derived)
            leq_before = derived["nvh.clip.spl.leq_db_mean"]
            filled = fill_nvh_semantic_labels(root, derived, model="nvh_sem_heuristic")
            self.assertIn("nvh.sem.noise_category", filled)
            self.assertEqual(filled["nvh.clip.spl.leq_db_mean"], leq_before)
            for prefix in ("nvh.clip.", "nvh.ch."):
                for k, v in derived.items():
                    if k.startswith(prefix):
                        self.assertEqual(filled[k], v, msg=k)


if __name__ == "__main__":
    unittest.main()
