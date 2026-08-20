"""L2 audio products: STFT, Mel, 1/3-octave, SPL timeline (numpy + Pillow)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

PREF_THIRD_OCTAVE_HZ = [
    20, 25, 31.5, 40, 50, 63, 80, 100, 125, 160, 200, 250, 315, 400, 500, 630,
    800, 1000, 1250, 1600, 2000, 2500, 3150, 4000, 5000, 6300, 8000, 10000,
    12500, 16000, 20000,
]


def _stft_mag(x: np.ndarray, fs: float, nperseg: int = 2048, hop: int = 512) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    window = np.hanning(nperseg).astype(np.float64)
    n = len(x)
    if n < nperseg:
        pad = np.zeros(nperseg, dtype=np.float64)
        pad[:n] = x.astype(np.float64)
        x = pad
        n = nperseg
    starts = list(range(0, n - nperseg + 1, hop))
    spec = np.empty((nperseg // 2 + 1, len(starts)), dtype=np.float64)
    for i, s in enumerate(starts):
        frame = x[s : s + nperseg].astype(np.float64) * window
        spec[:, i] = np.abs(np.fft.rfft(frame))
    freqs = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    times = (np.array(starts) + nperseg / 2.0) / fs
    return freqs, times, spec


def _mel_filterbank(n_fft: int, fs: float, n_mels: int = 64) -> np.ndarray:
    def hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
        return 2595.0 * np.log10(1.0 + np.asarray(hz) / 700.0)

    def mel_to_hz(mel: np.ndarray) -> np.ndarray:
        return 700.0 * (10 ** (mel / 2595.0) - 1.0)

    fmin, fmax = 20.0, min(fs / 2.0, 20000.0)
    mels = np.linspace(hz_to_mel(fmin), hz_to_mel(fmax), n_mels + 2)
    hz = mel_to_hz(mels)
    bins = np.floor((n_fft + 1) * hz / fs).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float64)
    for i in range(n_mels):
        left, center, right = bins[i], bins[i + 1], bins[i + 2]
        if center <= left:
            center = left + 1
        if right <= center:
            right = center + 1
        right = min(right, fb.shape[1] - 1)
        for j in range(left, center):
            if center != left:
                fb[i, j] = (j - left) / (center - left)
        for j in range(center, right):
            if right != center:
                fb[i, j] = (right - j) / (right - center)
    return fb


def _spec_png(mag: np.ndarray, path: Path) -> None:
    db = 20.0 * np.log10(np.maximum(mag, 1e-12))
    p10, p90 = np.percentile(db, [10, 99])
    scaled = np.clip((db - p10) / max(p90 - p10, 1e-6), 0, 1)
    h, w = scaled.shape
    target_w, target_h = 512, 256
    ys = np.linspace(0, h - 1, target_h)
    xs = np.linspace(0, w - 1, target_w)
    yy, xx = np.meshgrid(ys, xs, indexing="ij")
    img = scaled[yy.astype(int), xx.astype(int)]
    img = np.flipud(img)
    rgb = np.zeros((target_h, target_w, 3), dtype=np.uint8)
    rgb[..., 0] = (np.clip(img * 1.4, 0, 1) * 255).astype(np.uint8)
    rgb[..., 1] = (img * 180).astype(np.uint8)
    rgb[..., 2] = ((1 - img) * 80 + img * 40).astype(np.uint8)
    Image.fromarray(rgb, mode="RGB").save(path)


def _third_octave(x: np.ndarray, fs: float) -> list[dict[str, float]]:
    nperseg = min(8192, max(1024, int(2 ** np.floor(np.log2(len(x) or 2)))))
    freqs, _, mag = _stft_mag(x, fs, nperseg=nperseg, hop=nperseg // 2)
    psd = np.mean(mag**2, axis=1)
    nyq = fs / 2.0
    out: list[dict[str, float]] = []
    pref = 2e-5
    for fc in PREF_THIRD_OCTAVE_HZ:
        if fc >= nyq:
            break
        lo, hi = fc / (2 ** (1 / 6)), min(fc * (2 ** (1 / 6)), nyq)
        mask = (freqs >= lo) & (freqs < hi)
        if not np.any(mask):
            continue
        power = float(np.sum(psd[mask]))
        rms = float(np.sqrt(max(power, 0.0) / (nperseg / 2)))
        spl = 20.0 * np.log10(max(rms, 1e-12) / pref)
        out.append({"fc_hz": fc, "spl_db": spl})
    return out


def _spl_timeline(x: np.ndarray, fs: float, win_s: float = 0.125) -> list[dict[str, float]]:
    nwin = max(1, int(round(win_s * fs)))
    pref = 2e-5
    rows: list[dict[str, float]] = []
    for i in range(0, len(x) - nwin + 1, nwin):
        seg = x[i : i + nwin]
        rms = float(np.sqrt(np.mean(np.square(seg, dtype=np.float64))))
        rows.append(
            {
                "t_s": (i + nwin / 2.0) / fs,
                "spl_db": 20.0 * np.log10(max(rms, 1e-12) / pref),
            }
        )
    return rows


def analyze_pcm_pa(pcm_pa: np.ndarray, fs: float, channel_names: list[str], out_dir: Path) -> dict[str, Any]:
    """Write L2 products. pcm_pa shape (n, ch) in Pascal."""
    out_dir.mkdir(parents=True, exist_ok=True)
    n_ch = pcm_pa.shape[1]
    names = list(channel_names) + [f"ch{i+1}" for i in range(len(channel_names), n_ch)]
    pref = 2e-5
    summary_ch: list[dict[str, Any]] = []
    for i in range(n_ch):
        name = names[i]
        x = np.asarray(pcm_pa[:, i], dtype=np.float64)
        rms = float(np.sqrt(np.mean(np.square(x))))
        leq = 20.0 * np.log10(max(rms, 1e-12) / pref)
        freqs, times, mag = _stft_mag(x, fs)
        ch_dir = out_dir / name
        ch_dir.mkdir(exist_ok=True)
        np.save(ch_dir / "stft_mag.npy", mag.astype(np.float32))
        np.save(ch_dir / "stft_freqs.npy", freqs.astype(np.float32))
        np.save(ch_dir / "stft_times.npy", times.astype(np.float32))
        _spec_png(mag, ch_dir / "stft.png")
        fb = _mel_filterbank((mag.shape[0] - 1) * 2, fs)
        if fb.shape[1] != mag.shape[0]:
            fb = _mel_filterbank(2048, fs)
            if fb.shape[1] > mag.shape[0]:
                fb = fb[:, : mag.shape[0]]
            else:
                mag_m = mag[: fb.shape[1], :]
                mag = mag_m
        mel = fb @ mag
        np.save(ch_dir / "mel_matrix.npy", mel.astype(np.float32))
        _spec_png(mel, ch_dir / "mel.png")
        bands = _third_octave(x, fs)
        (ch_dir / "third_octave.json").write_text(json.dumps(bands, ensure_ascii=False), encoding="utf-8")
        spl = _spl_timeline(x, fs)
        with (ch_dir / "spl_timeline.jsonl").open("w", encoding="utf-8") as f:
            for row in spl:
                f.write(json.dumps(row) + "\n")
        (ch_dir / "waveform.json").write_text(
            json.dumps(
                {
                    "fs_display": 200,
                    "samples": x[:: max(1, int(fs / 200))].tolist(),
                }
            ),
            encoding="utf-8",
        )
        summary_ch.append({"name": name, "rms_pa": rms, "leq_db": leq, "n_samples": int(len(x))})
    summary = {
        "fs_hz": fs,
        "n_channels": n_ch,
        "duration_s": pcm_pa.shape[0] / fs,
        "unit": "Pa",
        "channels": summary_ch,
        "products": ["stft", "mel_matrix", "third_octave", "spl_timeline", "waveform"],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
