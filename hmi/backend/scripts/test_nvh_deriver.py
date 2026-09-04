"""OP-DERIVE-NVH: derive_nvh_labels from L2 audio_spec products."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))

SAMPLE_DAT = Path(r"C:\Users\svw\Downloads\CBK1-4266 saixin steelsuokou-boardline.dat")

HUMAN_OR_SKIP = {
    "nvh.meta.record_context",
    "nvh.band.masking_band",
    "nvh.sem.noise_category",
    "nvh.sem.noise_sources",
    "nvh.sem.tonal_annoyance",
    "nvh.sem.broadband_annoyance",
    "nvh.sem.quality_grade",
    "nvh.sem.spec_compliance",
    "nvh.sem.spec_limit_db",
    "nvh.sem.test_point",
    "nvh.sem.annotator_notes",
    "nvh.sem.ai_hypothesis",
}


def _synth_run(root: Path, *, leq_target_db: float = 94.5, duration_s: float = 1.0, fs: float = 44100.0) -> None:
    from hmi.local.audio_spectrum import analyze_pcm_pa

    pref = 2e-5
    rms = pref * (10 ** (leq_target_db / 20.0))
    n = int(fs * duration_s)
    t = np.arange(n, dtype=np.float64) / fs
    # four near-equal channels with slight imbalance
    scales = [1.0, 0.98, 1.02, 0.99]
    cols = []
    for s in scales:
        cols.append((rms * s * np.sqrt(2.0) * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32))
    pcm = np.stack(cols, axis=1)
    names = ["VL", "VR", "HL", "HR"]
    meta = {
        "format": "head_acoustics_hdf_v4",
        "fs_hz": fs,
        "duration_s": duration_s,
        "n_channels": 4,
        "unit": "Pa",
        "channels": [{"name": n, "map_factor": 1.0} for n in names],
    }
    (root / "head_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    np.save(root / "pcm_pa.npy", pcm)
    analyze_pcm_pa(pcm, fs, names, root / "audio_spec")


class TestDeriveNvhLabels(unittest.TestCase):
    def test_synthetic_auto_semi_not_human(self) -> None:
        from hmi.local.nvh_deriver import DERIVER_VERSION, derive_nvh_labels
        from hmi.platform.audio_nvh_v2 import VERSION_CODE, build_labels

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _synth_run(root, leq_target_db=94.5)
            labels = derive_nvh_labels(root)

        self.assertIn("_meta", labels)
        self.assertEqual(labels["_meta"]["taxonomy_version_code"], VERSION_CODE)
        self.assertEqual(labels["_meta"]["deriver_version"], DERIVER_VERSION)
        self.assertIn("derived_at", labels["_meta"])

        leq = float(labels["nvh.clip.spl.leq_db_mean"])
        self.assertGreater(leq, 90.0)
        self.assertLess(leq, 98.0)
        self.assertEqual(labels["nvh.clip.spl.level_class"], "high")
        self.assertIn("VL", labels["nvh.ch.leq_db"])
        self.assertIn("_ref", labels["nvh.band.third_octave"])
        self.assertTrue(str(labels["nvh.band.third_octave"]["_ref"]).startswith("audio_spec/"))

        for hid in HUMAN_OR_SKIP:
            self.assertNotIn(hid, labels)

        deriv = {item["id"]: item["value_schema"]["derivation"] for item in build_labels()}
        auto_ids = [i for i, d in deriv.items() if d == "auto"]
        for lid in auto_ids:
            self.assertIn(lid, labels, msg=f"missing auto label {lid}")
        # seeded semi
        self.assertIn("nvh.clip.spl.level_class", labels)
        self.assertIn("nvh.spatial.channel_balance_grade", labels)
        self.assertIn("nvh.band.tonal_components", labels)

    def test_user_sample_leq_range(self) -> None:
        if not SAMPLE_DAT.is_file():
            self.skipTest(f"missing sample dat: {SAMPLE_DAT}")
        from hmi.local.audio_spectrum import analyze_pcm_pa
        from hmi.local.head_dat import parse_head_dat_bytes
        from hmi.local.nvh_deriver import derive_nvh_labels

        parsed = parse_head_dat_bytes(SAMPLE_DAT.read_bytes())
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            names = [c["name"] for c in parsed["channels"]]
            meta = {
                "format": "head_acoustics_hdf_v4",
                "fs_hz": parsed["fs_hz"],
                "duration_s": parsed["duration_s"],
                "n_channels": parsed["n_channels"],
                "unit": "Pa",
                "channels": parsed["channels"],
            }
            (root / "head_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            np.save(root / "pcm_pa.npy", parsed["pcm_pa"])
            analyze_pcm_pa(parsed["pcm_pa"], float(parsed["fs_hz"]), names, root / "audio_spec")
            labels = derive_nvh_labels(root)

        leq = float(labels["nvh.clip.spl.leq_db_mean"])
        self.assertGreaterEqual(leq, 93.0)
        self.assertLessEqual(leq, 96.0)
        for hid in ("nvh.sem.noise_category", "nvh.sem.quality_grade", "nvh.meta.record_context"):
            self.assertNotIn(hid, labels)

    def test_label_stage_semantic_enabled(self) -> None:
        from hmi.platform.recipe import seed_recipes

        rec = seed_recipes()["audio_array_spec"]
        self.assertTrue(rec["stages"]["label"]["enabled"])
        self.assertEqual(rec["stages"]["label"]["model"], "nvh_sem_ast")
        self.assertEqual(rec.get("taxonomy_version_code"), "audio_nvh-v2")
        self.assertFalse(rec["stages"]["embed"]["enabled"])


if __name__ == "__main__":
    unittest.main()
