"""将 clip 音频渲染为声学面板（STFT / Mel 频谱图），供 VL-embedding 作为图像输入。"""
from __future__ import annotations

import os
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image

PanelType = Literal["stft", "mel"]


@dataclass
class AcousticPanelConfig:
    """声学面板渲染参数。"""

    panel_type: PanelType = "mel"
    n_fft: int = 2048
    hop_length: int = 512
    n_mels: int = 128
    fmin: float = 20.0
    fmax: float | None = None
    target_width: int = 768
    target_height: int = 256

    @classmethod
    def from_env(cls) -> AcousticPanelConfig:
        fmax_raw = os.getenv("ACOUSTIC_PANEL_FMAX", "").strip()
        panel_type = os.getenv("ACOUSTIC_PANEL_TYPE", "mel").strip().lower()
        if panel_type not in {"stft", "mel"}:
            panel_type = "mel"
        return cls(
            panel_type=panel_type,  # type: ignore[arg-type]
            n_fft=int(os.getenv("ACOUSTIC_PANEL_N_FFT", "2048")),
            hop_length=int(os.getenv("ACOUSTIC_PANEL_HOP_LENGTH", "512")),
            n_mels=int(os.getenv("ACOUSTIC_PANEL_N_MELS", "128")),
            fmin=float(os.getenv("ACOUSTIC_PANEL_FMIN", "20")),
            fmax=float(fmax_raw) if fmax_raw else None,
            target_width=int(os.getenv("ACOUSTIC_PANEL_WIDTH", "768")),
            target_height=int(os.getenv("ACOUSTIC_PANEL_HEIGHT", "256")),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _load_mono_wav(wav_path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(wav_path), "rb") as wf:
        sample_rate = wf.getframerate()
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        frame_count = wf.getnframes()
        raw = wf.readframes(frame_count)

    if sample_width == 2:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    elif sample_width == 4:
        samples = np.frombuffer(raw, dtype=np.int32).astype(np.float32)
    else:
        raise ValueError(f"Unsupported WAV sample width: {sample_width}")

    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)

    peak = np.max(np.abs(samples))
    if peak > 0:
        samples /= peak
    return samples, sample_rate


def _stft(signal: np.ndarray, *, n_fft: int, hop_length: int) -> np.ndarray:
    if len(signal) < n_fft:
        signal = np.pad(signal, (0, n_fft - len(signal)))

    window = np.hanning(n_fft).astype(np.float32)
    frames = (len(signal) - n_fft) // hop_length + 1
    spec = np.empty((n_fft // 2 + 1, frames), dtype=np.float32)
    for i in range(frames):
        start = i * hop_length
        chunk = signal[start : start + n_fft] * window
        spec[:, i] = np.abs(np.fft.rfft(chunk))
    return spec


def _hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)


def _mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def _mel_filterbank(
    *,
    n_mels: int,
    n_fft: int,
    sample_rate: int,
    fmin: float,
    fmax: float,
) -> np.ndarray:
    n_freqs = n_fft // 2 + 1
    mel_points = np.linspace(_hz_to_mel(fmin), _hz_to_mel(fmax), n_mels + 2)
    hz_points = _mel_to_hz(mel_points)
    bin_points = np.floor((n_fft + 1) * hz_points / sample_rate).astype(int)
    bin_points = np.clip(bin_points, 0, n_freqs - 1)

    weights = np.zeros((n_mels, n_freqs), dtype=np.float32)
    for i in range(n_mels):
        left, center, right = bin_points[i : i + 3]
        if center == left:
            center = min(left + 1, n_freqs - 1)
        if right == center:
            right = min(center + 1, n_freqs - 1)
        if center > left:
            weights[i, left:center] = (np.arange(left, center) - left) / (center - left)
        if right > center:
            weights[i, center:right] = (right - np.arange(center, right)) / (right - center)
    return weights


def _compute_spectrogram(
    signal: np.ndarray,
    sample_rate: int,
    config: AcousticPanelConfig,
) -> np.ndarray:
    spec = _stft(signal, n_fft=config.n_fft, hop_length=config.hop_length)
    if config.panel_type == "stft":
        return spec

    fmax = config.fmax if config.fmax is not None else sample_rate / 2
    mel_basis = _mel_filterbank(
        n_mels=config.n_mels,
        n_fft=config.n_fft,
        sample_rate=sample_rate,
        fmin=config.fmin,
        fmax=fmax,
    )
    return mel_basis @ (spec**2)


def _viridis_rgb(values: np.ndarray) -> np.ndarray:
    """Map normalized [0, 1] values to RGB using a viridis-like palette."""
    anchors = np.array(
        [
            [68, 1, 84],
            [59, 82, 139],
            [33, 145, 140],
            [94, 201, 98],
            [253, 231, 37],
        ],
        dtype=np.float32,
    )
    scaled = np.clip(values, 0.0, 1.0) * (len(anchors) - 1)
    lower = np.floor(scaled).astype(np.int32)
    upper = np.minimum(lower + 1, len(anchors) - 1)
    weight = (scaled - lower)[..., None]
    rgb = anchors[lower] * (1.0 - weight) + anchors[upper] * weight
    return rgb.astype(np.uint8)


def _normalize_log_power(log_power: np.ndarray) -> np.ndarray:
    lo = np.percentile(log_power, 5)
    hi = np.percentile(log_power, 99)
    if hi <= lo:
        hi = lo + 1e-6
    return np.clip((log_power - lo) / (hi - lo), 0.0, 1.0)


def render_acoustic_panel(
    wav_path: str | Path,
    output_path: str | Path,
    *,
    config: AcousticPanelConfig | None = None,
    n_fft: int | None = None,
    hop_length: int | None = None,
    target_width: int | None = None,
    target_height: int | None = None,
) -> str:
    """Render an acoustic panel PNG from a WAV file.

    Returns:
        Absolute path to the generated PNG.
    """
    panel_config = config or AcousticPanelConfig()
    if n_fft is not None:
        panel_config.n_fft = n_fft
    if hop_length is not None:
        panel_config.hop_length = hop_length
    if target_width is not None:
        panel_config.target_width = target_width
    if target_height is not None:
        panel_config.target_height = target_height

    wav_path = Path(wav_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    signal, sample_rate = _load_mono_wav(wav_path)
    spec = _compute_spectrogram(signal, sample_rate, panel_config)
    normalized = _normalize_log_power(np.log1p(spec))

    rgb = _viridis_rgb(normalized)
    image = Image.fromarray(rgb, mode="RGB")
    image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    image = image.resize(
        (panel_config.target_width, panel_config.target_height),
        Image.Resampling.BILINEAR,
    )
    image.save(output_path, format="PNG")
    return str(output_path.resolve())
