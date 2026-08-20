"""Parse HEAD acoustics HDF v4 time-data .dat (SQuadriga / ArtemiS)."""

from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

import numpy as np

HEAD_MAGIC = b"HEAD acoustics"


def is_head_dat(data: bytes) -> bool:
    return HEAD_MAGIC in data[:512]


def _header_field(header: str, key: str) -> str | None:
    m = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", header, re.MULTILINE)
    if not m:
        return None
    return m.group(1).rstrip("\r")


def parse_head_dat_bytes(data: bytes) -> dict[str, Any]:
    if not is_head_dat(data):
        raise ValueError("not a HEAD acoustics .dat file")
    header = data[:65536].decode("latin-1", errors="replace")
    start = int(_header_field(header, "start of data") or "65536")
    n_ch = int(_header_field(header, "nbr of channel") or "0")
    n_scans = int(_header_field(header, "nbr of scans") or "0")
    dt = float(_header_field(header, "delta value") or "0")
    if n_ch < 1 or n_scans < 1 or dt <= 0:
        raise ValueError("HEAD .dat header missing channel/scan/delta")
    impl = (_header_field(header, "implementation type") or "FLOAT32").upper()
    if impl != "FLOAT32":
        raise ValueError(f"unsupported HEAD implementation type={impl}")
    width = 4
    nbytes = n_scans * n_ch * width
    blob = data[start : start + nbytes]
    if len(blob) != nbytes:
        raise ValueError(f"HEAD .dat truncated: expected {nbytes} bytes at {start}, got {len(blob)}")
    pcm = np.frombuffer(blob, dtype="<f4").reshape(n_scans, n_ch).copy()

    channels: list[dict[str, Any]] = []
    blocks = re.split(r"^channel definition:\s*", header, flags=re.MULTILINE)
    for block in blocks[1:]:
        m_name = re.search(r"^name str:\s*(.*?)\s*$", block, re.MULTILINE)
        m_factor = re.search(r"^map factor:\s*([0-9eE.+-]+)\s*$", block, re.MULTILINE)
        m_cal = re.search(r"^calibration:\s*([0-9eE.+-]+)\s*$", block, re.MULTILINE)
        m_idx = re.search(r"^(\d+)\s*$", block)
        name_s = (m_name.group(1).strip() if m_name else "") or f"ch{len(channels)+1}"
        factor = float(m_factor.group(1)) if m_factor else 1.0
        cal = float(m_cal.group(1)) if m_cal else None
        idx = int(m_idx.group(1)) if m_idx else len(channels) + 1
        channels.append(
            {
                "index": idx,
                "name": name_s,
                "map_factor": factor,
                "calibration": cal,
            }
        )
    if len(channels) != n_ch:
        channels = [
            {"index": i + 1, "name": f"ch{i+1}", "map_factor": 1.0, "calibration": None}
            for i in range(n_ch)
        ]

    factors = np.array([float(c["map_factor"]) for c in channels], dtype=np.float64)
    pcm_pa = (pcm.astype(np.float64) * factors.reshape(1, -1)).astype(np.float32)
    fs = 1.0 / dt
    return {
        "fs_hz": fs,
        "n_channels": n_ch,
        "n_scans": n_scans,
        "duration_s": n_scans / fs,
        "delta_t": dt,
        "start_of_data": start,
        "channels": channels,
        "pcm_raw": pcm,
        "pcm_pa": pcm_pa,
        "kind": (_header_field(header, "kind") or "").strip(),
        "byte_order": (_header_field(header, "byte order") or "").strip(),
        "recorded_at": None,
    }


def write_ieee_float_wav(path: Path, pcm: np.ndarray, fs: float) -> None:
    """Write WAVE_FORMAT_IEEE_FLOAT (format=3) WAV. pcm shape (n, ch)."""
    arr = np.asarray(pcm, dtype=np.float32)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    n_frames, n_ch = arr.shape
    sr = int(round(fs))
    data = arr.astype("<f4", copy=False).tobytes()
    byte_rate = sr * n_ch * 4
    block_align = n_ch * 4
    fmt = struct.pack(
        "<HHIIHHH",
        3,
        n_ch,
        sr,
        byte_rate,
        block_align,
        32,
        0,
    )
    # WAVEFORMATEX extra size 0
    riff_size = 4 + (8 + 18) + (8 + len(data))
    with path.open("wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", riff_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<I", 18))
        f.write(fmt)
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)


def persist_head_dat_package(dest_dir: Path, filename: str, data: bytes) -> dict[str, Any]:
    """Write original .dat + calibrated PCM + per-channel wavs + meta (no pipeline rows)."""
    parsed = parse_head_dat_bytes(data)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / "source.dat").write_bytes(data)
    pcm_pa: np.ndarray = parsed["pcm_pa"]
    fs = float(parsed["fs_hz"])
    np.save(dest_dir / "pcm_pa.npy", pcm_pa)
    write_ieee_float_wav(dest_dir / "audio.wav", pcm_pa, fs)
    ch_dir = dest_dir / "channels"
    ch_dir.mkdir(exist_ok=True)
    names: list[str] = []
    for i, ch in enumerate(parsed["channels"]):
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(ch["name"])).strip("_") or f"ch{i+1}"
        names.append(name)
        write_ieee_float_wav(ch_dir / f"{name}.wav", pcm_pa[:, i], fs)
    meta = {
        "format": "head_acoustics_hdf_v4",
        "source_filename": filename,
        "fs_hz": fs,
        "n_channels": parsed["n_channels"],
        "n_scans": parsed["n_scans"],
        "duration_s": parsed["duration_s"],
        "channels": parsed["channels"],
        "channel_files": [f"channels/{n}.wav" for n in names],
        "pcm_pa": "pcm_pa.npy",
        "audio": "audio.wav",
        "unit": "Pa",
    }
    (dest_dir / "head_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta
