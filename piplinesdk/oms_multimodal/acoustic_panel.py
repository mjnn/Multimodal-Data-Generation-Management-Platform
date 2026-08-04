"""将 clip 音频渲染为声学面板（STFT / Mel 频谱图），并导出 Mel 矩阵文本特征。

- PNG：供 VL-embedding 作为 image 输入
- Mel 矩阵（csv/npy）+ feature text：供 Omni 打标与 fusion embedding 的 text 侧输入
"""
from __future__ import annotations

import csv
import json
import os
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
from PIL import Image

PanelType = Literal["stft", "mel"]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass
class AcousticPanelConfig:
    """声学面板 / Mel 矩阵渲染参数。"""

    panel_type: PanelType = "mel"
    n_fft: int = 2048
    hop_length: int = 512
    n_mels: int = 128
    fmin: float = 20.0
    fmax: float | None = None
    target_width: int = 768
    target_height: int = 256
    # Mel 矩阵导出（文本特征）
    export_mel_matrix: bool = True
    mel_matrix_csv: bool = True
    mel_matrix_npy: bool = False
    # 写入 label/embed 的文本侧：时间轴下采样帧数上限
    mel_feature_max_frames: int = 32
    mel_feature_max_chars: int = 6000

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
            export_mel_matrix=_env_bool("ACOUSTIC_EXPORT_MEL_MATRIX", True),
            mel_matrix_csv=_env_bool("ACOUSTIC_MEL_MATRIX_CSV", True),
            mel_matrix_npy=_env_bool("ACOUSTIC_MEL_MATRIX_NPY", False),
            mel_feature_max_frames=int(os.getenv("ACOUSTIC_MEL_FEATURE_MAX_FRAMES", "32")),
            mel_feature_max_chars=int(os.getenv("ACOUSTIC_MEL_FEATURE_MAX_CHARS", "6000")),
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


def compute_mel_matrix(
    wav_path: str | Path,
    *,
    config: AcousticPanelConfig | None = None,
    log_power: bool = True,
) -> tuple[np.ndarray, dict[str, Any]]:
    """从 WAV 计算 Mel（或 STFT）功率矩阵。

    Returns:
        matrix: shape ``(n_bins, n_frames)``；默认 ``log1p`` 功率
        meta: sample_rate / shape / panel_type 等
    """
    panel_config = config or AcousticPanelConfig()
    wav_path = Path(wav_path)
    signal, sample_rate = _load_mono_wav(wav_path)
    power = _compute_spectrogram(signal, sample_rate, panel_config)
    matrix = np.log1p(power).astype(np.float32) if log_power else power.astype(np.float32)
    meta = {
        "wav_path": str(wav_path.resolve()),
        "sample_rate": sample_rate,
        "panel_type": panel_config.panel_type,
        "n_fft": panel_config.n_fft,
        "hop_length": panel_config.hop_length,
        "n_mels": panel_config.n_mels if panel_config.panel_type == "mel" else int(matrix.shape[0]),
        "fmin": panel_config.fmin,
        "fmax": panel_config.fmax if panel_config.fmax is not None else sample_rate / 2,
        "shape": [int(matrix.shape[0]), int(matrix.shape[1])],
        "log_power": log_power,
        "dtype": "float32",
    }
    return matrix, meta


def mel_matrix_to_feature_text(
    matrix: np.ndarray,
    *,
    meta: dict[str, Any] | None = None,
    config: AcousticPanelConfig | None = None,
) -> str:
    """将 Mel 矩阵压缩为可供 Omni / Embedding 文本侧使用的特征描述。

    包含：全局统计 + 时间轴下采样后的每帧 band 能量摘要（非整表灌入）。
    """
    panel_config = config or AcousticPanelConfig()
    meta = meta or {}
    n_bins, n_frames = int(matrix.shape[0]), int(matrix.shape[1])
    flat = matrix.reshape(-1)
    stats_lines = [
        "[Mel spectrogram matrix features]",
        (
            f"shape=({n_bins},{n_frames}) panel_type={meta.get('panel_type', panel_config.panel_type)} "
            f"n_fft={meta.get('n_fft', panel_config.n_fft)} hop={meta.get('hop_length', panel_config.hop_length)} "
            f"sr={meta.get('sample_rate', '')}"
        ),
        (
            f"global: mean={float(flat.mean()):.4f} std={float(flat.std()):.4f} "
            f"min={float(flat.min()):.4f} max={float(flat.max()):.4f} "
            f"p25={float(np.percentile(flat, 25)):.4f} p50={float(np.percentile(flat, 50)):.4f} "
            f"p75={float(np.percentile(flat, 75)):.4f}"
        ),
    ]

    # 频带三分：低 / 中 / 高
    if n_bins >= 3:
        a, b = n_bins // 3, 2 * n_bins // 3
        bands = {
            "low": matrix[:a, :],
            "mid": matrix[a:b, :],
            "high": matrix[b:, :],
        }
        band_parts = []
        for name, block in bands.items():
            band_parts.append(
                f"{name}_mean={float(block.mean()):.4f}/std={float(block.std()):.4f}"
            )
        stats_lines.append("bands: " + " ".join(band_parts))

    max_frames = max(1, int(panel_config.mel_feature_max_frames))
    if n_frames <= max_frames:
        indices = list(range(n_frames))
    else:
        indices = [
            int(round(i * (n_frames - 1) / (max_frames - 1))) for i in range(max_frames)
        ]

    # 每帧：低频/中频/高频均值（压缩文本，避免整表）
    frame_lines: list[str] = ["time_frames (idx:low,mid,high):"]
    for idx in indices:
        col = matrix[:, idx]
        if n_bins >= 3:
            a, b = n_bins // 3, 2 * n_bins // 3
            vals = (
                float(col[:a].mean()),
                float(col[a:b].mean()),
                float(col[b:].mean()),
            )
            frame_lines.append(f"{idx}:{vals[0]:.3f},{vals[1]:.3f},{vals[2]:.3f}")
        else:
            frame_lines.append(f"{idx}:{float(col.mean()):.3f}")

    text = "\n".join(stats_lines + frame_lines)
    max_chars = max(500, int(panel_config.mel_feature_max_chars))
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n...[truncated]"
    return text


