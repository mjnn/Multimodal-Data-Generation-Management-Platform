"""Read/write preview/manifest.json for MP4 timeline mode (sdk_v1)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.data_source import artifact_path
from hmi.local import assets
from hmi.media.preview_mp4 import GRID_MP4_NAME, LEGACY_PREVIEW_REL_DIR, MANIFEST_NAME, PREVIEW_REL_DIR

MANIFEST_REL = f"{PREVIEW_REL_DIR}/{MANIFEST_NAME}"
LEGACY_MANIFEST_REL = f"{LEGACY_PREVIEW_REL_DIR}/{MANIFEST_NAME}"


def manifest_path(clip_id: str, run_id: str) -> Path:
    primary = artifact_path(clip_id, run_id, MANIFEST_REL)
    if primary.is_file():
        return primary
    return artifact_path(clip_id, run_id, LEGACY_MANIFEST_REL)


def load_preview_manifest(clip_id: str, run_id: str) -> dict[str, Any] | None:
    path = manifest_path(clip_id, run_id)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


def write_preview_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def manifest_for_api(clip_id: str, run_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    grid_rel = str(doc.get("grid_relpath") or f"{PREVIEW_REL_DIR}/{GRID_MP4_NAME}")
    out: dict[str, Any] = {
        "mode": "mp4",
        "fps": float(doc.get("fps") or 15),
        "frame_count": int(doc.get("frame_count") or 0),
        "start_time_ns": int(doc.get("start_time_ns") or 0),
        "end_time_ns": int(doc.get("end_time_ns") or 0),
        "grid_url": assets.local_file_url(clip_id, run_id, grid_rel),
        "cameras": [],
    }
    cams = doc.get("cameras")
    if isinstance(cams, dict):
        for cam, info in sorted(cams.items()):
            if not isinstance(info, dict):
                continue
            rel = str(info.get("relpath") or "")
            if not rel:
                continue
            out["cameras"].append(
                {
                    "camera": cam,
                    "url": assets.local_file_url(clip_id, run_id, rel),
                    "frame_count": int(info.get("frame_count") or 0),
                }
            )
    return out


def sampled_timestamps_from_manifest(doc: dict[str, Any]) -> list[int]:
    """Clip-level preview: no per-frame scrub ticks."""
    start = int(doc.get("start_time_ns") or 0)
    end = int(doc.get("end_time_ns") or start)
    if end <= start:
        return [start]
    return [start, end]
