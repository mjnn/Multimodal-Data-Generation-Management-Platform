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


def _files_identical(a: Path, b: Path) -> bool:
    """Fast same-content check for mis-copied plain==bbox previews."""
    try:
        if not a.is_file() or not b.is_file():
            return False
        if a.resolve() == b.resolve():
            return True
        sa, sb = a.stat(), b.stat()
        if sa.st_size != sb.st_size or sa.st_size <= 0:
            return False
        # Compare in chunks; these previews are a few MB.
        with a.open("rb") as fa, b.open("rb") as fb:
            while True:
                ca = fa.read(1024 * 1024)
                cb = fb.read(1024 * 1024)
                if ca != cb:
                    return False
                if not ca:
                    return True
    except OSError:
        return False


def manifest_for_api(clip_id: str, run_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    grid_rel = str(doc.get("grid_relpath") or f"{PREVIEW_REL_DIR}/{GRID_MP4_NAME}")
    out: dict[str, Any] = {
        "mode": "mp4",
        "fps": float(doc.get("fps") or 15),
        "frame_count": int(doc.get("frame_count") or 0),
        "start_time_ns": int(doc.get("start_time_ns") or 0),
        "end_time_ns": int(doc.get("end_time_ns") or 0),
        "grid_url": assets.local_file_url(clip_id, run_id, grid_rel) if grid_rel else "",
        "cameras": [],
        "has_bbox_preview": False,
        # True only when encode_plain (or equivalent) produced distinct plain camera MP4s.
        "has_plain_preview": False,
    }
    cams = doc.get("cameras")
    cams_bbox = doc.get("cameras_bbox") if isinstance(doc.get("cameras_bbox"), dict) else {}
    bbox_by_cam: dict[str, str] = {}
    if isinstance(cams_bbox, dict):
        for cam, info in cams_bbox.items():
            if not isinstance(info, dict):
                continue
            rel = str(info.get("relpath") or "")
            if rel:
                bbox_by_cam[str(cam).lower()] = rel

    if isinstance(cams, dict):
        for cam, info in sorted(cams.items()):
            if not isinstance(info, dict):
                continue
            rel = str(info.get("relpath") or "")
            if not rel:
                continue
            cam_key = str(cam).lower()
            bbox_rel = bbox_by_cam.get(cam_key)
            # Legacy bug: import copied bbox MP4 into plain name — treat as bbox-only.
            if bbox_rel and _files_identical(
                artifact_path(clip_id, run_id, rel),
                artifact_path(clip_id, run_id, bbox_rel),
            ):
                continue
            entry: dict[str, Any] = {
                "camera": cam_key,
                "url": assets.local_file_url(clip_id, run_id, rel),
                "frame_count": int(info.get("frame_count") or 0),
            }
            out["has_plain_preview"] = True
            if bbox_rel:
                entry["bbox_url"] = assets.local_file_url(clip_id, run_id, bbox_rel)
                out["has_bbox_preview"] = True
            out["cameras"].append(entry)

    # Bbox cameras missing a real plain twin: expose bbox_url only.
    if isinstance(cams_bbox, dict):
        have = {c["camera"] for c in out["cameras"]}
        for cam, info in sorted(cams_bbox.items()):
            cam_key = str(cam).lower()
            if cam_key in have or not isinstance(info, dict):
                continue
            rel = str(info.get("relpath") or "")
            if not rel:
                continue
            out["cameras"].append(
                {
                    "camera": cam_key,
                    "url": "",
                    "bbox_url": assets.local_file_url(clip_id, run_id, rel),
                    "frame_count": int(info.get("frame_count") or 0),
                }
            )
            out["has_bbox_preview"] = True
    return out


def sampled_timestamps_from_manifest(doc: dict[str, Any]) -> list[int]:
    """Clip-level preview: no per-frame scrub ticks."""
    start = int(doc.get("start_time_ns") or 0)
    end = int(doc.get("end_time_ns") or start)
    if end <= start:
        return [start]
    return [start, end]