def save_mel_matrix(
    matrix: np.ndarray,
    output_stem: str | Path,
    *,
    meta: dict[str, Any] | None = None,
    config: AcousticPanelConfig | None = None,
) -> dict[str, Any]:
    """导出 Mel 矩阵为 csv（文本）与可选 npy；并写 meta json。

    ``output_stem`` 例：``.../clips/{id}/mel_matrix`` →
    ``mel_matrix.csv`` / ``mel_matrix.meta.json`` / 可选 ``mel_matrix.npy``。
    """
    panel_config = config or AcousticPanelConfig()
    base = Path(output_stem)
    if base.suffix:
        base = base.with_suffix("")
    base.parent.mkdir(parents=True, exist_ok=True)

    meta = dict(meta or {})
    meta.setdefault("shape", [int(matrix.shape[0]), int(matrix.shape[1])])

    csv_path = Path(str(base) + ".csv")
    npy_path = Path(str(base) + ".npy")
    meta_path = Path(str(base) + ".meta.json")

    out: dict[str, Any] = {
        "shape": meta["shape"],
        "meta_path": None,
        "csv_path": None,
        "npy_path": None,
        "feature_text": mel_matrix_to_feature_text(matrix, meta=meta, config=panel_config),
    }

    if panel_config.mel_matrix_csv:
        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow([f"bin_{i}" for i in range(matrix.shape[0])])
            # 行 = 时间帧，列 = mel bin（便于文本查看）
            for t in range(matrix.shape[1]):
                writer.writerow([f"{float(v):.6f}" for v in matrix[:, t]])
        out["csv_path"] = str(csv_path.resolve())
        meta["csv_layout"] = "rows=time_frames, cols=freq_bins"

    if panel_config.mel_matrix_npy:
        np.save(npy_path, matrix)
        out["npy_path"] = str(npy_path.resolve())

    meta["feature_text_preview_chars"] = len(out["feature_text"])
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    out["meta_path"] = str(meta_path.resolve())
    return out


def render_acoustic_assets(
    wav_path: str | Path,
    output_dir: str | Path,
    *,
    config: AcousticPanelConfig | None = None,
    panel_filename: str = "acoustic_panel.png",
    matrix_stem: str = "mel_matrix",
) -> dict[str, Any]:
    """一次计算：写 PNG 面板 +（可选）Mel 矩阵文件 + feature_text。"""
    panel_config = config or AcousticPanelConfig()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    matrix, meta = compute_mel_matrix(wav_path, config=panel_config, log_power=True)
    panel_path = output_dir / panel_filename
    # PNG 用归一化后的可视化（与历史行为一致）
    normalized = _normalize_log_power(matrix)
    rgb = _viridis_rgb(normalized)
    image = Image.fromarray(rgb, mode="RGB")
    image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    image = image.resize(
        (panel_config.target_width, panel_config.target_height),
        Image.Resampling.BILINEAR,
    )
    image.save(panel_path, format="PNG")

    result: dict[str, Any] = {
        "acoustic_panel_path": str(panel_path.resolve()),
        "mel_matrix_path": None,
        "mel_matrix_npy_path": None,
        "mel_matrix_meta_path": None,
        "mel_feature_text": None,
        "mel_matrix_shape": meta["shape"],
        "acoustic_panel_config": panel_config.to_dict(),
    }

    if panel_config.export_mel_matrix and panel_config.panel_type == "mel":
        saved = save_mel_matrix(
            matrix,
            output_dir / matrix_stem,
            meta=meta,
            config=panel_config,
        )
        result["mel_matrix_path"] = saved.get("csv_path")
        result["mel_matrix_npy_path"] = saved.get("npy_path")
        result["mel_matrix_meta_path"] = saved.get("meta_path")
        result["mel_feature_text"] = saved.get("feature_text")
    elif panel_config.export_mel_matrix:
        # STFT 也可导出矩阵，文件名仍用 stem
        saved = save_mel_matrix(
            matrix,
            output_dir / matrix_stem,
            meta=meta,
            config=panel_config,
        )
        result["mel_matrix_path"] = saved.get("csv_path")
        result["mel_matrix_npy_path"] = saved.get("npy_path")
        result["mel_matrix_meta_path"] = saved.get("meta_path")
        result["mel_feature_text"] = saved.get("feature_text")

    return result


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

    assets = render_acoustic_assets(
        wav_path,
        Path(output_path).parent,
        config=panel_config,
        panel_filename=Path(output_path).name,
    )
    return str(assets["acoustic_panel_path"])
