"""HEAD .dat parse + audio_array_spec L2 products."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))

SAMPLE_DAT = Path(r"C:\Users\svw\Downloads\CBK1-4266 saixin steelsuokou-boardline.dat")


class TestHeadDatParse(unittest.TestCase):
    def test_parse_user_sample(self) -> None:
        if not SAMPLE_DAT.is_file():
            self.skipTest(f"missing sample dat: {SAMPLE_DAT}")
        from hmi.local.head_dat import parse_head_dat_bytes

        parsed = parse_head_dat_bytes(SAMPLE_DAT.read_bytes())
        self.assertEqual(parsed["n_channels"], 4)
        self.assertAlmostEqual(parsed["fs_hz"], 44100.0, delta=1.0)
        self.assertAlmostEqual(parsed["duration_s"], 55.5, delta=0.2)
        self.assertEqual(parsed["pcm_pa"].shape[1], 4)
        names = [c["name"] for c in parsed["channels"]]
        self.assertEqual(names, ["VL", "VR", "HL", "HR"])

    def test_persist_and_analyze(self) -> None:
        if not SAMPLE_DAT.is_file():
            self.skipTest(f"missing sample dat: {SAMPLE_DAT}")
        from hmi.local.audio_spectrum import analyze_pcm_pa
        from hmi.local.head_dat import parse_head_dat_bytes, persist_head_dat_package

        data = SAMPLE_DAT.read_bytes()
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td)
            meta = persist_head_dat_package(dest, SAMPLE_DAT.name, data)
            self.assertTrue((dest / "audio.wav").is_file())
            self.assertTrue((dest / "pcm_pa.npy").is_file())
            parsed = parse_head_dat_bytes(data)
            summary = analyze_pcm_pa(
                parsed["pcm_pa"],
                float(parsed["fs_hz"]),
                [c["name"] for c in parsed["channels"]],
                dest / "spec",
            )
            self.assertEqual(summary["n_channels"], 4)
            self.assertTrue((dest / "spec" / "VL" / "mel.png").is_file())
            self.assertTrue((dest / "spec" / "VL" / "third_octave.json").is_file())
            bands = json.loads((dest / "spec" / "VL" / "third_octave.json").read_text(encoding="utf-8"))
            self.assertGreater(len(bands), 10)
            self.assertIn("spl_db", bands[0])
            self.assertEqual(meta["n_channels"], 4)


class TestAudioArraySpecRecipe(unittest.TestCase):
    def test_seed_recipe(self) -> None:
        from hmi.platform.recipe import seed_recipes

        seeds = seed_recipes()
        self.assertIn("audio_array_spec", seeds)
        rec = seeds["audio_array_spec"]
        self.assertEqual(rec["overview_view"], "audio_nvh_timeline")
        self.assertTrue(rec["stages"]["label"]["enabled"])
        self.assertEqual(rec["stages"]["label"]["model"], "nvh_sem_heuristic")
        self.assertEqual(rec.get("taxonomy_version_code"), "audio_nvh-v2")
        self.assertFalse(rec["stages"]["embed"]["enabled"])
        ops = [s["op_id"] for s in rec["preprocess"]]
        self.assertIn("stft_spectrogram", ops)
        self.assertIn("mel_spectrogram", ops)


if __name__ == "__main__":
    unittest.main()
