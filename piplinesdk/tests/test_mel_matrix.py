"""Unit tests for Mel matrix export and feature text."""
from __future__ import annotations

import math
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from oms_multimodal.acoustic_panel import (
    AcousticPanelConfig,
    compute_mel_matrix,
    mel_matrix_to_feature_text,
    render_acoustic_assets,
    save_mel_matrix,
)
from oms_multimodal.rosbag_parser import Clip


def _write_sine_wav(path: Path, *, seconds: float = 0.5, sr: int = 16000, freq: float = 440.0) -> None:
    t = np.arange(int(sr * seconds), dtype=np.float32) / sr
    signal = (0.4 * np.sin(2 * math.pi * freq * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(signal.tobytes())


class TestMelMatrix(unittest.TestCase):
    def test_compute_and_save_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "a.wav"
            _write_sine_wav(wav)
            matrix, meta = compute_mel_matrix(wav, config=AcousticPanelConfig(n_mels=32, n_fft=512, hop_length=256))
            self.assertEqual(matrix.shape[0], 32)
            self.assertGreater(matrix.shape[1], 0)
            self.assertEqual(meta["panel_type"], "mel")

            saved = save_mel_matrix(
                matrix,
                Path(tmp) / "mel_matrix",
                meta=meta,
                config=AcousticPanelConfig(n_mels=32, mel_matrix_csv=True, mel_matrix_npy=True),
            )
            self.assertTrue(Path(saved["csv_path"]).is_file())
            self.assertTrue(Path(saved["npy_path"]).is_file())
            self.assertIn("[Mel spectrogram matrix features]", saved["feature_text"])
            self.assertIn("shape=(32,", saved["feature_text"])

    def test_render_acoustic_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "b.wav"
            _write_sine_wav(wav)
            out = Path(tmp) / "clip"
            assets = render_acoustic_assets(
                wav,
                out,
                config=AcousticPanelConfig(n_mels=16, n_fft=512, hop_length=256),
            )
            self.assertTrue(Path(assets["acoustic_panel_path"]).is_file())
            self.assertTrue(Path(assets["mel_matrix_path"]).is_file())
            self.assertIsNotNone(assets["mel_feature_text"])
            self.assertEqual(assets["mel_matrix_shape"][0], 16)

    def test_speech_context_includes_mel_feature(self) -> None:
        clip = Clip(
            clip_id="c0",
            bag_name="x.bag",
            start_timestamp_ns=0,
            end_timestamp_ns=1_000_000_000,
            duration_sec=1.0,
            asr_text="hello",
            mel_feature_text="[Mel spectrogram matrix features]\nshape=(8,4)",
        )
        text = clip.speech_context_text()
        self.assertIn("[ASR transcript]", text)
        self.assertIn("[Mel spectrogram matrix features]", text)

    def test_feature_text_truncation(self) -> None:
        matrix = np.random.rand(64, 200).astype(np.float32)
        text = mel_matrix_to_feature_text(
            matrix,
            meta={"panel_type": "mel", "n_fft": 512, "hop_length": 256, "sample_rate": 16000},
            config=AcousticPanelConfig(mel_feature_max_frames=8, mel_feature_max_chars=800),
        )
        self.assertLessEqual(len(text), 800)


if __name__ == "__main__":
    unittest.main()
