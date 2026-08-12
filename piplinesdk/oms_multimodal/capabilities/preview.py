"""Capability: preview — 整理 preview/ 目录（sdk_upload 前）。"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from .types import RunContext

_CAM_PLAIN_RE = re.compile(r"^clip_preview_(camera\d+)$", re.IGNORECASE)
_CAM_BBOX_RE = re.compile(r"^clip_preview_bbox_(camera\d+)$", re.IGNORECASE)


def _copy_clip_media(clip_dir: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    for mp4 in clip_dir.glob("clip_preview_*.mp4"):
        shutil.copy2(mp4, dest_dir / mp4.name)
    wav = clip_dir / "audio.wav"
    if wav.is_file():
        shutil.copy2(wav, dest_dir / "audio.wav")


def _iter_clip_dirs(work: Path) -> list[Path]:
    clips_roots: list[Path] = []
    direct = work / "clips"
    if direct.is_dir():
        clips_roots.append(direct)
    for child in work.iterdir():
        nested = child / "clips"
        if nested.is_dir() and nested not in clips_roots:
            clips_roots.append(nested)

    clip_dirs: list[Path] = []
    for clips_root in clips_roots:
        for clip_dir in sorted(clips_root.iterdir()):
            if clip_dir.is_dir():
                clip_dirs.append(clip_dir)
    return clip_dirs


def _split_cameras_from_preview_dir(
    preview_dir: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return (plain cameras, bbox cameras) keyed by camera0..N."""
    cameras: dict[str, dict[str, Any]] = {}
    cameras_bbox: dict[str, dict[str, Any]] = {}
    for mp4 in sorted(preview_dir.glob("clip_preview_*.mp4")):
        stem = mp4.stem
        bbox_match = _CAM_BBOX_RE.match(stem)
        if bbox_match:
            cam = bbox_match.group(1).lower()
            cameras_bbox[cam] = {
                "relpath": f"preview/{mp4.name}",
                "frame_count": 0,
                "variant": "bbox",
            }
            continue
        plain_match = _CAM_PLAIN_RE.match(stem)
        if plain_match:
            cam = plain_match.group(1).lower()
            cameras[cam] = {
                "relpath": f"preview/{mp4.name}",
                "frame_count": 0,
                "variant": "plain",
            }
            continue
        # Legacy single-file names
        if stem.lower() == "clip_preview_bbox":
            cameras_bbox["camera0"] = {
                "relpath": f"preview/{mp4.name}",
                "frame_count": 0,
                "variant": "bbox",
            }
        elif stem.lower() == "clip_preview":
            cameras.setdefault(
                "camera0",
                {
                    "relpath": f"preview/{mp4.name}",
                    "frame_count": 0,
                    "variant": "plain",
                },
            )
    return cameras, cameras_bbox


def _cameras_from_preview_dir(preview_dir: Path) -> dict[str, dict[str, Any]]:
    """Plain cameras only (backward compatible)."""
    cameras, _ = _split_cameras_from_preview_dir(preview_dir)
    return cameras


def write_preview_manifest(
    preview_dir: Path,
    *,
    cameras: dict[str, dict[str, Any]] | None = None,
    cameras_bbox: dict[str, dict[str, Any]] | None = None,
    clip_count: int = 0,
    extra: dict[str, Any] | None = None,
) -> Path:
    """Write preview/manifest.json for HMI sdk_v1 timeline mode."""
    preview_dir.mkdir(parents=True, exist_ok=True)
    if cameras is None or cameras_bbox is None:
        plain, bbox = _split_cameras_from_preview_dir(preview_dir)
        cams = cameras if cameras is not None else plain
        cams_bbox = cameras_bbox if cameras_bbox is not None else bbox
    else:
        cams = cameras
        cams_bbox = cameras_bbox
    doc: dict[str, Any] = {
        "mode": "mp4",
        "fps": 1.0,
        "frame_count": 0,
        "start_time_ns": 0,
        "end_time_ns": 0,
        "grid_relpath": "",
        "cameras": cams,
        "cameras_bbox": cams_bbox,
        "source": "oms_multimodal.materialize_preview",
        "camera_count": len(cams),
        "bbox_camera_count": len(cams_bbox),
        "clip_count": clip_count,
    }
    if (preview_dir / "audio.wav").is_file():
        doc["audio_relpath"] = "preview/audio.wav"
    if extra:
        doc.update(extra)
    path = preview_dir / "manifest.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def materialize_preview(ctx: RunContext) -> Path:
    """将 _sdk_work 下 clip_preview_*.mp4、audio.wav 拷到 run_dir/preview/。

    extract 把产物写在 ``work_dir/<bag_stem>/clips/``（见 RosbagExtractor），
    因此需同时兼容 ``work_dir/clips`` 与 ``work_dir/*/clips``。

    多 clip 时写入 ``preview/{clip_dir.name}/``，并把**第一个** clip 提升到
    扁平 ``preview/``（HMI 默认读扁平路径），避免同名覆盖。
    """
    preview_dir = ctx.run_dir / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    work = ctx.work_dir
    if not work.is_dir():
        write_preview_manifest(preview_dir, cameras={}, cameras_bbox={}, clip_count=0)
        return preview_dir

    clip_dirs = _iter_clip_dirs(work)
    if not clip_dirs:
        write_preview_manifest(preview_dir, cameras={}, cameras_bbox={}, clip_count=0)
        return preview_dir

    if len(clip_dirs) == 1:
        _copy_clip_media(clip_dirs[0], preview_dir)
    else:
        for clip_dir in clip_dirs:
            _copy_clip_media(clip_dir, preview_dir / clip_dir.name)
        # Promote primary clip to flat preview paths for HMI / run.json contract.
        _copy_clip_media(clip_dirs[0], preview_dir)

    # bboxes.jsonl is already written to ctx.bboxes_path (= run_dir/bboxes.jsonl)
    # by annotate_bboxes; do not shutil.copy2 onto itself (WinError 32 on Windows).

    write_preview_manifest(preview_dir, clip_count=len(clip_dirs))
    return preview_dir
