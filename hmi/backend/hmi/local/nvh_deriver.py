"""Derive objective NVH labels (audio_nvh-v2) from L2 audio_spec products.

Fills auto + semi (with deterministic auto seeds). Human fields are omitted.
json_ref values point relative to runs/{run_id}/ (run root).
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from hmi.platform.audio_nvh_v2 import CH_NAMES, PREF_PA, VERSION_CODE, build_labels

DERIVER_VERSION = "nvh_deriver-v1"
LEVEL_CLASS_THRESHOLDS_DB = (70.0, 85.0, 100.0)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _json_ref(rel: str, run_root: Path) -> dict[str, Any]:
    out: dict[str, Any] = {"_ref": rel.replace("\\", "/")}
    digest = _sha256_file(run_root / rel)
    if digest:
        out["_sha256"] = digest
    return out


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _db_from_pa(pa: float) -> float:
    return 20.0 * math.log10(max(float(pa), 1e-12) / PREF_PA)


def _lin_from_db(db: float) -> float:
    return 10.0 ** (float(db) / 10.0)


def _ch_map(values: dict[str, float]) -> dict[str, float]:
    return {name: float(values.get(name, 0.0)) for name in CH_NAMES if name in values}


def _resolve_channels(summary: dict[str, Any], run_root: Path) -> list[str]:
    names = [str(c.get("name") or "") for c in (summary.get("channels") or []) if c.get("name")]
    if names:
        return names
    spec = run_root / "audio_spec"
    found = [n for n in CH_NAMES if (spec / n).is_dir()]
    return list(found) if found else list(CH_NAMES)


def _band_spl(bands: list[dict[str, Any]], f_lo: float, f_hi: float) -> float:
    powers = []
    for b in bands:
        fc = float(b.get("fc_hz") or 0.0)
        if f_lo <= fc < f_hi:
            powers.append(_lin_from_db(float(b.get("spl_db") or -120.0)))
    if not powers:
        return -120.0
    return 10.0 * math.log10(max(sum(powers), 1e-30))


def _dominant_fc(bands: list[dict[str, Any]]) -> float:
    if not bands:
        return 0.0
    best = max(bands, key=lambda b: float(b.get("spl_db") or -1e9))
    return float(best.get("fc_hz") or 0.0)


def _tonality_index(bands: list[dict[str, Any]]) -> float:
    if not bands:
        return 0.0
    vals = [float(b.get("spl_db") or 0.0) for b in bands]
    return float(np.clip((max(vals) - float(np.median(vals))) / 15.0, 0.0, 1.0))


def _flatness(bands: list[dict[str, Any]]) -> float:
    if not bands:
        return 0.0
    lin = np.array([_lin_from_db(float(b.get("spl_db") or -120.0)) for b in bands], dtype=np.float64)
    lin = np.maximum(lin, 1e-30)
    geo = float(np.exp(np.mean(np.log(lin))))
    arith = float(np.mean(lin))
    return float(np.clip(geo / max(arith, 1e-30), 0.0, 1.0))


def _spectral_slope_db_oct(bands: list[dict[str, Any]]) -> float:
    xs: list[float] = []
    ys: list[float] = []
    for b in bands:
        fc = float(b.get("fc_hz") or 0.0)
        if 100.0 <= fc <= 8000.0:
            xs.append(math.log2(fc))
            ys.append(float(b.get("spl_db") or 0.0))
    if len(xs) < 2:
        return 0.0
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    x = x - x.mean()
    denom = float(np.dot(x, x))
    if denom < 1e-12:
        return 0.0
    return float(np.dot(x, y - y.mean()) / denom)


def _centroid_hz(run_root: Path, ch: str) -> float:
    mag_p = run_root / "audio_spec" / ch / "stft_mag.npy"
    freq_p = run_root / "audio_spec" / ch / "stft_freqs.npy"
    if not mag_p.is_file() or not freq_p.is_file():
        return 0.0
    mag = np.load(mag_p)
    freqs = np.load(freq_p)
    e = np.mean(np.square(mag.astype(np.float64)), axis=1)
    denom = float(np.sum(e))
    if denom <= 0:
        return 0.0
    return float(np.sum(freqs.astype(np.float64) * e) / denom)


def _percentile_exceedance(values: list[float], pct: float) -> float:
    """pct% exceedance level (higher SPL): L10 ≈ 90th percentile."""
    if not values:
        return 0.0
    return float(np.percentile(np.asarray(values, dtype=np.float64), 100.0 - pct))


def _mid_window_stats(timelines: dict[str, list[dict[str, Any]]]) -> tuple[bool, float, dict[str, float]]:
    all_rows: list[tuple[float, float]] = []
    for rows in timelines.values():
        for r in rows:
            all_rows.append((float(r.get("t_s") or 0.0), float(r.get("spl_db") or 0.0)))
    if not all_rows:
        return False, 0.0, {"t_start_s": 0.0, "t_end_s": 0.0, "leq_db": 0.0}
    all_rows.sort(key=lambda x: x[0])
    t0, t1 = all_rows[0][0], all_rows[-1][0]
    span = max(t1 - t0, 1e-9)
    lo, hi = t0 + 0.1 * span, t0 + 0.9 * span
    mid = [spl for t, spl in all_rows if lo <= t <= hi]
    if not mid:
        mid = [spl for _, spl in all_rows]
    steady = float(np.std(np.asarray(mid, dtype=np.float64))) < 3.0
    leq = 10.0 * math.log10(max(float(np.mean([_lin_from_db(s) for s in mid])), 1e-30))
    return steady, float(np.std(mid)) if mid else 0.0, {
        "t_start_s": float(lo),
        "t_end_s": float(hi),
        "leq_db": float(leq),
    }


def _modulation_index(timelines: dict[str, list[dict[str, Any]]]) -> float:
    vals: list[float] = []
    for rows in timelines.values():
        spl = [float(r.get("spl_db") or 0.0) for r in rows]
        if len(spl) < 2:
            continue
        diff = np.diff(np.asarray(spl, dtype=np.float64))
        mean = float(np.mean(np.abs(spl))) + 1e-9
        vals.append(float(np.sqrt(np.mean(diff**2))) / mean)
    if not vals:
        return 0.0
    return float(np.clip(np.mean(vals), 0.0, 1.0))


def _onset_count(timelines: dict[str, list[dict[str, Any]]]) -> int:
    count = 0
    for rows in timelines.values():
        spl = [float(r.get("spl_db") or 0.0) for r in rows]
        for i in range(1, len(spl)):
            if spl[i] - spl[i - 1] >= 3.0:
                count += 1
    return int(count)


def _transient_events(
    timelines: dict[str, list[dict[str, Any]]],
    leq_mean: float,
    win_s: float = 0.125,
) -> list[dict[str, Any]]:
    thr = leq_mean + 6.0
    events: list[dict[str, Any]] = []
    for ch, rows in timelines.items():
        i = 0
        while i < len(rows):
            spl = float(rows[i].get("spl_db") or 0.0)
            if spl < thr:
                i += 1
                continue
            j = i
            peak = spl
            while j < len(rows) and float(rows[j].get("spl_db") or 0.0) >= thr:
                peak = max(peak, float(rows[j].get("spl_db") or 0.0))
                j += 1
            dur_ms = (j - i) * win_s * 1000.0
            if dur_ms < 200.0:
                events.append(
                    {
                        "t_s": float(rows[i].get("t_s") or 0.0),
                        "ch": ch,
                        "peak_db": float(peak),
                        "dur_ms": float(dur_ms),
                    }
                )
            i = max(j, i + 1)
    events.sort(key=lambda e: e["t_s"])
    return events


def _peak_list(run_root: Path, channels: list[str], top_n: int = 8) -> list[dict[str, Any]]:
    peaks: list[dict[str, Any]] = []
    for ch in channels:
        mag_p = run_root / "audio_spec" / ch / "stft_mag.npy"
        freq_p = run_root / "audio_spec" / ch / "stft_freqs.npy"
        if not mag_p.is_file() or not freq_p.is_file():
            continue
        mag = np.load(mag_p).astype(np.float64)
        freqs = np.load(freq_p).astype(np.float64)
        e = np.mean(mag**2, axis=1)
        if e.size < 3:
            continue
        for i in range(1, len(e) - 1):
            if e[i] >= e[i - 1] and e[i] >= e[i + 1] and e[i] > 0:
                rms = math.sqrt(max(e[i], 0.0))
                peaks.append(
                    {
                        "fc_hz": float(freqs[i]),
                        "spl_db": _db_from_pa(rms),
                        "ch": ch,
                        "bw_hz": float(max(freqs[1] - freqs[0], 0.0)) if len(freqs) > 1 else 0.0,
                    }
                )
    peaks.sort(key=lambda p: p["spl_db"], reverse=True)
    return peaks[:top_n]


def _tonal_components(peaks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not peaks:
        return out
    floor = float(np.median([p["spl_db"] for p in peaks]))
    for p in peaks:
        prom = float(p["spl_db"] - floor)
        if prom < 3.0:
            continue
        out.append(
            {
                "fc_hz": p["fc_hz"],
                "spl_db": p["spl_db"],
                "prominence_db": prom,
                "confirmed": False,
            }
        )
    return out


def _a_weight_filter(x: np.ndarray, fs: float) -> np.ndarray:
    """Frequency-domain A-weighting (IEC 61672 curve), scipy-free."""
    f1, f2, f3, f4 = 20.598997, 107.65265, 737.86223, 12194.217
    a1000 = 1.9997
    n = len(x)
    if n < 16:
        return x.astype(np.float64)
    nfft = 1 << int(math.ceil(math.log2(n)))
    freqs = np.fft.rfftfreq(nfft, d=1.0 / fs)
    f = np.maximum(freqs, 1e-6)
    ra = (f4**2) * (f**4) / (
        ((f**2) + (f1**2))
        * np.sqrt((f**2) + (f2**2))
        * np.sqrt((f**2) + (f3**2))
        * ((f**2) + (f4**2))
    )
    a = 20.0 * np.log10(np.maximum(ra, 1e-30)) - 20.0 * math.log10(a1000)
    w = 10.0 ** (a / 20.0)
    X = np.fft.rfft(x.astype(np.float64), n=nfft)
    y = np.fft.irfft(X * w, n=nfft)[:n]
    return y


def _a_weighted_leq(pcm_pa: np.ndarray, fs: float, channels: list[str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for i, name in enumerate(channels):
        if i >= pcm_pa.shape[1]:
            break
        y = _a_weight_filter(pcm_pa[:, i], fs)
        rms = float(np.sqrt(np.mean(np.square(y))))
        out[name] = _db_from_pa(rms)
    return out


def _correlation_matrix(pcm_pa: np.ndarray, channels: list[str]) -> list[list[float]]:
    n = min(pcm_pa.shape[1], len(channels))
    if n == 0:
        return []
    if n == 1:
        return [[1.0]]
    data = pcm_pa[:, :n].astype(np.float64)
    if data.shape[0] < 2:
        return [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
    c = np.atleast_2d(np.corrcoef(data, rowvar=False))
    return [[float(c[i, j]) for j in range(n)] for i in range(n)]


def _coherence_phase_1khz(
    pcm_pa: np.ndarray, fs: float, channels: list[str]
) -> tuple[dict[str, float], dict[str, float]]:
    nperseg = 2048
    hop = 512
    target = 1000.0
    n_ch = min(pcm_pa.shape[1], len(channels))
    if n_ch == 0 or pcm_pa.shape[0] < nperseg:
        z = {channels[i]: 0.0 for i in range(n_ch)}
        return z, dict(z)
    window = np.hanning(nperseg)
    freqs = np.fft.rfftfreq(nperseg, d=1.0 / fs)
    k = int(np.argmin(np.abs(freqs - target)))
    specs: list[np.ndarray] = []
    for i in range(n_ch):
        x = pcm_pa[:, i].astype(np.float64)
        frames = []
        for s in range(0, len(x) - nperseg + 1, hop):
            frames.append(np.fft.rfft(x[s : s + nperseg] * window)[k])
        specs.append(np.asarray(frames, dtype=np.complex128))
    ref = specs[0]
    coh: dict[str, float] = {}
    phase: dict[str, float] = {}
    for i in range(n_ch):
        a, b = ref, specs[i]
        num = np.abs(np.mean(a * np.conj(b))) ** 2
        den = float(np.mean(np.abs(a) ** 2) * np.mean(np.abs(b) ** 2)) + 1e-30
        coh[channels[i]] = float(np.clip(num / den, 0.0, 1.0))
        ang = np.angle(np.mean(b * np.conj(a)))
        phase[channels[i]] = float(np.degrees(ang))
    return coh, phase


def _level_class(leq_mean: float) -> str:
    if leq_mean < LEVEL_CLASS_THRESHOLDS_DB[0]:
        return "low"
    if leq_mean < LEVEL_CLASS_THRESHOLDS_DB[1]:
        return "medium"
    if leq_mean < LEVEL_CLASS_THRESHOLDS_DB[2]:
        return "high"
    return "very_high"


def _balance_grade(spread: float) -> str:
    if spread < 1.0:
        return "excellent"
    if spread < 3.0:
        return "good"
    if spread < 6.0:
        return "fair"
    return "poor"


def _ensure_run_inputs(run_root: Path, source_dir: Path | None) -> None:
    """Copy head_meta / pcm into run root when missing but available on source."""
    if source_dir is None:
        return
    for name in ("head_meta.json", "pcm_pa.npy"):
        dest = run_root / name
        src = source_dir / name
        if not dest.is_file() and src.is_file():
            dest.write_bytes(src.read_bytes())


def derivation_map() -> dict[str, str]:
    return {item["id"]: str(item["value_schema"].get("derivation") or "") for item in build_labels()}


def derive_nvh_labels(run_root: Path, *, source_dir: Path | None = None) -> dict[str, Any]:
    """Build labels_json for audio_nvh-v2 from L2 products under ``run_root``."""
    run_root = Path(run_root)
    _ensure_run_inputs(run_root, Path(source_dir) if source_dir else None)

    meta_path = run_root / "head_meta.json"
    summary_path = run_root / "audio_spec" / "summary.json"
    if not summary_path.is_file():
        raise FileNotFoundError(f"missing L2 summary: {summary_path}")
    summary = _load_json(summary_path)
    meta = _load_json(meta_path) if meta_path.is_file() else {}

    channels = _resolve_channels(summary, run_root)
    ch_summary = {str(c.get("name")): c for c in (summary.get("channels") or []) if c.get("name")}

    timelines: dict[str, list[dict[str, Any]]] = {}
    thirds: dict[str, list[dict[str, Any]]] = {}
    for ch in channels:
        timelines[ch] = _load_jsonl(run_root / "audio_spec" / ch / "spl_timeline.jsonl")
        tp = run_root / "audio_spec" / ch / "third_octave.json"
        thirds[ch] = _load_json(tp) if tp.is_file() else []

    leq_by_ch = {ch: float(ch_summary.get(ch, {}).get("leq_db") or 0.0) for ch in channels}
    rms_by_ch = {ch: float(ch_summary.get(ch, {}).get("rms_pa") or 0.0) for ch in channels}
    leq_vals = [leq_by_ch[c] for c in channels if c in leq_by_ch]
    leq_mean = float(np.mean(leq_vals)) if leq_vals else 0.0
    leq_max = float(max(leq_vals)) if leq_vals else 0.0
    leq_min = float(min(leq_vals)) if leq_vals else 0.0
    leq_spread = leq_max - leq_min
    leq_std = float(np.std(leq_vals)) if leq_vals else 0.0
    rms_mean = float(np.mean([rms_by_ch[c] for c in channels])) if channels else 0.0

    pcm_path = run_root / "pcm_pa.npy"
    pcm_pa: np.ndarray | None = None
    if pcm_path.is_file():
        pcm_pa = np.load(pcm_path)

    peak_by_ch: dict[str, float] = {}
    peak_pa_max = 0.0
    if pcm_pa is not None:
        for i, ch in enumerate(channels):
            if i >= pcm_pa.shape[1]:
                break
            pk = float(np.max(np.abs(pcm_pa[:, i])))
            peak_by_ch[ch] = pk
            peak_pa_max = max(peak_pa_max, pk)
    peak_db_max = _db_from_pa(peak_pa_max) if peak_pa_max > 0 else 0.0

    all_spl = [float(r.get("spl_db") or 0.0) for rows in timelines.values() for r in rows]
    lmax = float(max(all_spl)) if all_spl else 0.0
    lmin = float(min(all_spl)) if all_spl else 0.0
    dynamic_range = lmax - lmin
    l10 = _percentile_exceedance(all_spl, 10.0)
    l50 = _percentile_exceedance(all_spl, 50.0)
    l90 = _percentile_exceedance(all_spl, 90.0)

    ch_lmax: dict[str, float] = {}
    ch_lmin: dict[str, float] = {}
    ch_l10: dict[str, float] = {}
    ch_l90: dict[str, float] = {}
    for ch, rows in timelines.items():
        vals = [float(r.get("spl_db") or 0.0) for r in rows]
        ch_lmax[ch] = float(max(vals)) if vals else 0.0
        ch_lmin[ch] = float(min(vals)) if vals else 0.0
        ch_l10[ch] = _percentile_exceedance(vals, 10.0)
        ch_l90[ch] = _percentile_exceedance(vals, 90.0)

    ch_crest = {ch: ch_lmax.get(ch, 0.0) - leq_by_ch.get(ch, 0.0) for ch in channels}
    ch_low = {ch: _band_spl(thirds.get(ch, []), 20.0, 500.0) for ch in channels}
    ch_mid = {ch: _band_spl(thirds.get(ch, []), 500.0, 2000.0) for ch in channels}
    ch_high = {ch: _band_spl(thirds.get(ch, []), 2000.0, 20000.0) for ch in channels}
    ch_dom = {ch: _dominant_fc(thirds.get(ch, [])) for ch in channels}

    centroids = [_centroid_hz(run_root, ch) for ch in channels]
    centroid_mean = float(np.mean(centroids)) if centroids else 0.0
    # energy-weighted dominant fc across channels
    dom_num = 0.0
    dom_den = 0.0
    for ch in channels:
        fc = ch_dom[ch]
        w = _lin_from_db(leq_by_ch.get(ch, 0.0))
        dom_num += fc * w
        dom_den += w
    dominant_fc = float(dom_num / dom_den) if dom_den > 0 else 0.0

    low_db = float(np.mean([ch_low[c] for c in channels])) if channels else 0.0
    mid_db = float(np.mean([ch_mid[c] for c in channels])) if channels else 0.0
    high_db = float(np.mean([ch_high[c] for c in channels])) if channels else 0.0
    tonality = float(np.mean([_tonality_index(thirds[c]) for c in channels])) if channels else 0.0
    flatness = float(np.mean([_flatness(thirds[c]) for c in channels])) if channels else 0.0
    slope = float(np.mean([_spectral_slope_db_oct(thirds[c]) for c in channels])) if channels else 0.0

    steady, _, steady_win = _mid_window_stats(timelines)
    active_thr = leq_mean - 10.0
    active_n = sum(1 for s in all_spl if s > active_thr)
    active_ratio = float(active_n / len(all_spl)) if all_spl else 0.0
    mod_idx = _modulation_index(timelines)
    onsets = _onset_count(timelines)
    transients = _transient_events(timelines, leq_mean)

    # spatial from Leq linear power
    def _e(ch: str) -> float:
        return _lin_from_db(leq_by_ch.get(ch, 0.0))

    e_vl, e_vr, e_hl, e_hr = _e("VL"), _e("VR"), _e("HL"), _e("HR")
    e_left = (e_vl + e_hl) / 2.0
    e_right = (e_vr + e_hr) / 2.0
    e_front = (e_vl + e_vr) / 2.0
    e_back = (e_hl + e_hr) / 2.0
    lr_imb = 10.0 * math.log10(max(e_left, 1e-30) / max(e_right, 1e-30))
    fb_imb = 10.0 * math.log10(max(e_front, 1e-30) / max(e_back, 1e-30))
    max_delta = 0.0
    for a in channels:
        for b in channels:
            max_delta = max(max_delta, abs(leq_by_ch[a] - leq_by_ch[b]))
    centroid_lr = (e_left - e_right) / max(e_left + e_right, 1e-30)
    centroid_fb = (e_front - e_back) / max(e_front + e_back, 1e-30)

    corr = _correlation_matrix(pcm_pa, channels) if pcm_pa is not None else []
    fs = float(summary.get("fs_hz") or meta.get("fs_hz") or 44100.0)
    if pcm_pa is not None:
        coh, phase = _coherence_phase_1khz(pcm_pa, fs, channels)
        a_leq = _a_weighted_leq(pcm_pa, fs, channels)
    else:
        coh = {ch: 0.0 for ch in channels}
        phase = {ch: 0.0 for ch in channels}
        a_leq = {ch: leq_by_ch.get(ch, 0.0) for ch in channels}

    # derived artifact files under audio_spec/
    matrix = {ch: thirds.get(ch, []) for ch in channels}
    _write_json(run_root / "audio_spec" / "third_octave_matrix.json", matrix)
    peaks = _peak_list(run_root, channels)
    _write_json(run_root / "audio_spec" / "derived" / "peak_list.json", peaks)
    tonal = _tonal_components(peaks)
    _write_json(run_root / "audio_spec" / "derived" / "tonal_components.json", tonal)
    _write_json(run_root / "audio_spec" / "derived" / "transient_events.json", transients)
    _write_json(run_root / "audio_spec" / "derived" / "correlation_matrix.json", corr)

    third_map = {ch: f"audio_spec/{ch}/third_octave.json" for ch in channels}
    stft_map = {ch: f"audio_spec/{ch}/stft_mag.npy" for ch in channels}
    mel_map = {ch: f"audio_spec/{ch}/mel_matrix.npy" for ch in channels}
    timeline_map = {ch: f"audio_spec/{ch}/spl_timeline.jsonl" for ch in channels}
    wave_map = {ch: f"audio_spec/{ch}/waveform.json" for ch in channels}
    _write_json(run_root / "audio_spec" / "derived" / "third_octave_index.json", third_map)
    _write_json(run_root / "audio_spec" / "derived" / "stft_ref_map.json", stft_map)
    _write_json(run_root / "audio_spec" / "derived" / "mel_ref_map.json", mel_map)
    _write_json(run_root / "audio_spec" / "derived" / "spl_timeline_index.json", timeline_map)
    _write_json(run_root / "audio_spec" / "derived" / "waveform_index.json", wave_map)

    fmt = str(meta.get("format") or "other")
    if fmt not in ("head_acoustics_hdf_v4", "wav", "other"):
        fmt = "other"
    unit = str(meta.get("unit") or summary.get("unit") or "Pa")
    if unit != "Pa":
        unit = "Pa"
    ch_names_meta = [str(c.get("name") or "") for c in (meta.get("channels") or [])]
    layout = "VL_VR_HL_HR" if ch_names_meta[:4] == list(CH_NAMES) or channels[:4] == list(CH_NAMES) else "other"

    labels: dict[str, Any] = {
        "nvh.meta.format": fmt,
        "nvh.meta.fs_hz": float(meta.get("fs_hz") or summary.get("fs_hz") or fs),
        "nvh.meta.duration_s": float(meta.get("duration_s") or summary.get("duration_s") or 0.0),
        "nvh.meta.n_channels": int(meta.get("n_channels") or summary.get("n_channels") or len(channels)),
        "nvh.meta.unit": unit,
        "nvh.meta.channel_layout": layout,
        "nvh.meta.channels": meta.get("channels")
        or [{"name": ch, "map_factor": 1.0} for ch in channels],
        "nvh.clip.spl.leq_db_mean": leq_mean,
        "nvh.clip.spl.leq_db_max": leq_max,
        "nvh.clip.spl.leq_db_min": leq_min,
        "nvh.clip.spl.leq_db_spread": leq_spread,
        "nvh.clip.spl.leq_db_std": leq_std,
        "nvh.clip.spl.rms_pa_mean": rms_mean,
        "nvh.clip.spl.peak_pa_max": peak_pa_max,
        "nvh.clip.spl.peak_db_max": peak_db_max,
        "nvh.clip.spl.dynamic_range_db": dynamic_range,
        "nvh.clip.spl.level_class": _level_class(leq_mean),
        "nvh.clip.spec.centroid_hz_mean": centroid_mean,
        "nvh.clip.spec.dominant_fc_hz": dominant_fc,
        "nvh.clip.spec.low_mid_high_ratio": {
            "low_db": low_db,
            "mid_db": mid_db,
            "high_db": high_db,
        },
        "nvh.clip.spec.tonality_index": tonality,
        "nvh.clip.spec.broadband_flatness": flatness,
        "nvh.clip.spec.spectral_slope_db_oct": slope,
        "nvh.clip.time.lmax_db": lmax,
        "nvh.clip.time.lmin_db": lmin,
        "nvh.clip.time.l10_db": l10,
        "nvh.clip.time.l50_db": l50,
        "nvh.clip.time.l90_db": l90,
        "nvh.clip.time.crest_factor_db": lmax - leq_mean,
        "nvh.clip.time.steady_state": bool(steady),
        "nvh.clip.time.active_ratio": active_ratio,
        "nvh.ch.leq_db": _ch_map(leq_by_ch),
        "nvh.ch.lmax_db": _ch_map(ch_lmax),
        "nvh.ch.lmin_db": _ch_map(ch_lmin),
        "nvh.ch.l10_db": _ch_map(ch_l10),
        "nvh.ch.l90_db": _ch_map(ch_l90),
        "nvh.ch.peak_pa": _ch_map(peak_by_ch),
        "nvh.ch.rms_pa": _ch_map(rms_by_ch),
        "nvh.ch.crest_factor_db": _ch_map(ch_crest),
        "nvh.ch.low_band_db": _ch_map(ch_low),
        "nvh.ch.mid_band_db": _ch_map(ch_mid),
        "nvh.ch.high_band_db": _ch_map(ch_high),
        "nvh.ch.dominant_fc_hz": _ch_map(ch_dom),
        "nvh.band.third_octave": _json_ref("audio_spec/derived/third_octave_index.json", run_root),
        "nvh.band.third_octave_matrix": _json_ref("audio_spec/third_octave_matrix.json", run_root),
        "nvh.band.peak_list": _json_ref("audio_spec/derived/peak_list.json", run_root),
        "nvh.band.tonal_components": _json_ref("audio_spec/derived/tonal_components.json", run_root),
        "nvh.band.stft_ref": _json_ref("audio_spec/derived/stft_ref_map.json", run_root),
        "nvh.band.mel_ref": _json_ref("audio_spec/derived/mel_ref_map.json", run_root),
        "nvh.band.a_weighted_leq_db": _ch_map(a_leq),
        "nvh.time.spl_timeline_ref": _json_ref("audio_spec/derived/spl_timeline_index.json", run_root),
        "nvh.time.steady_window": steady_win,
        "nvh.time.transient_events": _json_ref("audio_spec/derived/transient_events.json", run_root),
        "nvh.time.modulation_index": mod_idx,
        "nvh.time.onset_count": onsets,
        "nvh.time.waveform_ref": _json_ref("audio_spec/derived/waveform_index.json", run_root),
        "nvh.spatial.lr_imbalance_db": float(lr_imb),
        "nvh.spatial.fb_imbalance_db": float(fb_imb),
        "nvh.spatial.max_interchannel_delta_db": float(max_delta),
        "nvh.spatial.energy_centroid_lr": float(centroid_lr),
        "nvh.spatial.energy_centroid_fb": float(centroid_fb),
        "nvh.spatial.correlation_matrix": _json_ref(
            "audio_spec/derived/correlation_matrix.json", run_root
        ),
        "nvh.spatial.coherence_1khz": _ch_map(coh),
        "nvh.spatial.phase_diff_deg_1khz": _ch_map(phase),
        "nvh.spatial.channel_balance_grade": _balance_grade(leq_spread),
        "nvh.spatial.symmetry_flag": bool(abs(lr_imb) < 2.0),
    }

    # Drop human / non-seeded semi keys if any slipped in
    human_or_skip = {
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
    for key in list(labels.keys()):
        if key in human_or_skip:
            labels.pop(key, None)

    labels["_meta"] = {
        "taxonomy_version_code": VERSION_CODE,
        "deriver_version": DERIVER_VERSION,
        "derived_at": _utc_now_iso(),
        "label_source": "derive_nvh_labels",
    }
    return labels


def persist_nvh_labels_artifact(run_root: Path, labels: dict[str, Any]) -> Path:
    path = Path(run_root) / "nvh_labels.json"
    _write_json(path, labels)
    return path


def apply_nvh_labels_to_facts(
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    labels: dict[str, Any],
    update_platform_run: bool = True,
) -> None:
    """Write fact_clip_label and optionally platform_run.y_json.

    Binds ``taxonomy_version_id`` to draft/published ``audio_nvh-v2`` by code —
    does **not** call ``publish_version`` (would archive OMS published).
    """
    from hmi.clip_facts import upsert_clip_label
    from hmi.local.nvh_ai_label import resolve_audio_nvh_taxonomy_version_id
    from hmi.platform.store import put_run_y

    tax_vid = resolve_audio_nvh_taxonomy_version_id()
    meta = labels.get("_meta") if isinstance(labels.get("_meta"), dict) else {}
    model_version = str(
        meta.get("ai_label_version") or meta.get("deriver_version") or DERIVER_VERSION
    )
    label_source = "derive"
    if meta.get("ai_label_version"):
        label_source = "derive+ai_sem"
    if "human" in str(meta.get("label_source") or "") and "human" not in label_source:
        label_source = f"{label_source}+human"
    upsert_clip_label(
        clip_id,
        run_id,
        ds=ds,
        labels_json=labels,
        taxonomy_version_id=tax_vid,
        model_version=model_version,
        label_source=label_source,
        multi_ai_meta_json={
            "layout_version": "audio_nvh_v2",
            "deriver_version": DERIVER_VERSION,
            "taxonomy_version_code": VERSION_CODE,
            "taxonomy_version_id": tax_vid,
            "ai_label_version": meta.get("ai_label_version"),
            "ai_model": meta.get("ai_model"),
            "ai_mode": meta.get("ai_mode"),
        },
    )
    if update_platform_run:
        try:
            put_run_y(run_id, labels)
        except Exception:
            # pipeline-only runs may lack platform_run row
            pass
