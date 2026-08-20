"""Audio NVH overview / explorer bootstrap from run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.data_source import artifact_path
from hmi.local import assets


CH_ORDER = ("VL", "VR", "HL", "HR")


def _read_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _channel_dirs(spec_root: Path) -> list[str]:
    found = [p.name for p in spec_root.iterdir() if p.is_dir()] if spec_root.is_dir() else []
    ordered = [c for c in CH_ORDER if c in found]
    for name in sorted(found):
        if name not in ordered:
            ordered.append(name)
    return ordered


def build_audio_nvh_bootstrap(clip_id: str, run_id: str) -> dict[str, Any] | None:
    """Return explorer payload for audio_nvh_timeline, or None if no audio_spec."""
    root = artifact_path(clip_id, run_id, "")
    spec_root = root / "audio_spec"
    summary = _read_json(spec_root / "summary.json") or _read_json(root / "audio_spec_summary.json")
    if summary is None and not spec_root.is_dir():
        return None

    summary = summary or {}
    channels_meta = {str(c.get("name")): c for c in (summary.get("channels") or []) if isinstance(c, dict)}
    names = _channel_dirs(spec_root)
    if not names and channels_meta:
        names = [n for n in CH_ORDER if n in channels_meta] or list(channels_meta.keys())

    channels: list[dict[str, Any]] = []
    for name in names:
        ch_dir = spec_root / name
        meta = channels_meta.get(name) or {}
        entry: dict[str, Any] = {
            "name": name,
            "leq_db": float(meta["leq_db"]) if meta.get("leq_db") is not None else None,
            "rms_pa": float(meta["rms_pa"]) if meta.get("rms_pa") is not None else None,
            "mel_url": None,
            "stft_url": None,
            "waveform_url": None,
            "spl_timeline_url": None,
            "third_octave_url": None,
        }
        if (ch_dir / "mel.png").is_file():
            entry["mel_url"] = assets.local_file_url(clip_id, run_id, f"audio_spec/{name}/mel.png")
        if (ch_dir / "stft.png").is_file():
            entry["stft_url"] = assets.local_file_url(clip_id, run_id, f"audio_spec/{name}/stft.png")
        if (ch_dir / "waveform.json").is_file():
            entry["waveform_url"] = assets.local_file_url(clip_id, run_id, f"audio_spec/{name}/waveform.json")
        if (ch_dir / "spl_timeline.jsonl").is_file():
            entry["spl_timeline_url"] = assets.local_file_url(
                clip_id, run_id, f"audio_spec/{name}/spl_timeline.jsonl"
            )
        if (ch_dir / "third_octave.json").is_file():
            entry["third_octave_url"] = assets.local_file_url(
                clip_id, run_id, f"audio_spec/{name}/third_octave.json"
            )
        channels.append(entry)

    audio_url = None
    for rel in ("preview/audio.wav", "audio.wav", "audio_spec/../preview/audio.wav"):
        if artifact_path(clip_id, run_id, rel).is_file():
            audio_url = assets.local_file_url(clip_id, run_id, "preview/audio.wav" if "preview" in rel else rel)
            break
    # Prefer mixdown wav from source package if preview missing
    if audio_url is None and (root / "preview" / "audio.wav").is_file():
        audio_url = assets.local_file_url(clip_id, run_id, "preview/audio.wav")

    labels: dict[str, Any] = {}
    for rel in ("nvh_labels.json", "audio_spec/nvh_labels.json"):
        doc = _read_json(root / rel)
        if isinstance(doc, dict):
            labels = doc.get("labels") if isinstance(doc.get("labels"), dict) else doc
            break

    duration_s = float(summary.get("duration_s") or 0.0)
    if duration_s <= 0 and channels:
        # Infer from first channel SPL timeline length
        first = names[0] if names else None
        if first:
            rows = _read_jsonl(spec_root / first / "spl_timeline.jsonl")
            if rows:
                duration_s = float(rows[-1].get("t_s") or 0.0) + 0.125

    return {
        "clip_id": clip_id,
        "run_id": run_id,
        "view": "audio_nvh_timeline",
        "fs_hz": float(summary.get("fs_hz") or 0.0) or None,
        "duration_s": duration_s,
        "unit": summary.get("unit") or "Pa",
        "channels": channels,
        "audio_url": audio_url,
        "summary": summary,
        "labels": labels,
        "thumb_url": next((c["mel_url"] for c in channels if c.get("mel_url")), None),
        "leq_db_mean": (
            sum(float(c["leq_db"]) for c in channels if c.get("leq_db") is not None)
            / max(1, sum(1 for c in channels if c.get("leq_db") is not None))
            if any(c.get("leq_db") is not None for c in channels)
            else None
        ),
    }


def audio_nvh_overview_extras(clip_id: str, run_id: str) -> dict[str, Any]:
    """Lightweight fields for overview table rows."""
    boot = build_audio_nvh_bootstrap(clip_id, run_id)
    if not boot:
        return {}
    return {
        "duration_sec": float(boot.get("duration_s") or 0.0),
        "nvh_leq_db_mean": boot.get("leq_db_mean"),
        "nvh_thumb_url": boot.get("thumb_url"),
        "nvh_channel_count": len(boot.get("channels") or []),
        "overview_view": "audio_nvh_timeline",
    }
