"""PCM (Pa) → AudioSet-527 sigmoid probabilities using Gong AST preprocessing."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

TARGET_SR = 16000
NUM_MEL_BINS = 128
TARGET_FRAMES = 1024
# YuanGongND/ast AudioSet stats (dataloader: (x - mean) / (std * 2))
NORM_MEAN = -4.2677393
NORM_STD = 4.5689974


def _load_pcm(run_root: Path) -> tuple[np.ndarray, float] | None:
    pcm_path = run_root / "pcm_pa.npy"
    meta_path = run_root / "head_meta.json"
    if not pcm_path.is_file():
        return None
    pcm = np.load(pcm_path)
    fs = 16000.0
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            fs = float(meta.get("fs_hz") or fs)
        except Exception:  # noqa: BLE001
            pass
    if pcm.ndim == 1:
        pcm = pcm[:, None]
    return pcm.astype(np.float64), fs


def _mix_peak_norm(pcm: np.ndarray) -> np.ndarray:
    if pcm.shape[1] == 1:
        mono = pcm[:, 0]
    else:
        mono = np.sqrt(np.mean(np.square(pcm), axis=1))
    mono = mono - float(np.mean(mono))
    peak = float(np.max(np.abs(mono)))
    if peak > 1e-12:
        mono = mono / peak * 0.99
    return mono.astype(np.float32)


def _resample_16k(mono: np.ndarray, fs: float) -> np.ndarray:
    if abs(fs - TARGET_SR) < 1e-6:
        return mono
    import torch
    import torchaudio

    wav = torch.from_numpy(mono).unsqueeze(0)
    out = torchaudio.functional.resample(wav, int(round(fs)), TARGET_SR)
    return out.squeeze(0).numpy()


def _kaldi_fbank(mono_16k: np.ndarray) -> "torch.Tensor":
    import torch
    import torchaudio

    wav = torch.from_numpy(np.asarray(mono_16k, dtype=np.float32)).unsqueeze(0)
    fbank = torchaudio.compliance.kaldi.fbank(
        wav,
        htk_compat=True,
        sample_frequency=TARGET_SR,
        use_energy=False,
        window_type="hanning",
        num_mel_bins=NUM_MEL_BINS,
        dither=0.0,
        frame_shift=10,
    )
    return fbank  # (T, 128)


def _windows_1024(fbank: "torch.Tensor") -> "torch.Tensor":
    import torch

    n = int(fbank.shape[0])
    if n < TARGET_FRAMES:
        pad = torch.zeros(TARGET_FRAMES - n, fbank.shape[1], dtype=fbank.dtype)
        return torch.cat([fbank, pad], dim=0).unsqueeze(0)
    chunks = []
    start = 0
    while start < n:
        sl = fbank[start : start + TARGET_FRAMES]
        if sl.shape[0] < TARGET_FRAMES:
            pad = torch.zeros(TARGET_FRAMES - sl.shape[0], sl.shape[1], dtype=sl.dtype)
            sl = torch.cat([sl, pad], dim=0)
        chunks.append(sl)
        start += TARGET_FRAMES
    return torch.stack(chunks, dim=0)


def infer_audioset_probs(run_root: Path, labels: dict[str, Any] | None = None) -> list[float] | None:
    del labels  # PCM-only; labels unused
    loaded = _load_pcm(run_root)
    if loaded is None:
        logger.info("nvh_sem_ast: missing pcm_pa.npy under %s", run_root)
        return None
    try:
        import torch
        from hmi.local.nvh_ast.model import load_ast_model
    except Exception as exc:  # noqa: BLE001
        logger.info("nvh_sem_ast: torch/model unavailable: %s", exc)
        return None
    try:
        import torchaudio  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        logger.info("nvh_sem_ast: torchaudio unavailable: %s", exc)
        return None

    pcm, fs = loaded
    try:
        mono = _mix_peak_norm(pcm)
        mono_16k = _resample_16k(mono, fs)
        fbank = _kaldi_fbank(mono_16k)
        fbank = (fbank - NORM_MEAN) / (NORM_STD * 2)
        windows = _windows_1024(fbank)
        model = load_ast_model()
        with torch.no_grad():
            logits = model(windows)
            probs = torch.sigmoid(logits).mean(dim=0)
        return [float(x) for x in probs.cpu().tolist()]
    except Exception as exc:  # noqa: BLE001
        logger.warning("nvh_sem_ast infer failed: %s", exc)
        return None
