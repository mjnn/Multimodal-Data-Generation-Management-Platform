#!/usr/bin/env python3
"""Import local OMS multimodal runs from data/real_data into HMI local mode.

Maps SDK output into **sdk_v1** layout under `data/hmi_local/artifacts` and SQLite facts.

Usage (repo root):
  py -3 scripts/import_real_data_clips.py --reset
  py -3 scripts/import_real_data_clips.py --list
  py -3 scripts/import_real_data_clips.py --source pipeline_latest --reset
  py -3 scripts/import_real_data_clips.py --preview-mode mp4
  py -3 scripts/upload_clip_preview_to_oss.py --all-real
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH

from hmi.ai_label_hints import extract_label_hints
from hmi.app_db import db_conn, ensure_schema
from hmi.data_source import artifacts_dir
from hmi.labels_util import labels_to_clip_dict
from hmi.local import store
from hmi.media.frame_encode import encode_frame_image
from hmi.media.preview_manifest import MANIFEST_REL, write_preview_manifest
from hmi.media.preview_mp4 import (
    GRID_MP4_NAME,
    PREVIEW_REL_DIR,
    build_grid_mp4_from_camera_mp4s,
    build_grid_mp4_from_frames,
    build_single_camera_mp4,
)
from hmi.oss_layout import (
    SDK_EMBEDDINGS_JSONL,
    SDK_LABELS_JSONL,
    SDK_LAYOUT_VERSION,
    SDK_RUN_JSON_KEY,
    SDK_VIDEOS_JSONL,
)
from hmi.review.enqueue import enqueue_clip

REAL_DATA_ROOT = HMI_ROOT / "data" / "real_data"
BATCH_CONTAINER_NAMES = frozenset({"pipeline_latest"})
LOCAL_CLIP_VIDEO_NAME = "clip_preview.mp4"
LOCAL_AUDIO_NAME = "audio.wav"
DS = datetime.now(timezone.utc).strftime("%Y%m%d")
# HMI preview: mp4 = local ffmpeg + OSS upload (fast); frames = per-jpg timeline (slow upload)
DEFAULT_PREVIEW_MODE = "mp4"
DEFAULT_PREVIEW_FPS = 30.0
DEFAULT_MP4_PREVIEW_FPS = 15.0
DEFAULT_MAX_FRAMES_PER_CAMERA = 900
REAL_DATA_BAG_OSS_PREFIX = "local://real_data/"
SDK_PREVIEW_AUDIO_REL = f"{PREVIEW_REL_DIR}/audio.wav"

CAMERA_TOPIC_DIRS: tuple[tuple[str, str], ...] = (
    ("camera0_image_raw_compressed", "camera0"),
    ("camera1_image_raw_compressed", "camera1"),
    ("camera2_image_raw_compressed", "camera2"),
    ("camera3_image_raw_compressed", "camera3"),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl_first(path: Path) -> dict[str, Any]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if isinstance(row, dict):
                return row
    raise ValueError(f"empty jsonl: {path}")


def _is_importable_run_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "labels.jsonl").is_file()
        and (path / "fusion_embeddings.jsonl").is_file()
    )


def _read_clip_video_row(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / "clip_videos.jsonl"
    if not path.is_file():
        return None
    try:
        return _read_jsonl_first(path)
    except ValueError:
        return None


CLIP_OUTPUT_REL = Path("work") / "output" / "clips" / "output_0000"


def _clip_output_dir(run_dir: Path) -> Path:
    return run_dir / CLIP_OUTPUT_REL


def _topic_to_camera(topic: str) -> str:
    t = (topic or "").lower()
    if "camera3" in t:
        return "camera3"
    if "camera2" in t:
        return "camera2"
    if "camera1" in t:
        return "camera1"
    return "camera0"


def _resolve_media_path(run_dir: Path, raw: str | None) -> Path | None:
    if not raw or not str(raw).strip():
        return None
    text = str(raw).strip()
    p = Path(text)
    if p.is_file():
        return p

    candidates: list[Path] = [
        run_dir / p,
        run_dir / p.name,
        _clip_output_dir(run_dir) / p.name,
    ]
    if p.parts:
        candidates.append(run_dir / Path(*p.parts))
        try:
            idx = p.parts.index("work")
            candidates.append(run_dir / Path(*p.parts[idx:]))
        except ValueError:
            pass
        if "pipeline_latest" in p.parts:
            try:
                pl_idx = p.parts.index("pipeline_latest")
                run_name = p.parts[pl_idx + 1]
                if run_name == run_dir.name:
                    candidates.append(run_dir / Path(*p.parts[pl_idx + 2 :]))
            except (ValueError, IndexError):
                pass

    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file():
            return resolved

    for local_name in (LOCAL_CLIP_VIDEO_NAME, LOCAL_AUDIO_NAME):
        local = run_dir / local_name
        if local.is_file() and local.name == p.name:
            return local
    return None


def _camera_frame_counts(video_row: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    cfg = video_row.get("clip_video_config")
    if isinstance(cfg, dict):
        for entry in cfg.get("encoded_cameras") or []:
            if not isinstance(entry, dict):
                continue
            cam = _topic_to_camera(str(entry.get("camera_topic") or ""))
            n = int(entry.get("encoded_frame_count") or 0)
            if n > 0:
                counts[cam] = n
    return counts


def _collect_sdk_camera_videos(run_dir: Path, video_row: dict[str, Any]) -> dict[str, Path]:
    found: dict[str, Path] = {}
    paths_map = video_row.get("clip_video_paths")
    if isinstance(paths_map, dict):
        for topic, raw in paths_map.items():
            cam = _topic_to_camera(str(topic))
            resolved = _resolve_media_path(run_dir, str(raw))
            if resolved:
                found[cam] = resolved

    cfg = video_row.get("clip_video_config")
    if isinstance(cfg, dict):
        for entry in cfg.get("encoded_cameras") or []:
            if not isinstance(entry, dict):
                continue
            cam = _topic_to_camera(str(entry.get("camera_topic") or ""))
            resolved = _resolve_media_path(run_dir, str(entry.get("path") or ""))
            if resolved:
                found[cam] = resolved

    clip_dir = _clip_output_dir(run_dir)
    if clip_dir.is_dir():
        for mp4 in sorted(clip_dir.glob("clip_preview_camera*.mp4")):
            m = re.match(r"clip_preview_(camera\d+)", mp4.stem, re.I)
            if m:
                found.setdefault(m.group(1).lower(), mp4)

    if not found:
        legacy = _resolve_media_path(
            run_dir,
            str(video_row.get("clip_video_path") or ""),
        )
        if legacy:
            found[_camera_from_video_row(video_row)] = legacy
    return found


def _camera_from_video_row(video_row: dict[str, Any]) -> str:
    cfg = video_row.get("clip_video_config")
    topic = ""
    if isinstance(cfg, dict):
        topic = str(cfg.get("camera_topic") or "")
    if "camera3" in topic:
        return "camera3"
    if "camera2" in topic:
        return "camera2"
    if "camera1" in topic:
        return "camera1"
    return "camera0"


def _preview_fps_from_video_row(video_row: dict[str, Any], *, duration_sec: float) -> float:
    per_cam = _camera_frame_counts(video_row)
    if duration_sec > 0 and per_cam:
        return max(1.0, min(60.0, max(per_cam.values()) / duration_sec))
    cfg = video_row.get("clip_video_config") if isinstance(video_row.get("clip_video_config"), dict) else {}
    frame_count = int(
        video_row.get("video_frame_count")
        or video_row.get("encoded_frame_count")
        or cfg.get("encoded_frame_count")
        or 0
    )
    if duration_sec > 0 and frame_count > 0:
        return max(1.0, min(60.0, frame_count / duration_sec))
    return DEFAULT_MP4_PREVIEW_FPS


def materialize_run_media(run_dir: Path) -> dict[str, str | None]:
    """Ensure work/.../output_0000 media is present (SDK layout under run_dir)."""
    video_row = _read_clip_video_row(run_dir) or {}
    out_dir = _clip_output_dir(run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    copied: dict[str, str | None] = {"audio.wav": None}
    for cam, src in _collect_sdk_camera_videos(run_dir, video_row).items():
        dest = out_dir / f"clip_preview_{cam}.mp4"
        if src.is_file() and (
            not dest.is_file() or dest.stat().st_mtime < src.stat().st_mtime
        ):
            shutil.copy2(src, dest)
        if dest.is_file():
            copied[f"clip_preview_{cam}.mp4"] = str(dest)

    audio_src = _resolve_media_path(run_dir, str(video_row.get("audio_path") or ""))
    if audio_src and audio_src.is_file():
        dest = out_dir / "audio.wav"
        if not dest.is_file() or dest.stat().st_mtime < audio_src.stat().st_mtime:
            shutil.copy2(audio_src, dest)
        copied["audio.wav"] = str(dest)
    return copied


def _sdk_preview_mp4_name(camera: str) -> str:
    return f"clip_preview_{camera}.mp4"


def _resolve_bag_path(run_dir: Path, label_row: dict[str, Any]) -> Path:
    bag_name = str(label_row.get("bag_name") or "output.bag").strip()
    candidates: list[Path] = []
    if bag_name:
        candidates.append(run_dir / bag_name)
        candidates.append(run_dir / Path(bag_name).name)
    candidates.extend(sorted(run_dir.rglob("*.bag")))
    summary = run_dir.parent / "run_summary.json"
    if summary.is_file():
        try:
            rows = json.loads(summary.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    scene = str(row.get("scene_dir") or "")
                    if run_dir.name not in scene and run_dir.as_posix() not in scene.replace("\\", "/"):
                        continue
                    bag_raw = str(row.get("bag") or "").strip()
                    if bag_raw:
                        candidates.insert(0, Path(bag_raw))
        except (json.JSONDecodeError, OSError):
            pass
    seen: set[str] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file() and resolved.suffix.lower() == ".bag":
            return resolved
    raise FileNotFoundError(f"No .bag found for SDK import under {run_dir}")


def clip_id_from_bag(run_dir: Path, label_row: dict[str, Any]) -> str:
    bag_path = _resolve_bag_path(run_dir, label_row)
    digest = hashlib.sha256()
    with bag_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def content_hash_from_clip_id(clip_id: str) -> str:
    return clip_id.split(":", 1)[-1][:64]


def _slug(run_dir_name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]+", "_", run_dir_name).strip("_")


def run_id_for_run(run_dir_name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"rosbag-labels/real-data/{run_dir_name}"))


def display_name(run_dir: Path, _label_row: dict[str, Any] | None = None) -> str:
    return run_dir.name


def _copy_sdk_jsonl_bundle(run_dir: Path, run_root: Path) -> None:
    for name in (SDK_LABELS_JSONL, SDK_EMBEDDINGS_JSONL, SDK_VIDEOS_JSONL):
        src = run_dir / name
        if not src.is_file():
            raise FileNotFoundError(f"missing {name} under {run_dir}")
        shutil.copy2(src, run_root / name)


def _write_sdk_run_json(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    source_run_dir: str,
    bag_oss_key: str,
    ds: str,
) -> None:
    payload = {
        "layout_version": SDK_LAYOUT_VERSION,
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": ds,
        "source_run_dir": source_run_dir,
        "bag_oss_key": bag_oss_key,
        "sdk_files": {
            "labels": SDK_LABELS_JSONL,
            "embeddings": SDK_EMBEDDINGS_JSONL,
            "videos": SDK_VIDEOS_JSONL,
        },
        "preview_manifest": f"{PREVIEW_REL_DIR}/manifest.json",
        "completed_at": _utc_now(),
    }
    _write_json(run_root / SDK_RUN_JSON_KEY, payload)


def _sample_paths(paths: list[Path], n: int) -> list[Path]:
    if not paths:
        return []
    if len(paths) <= n:
        return paths
    step = max(1, len(paths) // n)
    out = paths[::step][:n]
    if paths[-1] not in out:
        out[-1] = paths[-1]
    return out


def _pick_preview_frames(
    paths: list[Path],
    duration_sec: float,
    *,
    preview_fps: float,
    max_frames: int,
) -> list[Path]:
    """Keep up to preview_fps * duration frames; SDK disk cache may already be ~30fps."""
    ordered = sorted(paths, key=lambda p: p.name)
    if not ordered:
        return []
    target = min(max_frames, max(1, int(round(duration_sec * preview_fps))))
    if len(ordered) <= target:
        return ordered
    return _sample_paths(ordered, target)


def _resolve_audio_src(run_dir: Path) -> Path | None:
    candidates = [
        run_dir / LOCAL_AUDIO_NAME,
        run_dir / "work" / "output" / "clips" / "output_0000" / "audio.wav",
        run_dir / "viewable" / "audio.wav",
    ]
    video_row = _read_clip_video_row(run_dir)
    if video_row:
        resolved = _resolve_media_path(run_dir, str(video_row.get("audio_path") or ""))
        if resolved:
            candidates.insert(0, resolved)
    for path in candidates:
        if path.is_file():
            return path
    return None


def _build_sdk_mp4_preview_media(
    run_dir: Path,
    run_root: Path,
    *,
    start_ns: int,
    end_ns: int,
    video_row: dict[str, Any],
    label_row: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None] | None:
    camera_sources = _collect_sdk_camera_videos(run_dir, video_row)
    if not camera_sources and _clip_output_dir(run_dir).is_dir():
        camera_sources = _collect_sdk_camera_videos(run_dir, video_row)
    if not camera_sources:
        legacy = _resolve_media_path(
            run_dir,
            str(video_row.get("clip_video_path") or label_row.get("clip_video_path") or ""),
        )
        if legacy:
            camera_sources = {_camera_from_video_row(video_row): legacy}
    if not camera_sources:
        return None

    duration_sec = float(
        video_row.get("duration_sec")
        or label_row.get("duration_sec")
        or max(0.001, (end_ns - start_ns) / 1e9)
    )
    preview_fps = _preview_fps_from_video_row(video_row, duration_sec=duration_sec)
    per_cam_frames = _camera_frame_counts(video_row)
    frame_count = int(video_row.get("video_frame_count") or video_row.get("frame_count") or 0)
    if not frame_count and per_cam_frames:
        frame_count = max(per_cam_frames.values())

    preview_dir = run_root / PREVIEW_REL_DIR
    preview_dir.mkdir(parents=True, exist_ok=True)

    cam_meta: dict[str, dict[str, Any]] = {}
    staged: dict[str, Path] = {}
    for cam in ("camera0", "camera1", "camera2", "camera3"):
        src = camera_sources.get(cam)
        if not src or not src.is_file():
            continue
        sdk_name = _sdk_preview_mp4_name(cam)
        dest = preview_dir / sdk_name
        shutil.copy2(src, dest)
        staged[cam] = dest
        rel = f"{PREVIEW_REL_DIR}/{sdk_name}"
        cam_meta[cam] = {
            "relpath": rel,
            "frame_count": int(per_cam_frames.get(cam) or frame_count or 0),
        }

    grid_path = preview_dir / GRID_MP4_NAME
    if len(staged) >= 2:
        build_grid_mp4_from_camera_mp4s(staged, grid_path)
    elif len(staged) == 1:
        shutil.copy2(next(iter(staged.values())), grid_path)
    else:
        return None

    grid_rel = f"{PREVIEW_REL_DIR}/{GRID_MP4_NAME}"
    manifest = {
        "mode": "mp4",
        "fps": preview_fps,
        "frame_count": frame_count,
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
        "grid_relpath": grid_rel,
        "cameras": cam_meta,
        "source": "sdk_clip_video",
        "camera_count": len(staged),
    }
    write_preview_manifest(run_root / MANIFEST_REL, manifest)

    audio_rel: str | None = None
    audio_src = _resolve_audio_src(run_dir)
    if audio_src:
        audio_rel = SDK_PREVIEW_AUDIO_REL
        dest = run_root / audio_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_src, dest)

    frame_rows: list[dict[str, Any]] = []
    for cam in sorted(staged.keys()):
        frame_rows.append(
            {
                "camera": cam,
                "frame_idx": 0,
                "timestamp_ns": start_ns,
                "image_path": cam_meta[cam]["relpath"],
            }
        )
    if not frame_rows:
        frame_rows.append(
            {
                "camera": "camera0",
                "frame_idx": 0,
                "timestamp_ns": start_ns,
                "image_path": grid_rel,
            }
        )
    return frame_rows, audio_rel


def _copy_parsed_media(
    run_dir: Path,
    run_root: Path,
    *,
    start_ns: int,
    end_ns: int,
    preview_mode: str = DEFAULT_PREVIEW_MODE,
    preview_fps: float = DEFAULT_PREVIEW_FPS,
    max_frames_per_camera: int = DEFAULT_MAX_FRAMES_PER_CAMERA,
    label_row: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    if preview_mode == "mp4":
        video_row = _read_clip_video_row(run_dir)
        label_row = label_row or {}
        if video_row or label_row.get("clip_video_path") or _clip_output_dir(run_dir).is_dir():
            merged_video = video_row or {}
            sdk = _build_sdk_mp4_preview_media(
                run_dir,
                run_root,
                start_ns=start_ns,
                end_ns=end_ns,
                video_row=merged_video,
                label_row=label_row,
            )
            if sdk is not None:
                return sdk
        return _build_mp4_preview_media(
            run_dir,
            run_root,
            start_ns=start_ns,
            end_ns=end_ns,
            preview_fps=preview_fps,
            max_frames_per_camera=max_frames_per_camera,
        )
    return _copy_frame_preview_media(
        run_dir,
        run_root,
        start_ns=start_ns,
        end_ns=end_ns,
        preview_fps=preview_fps,
        max_frames_per_camera=max_frames_per_camera,
    )


def _build_mp4_preview_media(
    run_dir: Path,
    run_root: Path,
    *,
    start_ns: int,
    end_ns: int,
    preview_fps: float,
    max_frames_per_camera: int,
) -> tuple[list[dict[str, Any]], str | None]:
    frames_root = run_dir / "work" / "output" / "frames"
    audio_rel: str | None = None
    audio_src = _resolve_audio_src(run_dir)
    if audio_src:
        audio_rel = "parsed/output/audio/audio.wav"
        dest = run_root / audio_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_src, dest)

    if not frames_root.is_dir():
        return [], audio_rel

    duration_sec = max(0.001, (end_ns - start_ns) / 1e9)
    picked_by_cam: dict[str, list[Path]] = {}
    for topic_dir, camera in CAMERA_TOPIC_DIRS:
        cam_dir = frames_root / topic_dir
        if not cam_dir.is_dir():
            continue
        jpgs = list(cam_dir.glob("*.jpg"))
        picked = _pick_preview_frames(
            jpgs,
            duration_sec,
            preview_fps=preview_fps,
            max_frames=max_frames_per_camera,
        )
        if picked:
            picked_by_cam[camera] = picked

    if not picked_by_cam:
        return [], audio_rel

    preview_dir = run_root / PREVIEW_REL_DIR.replace("/", "\\") if "\\" in str(run_root) else run_root / PREVIEW_REL_DIR
    grid_path = preview_dir / GRID_MP4_NAME
    frame_count = build_grid_mp4_from_frames(picked_by_cam, grid_path, fps=preview_fps)

    cam_meta: dict[str, dict[str, Any]] = {}
    for camera, paths in picked_by_cam.items():
        cam_mp4 = preview_dir / f"{camera}.mp4"
        n = build_single_camera_mp4(paths, cam_mp4, fps=preview_fps)
        rel = f"{PREVIEW_REL_DIR}/{camera}.mp4"
        cam_meta[camera] = {"relpath": rel, "frame_count": n}

    grid_rel = f"{PREVIEW_REL_DIR}/{GRID_MP4_NAME}"
    manifest = {
        "mode": "mp4",
        "fps": preview_fps,
        "frame_count": frame_count,
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
        "grid_relpath": grid_rel,
        "cameras": cam_meta,
        "source": "real_data_import",
    }
    write_preview_manifest(run_root / MANIFEST_REL, manifest)

    # Sparse fact_frame: one row per camera at clip start (path points at preview dir for stats)
    frame_rows: list[dict[str, Any]] = []
    for i, camera in enumerate(sorted(picked_by_cam.keys())):
        frame_rows.append(
            {
                "camera": camera,
                "frame_idx": 0,
                "timestamp_ns": start_ns,
                "image_path": grid_rel,
            }
        )
    return frame_rows, audio_rel


def _copy_frame_preview_media(
    run_dir: Path,
    run_root: Path,
    *,
    start_ns: int,
    end_ns: int,
    preview_fps: float = DEFAULT_PREVIEW_FPS,
    max_frames_per_camera: int = DEFAULT_MAX_FRAMES_PER_CAMERA,
) -> tuple[list[dict[str, Any]], str | None]:
    frames_root = run_dir / "work" / "output" / "frames"
    frame_rows: list[dict[str, Any]] = []
    audio_rel: str | None = None

    audio_src = _resolve_audio_src(run_dir)
    if audio_src:
        audio_rel = "parsed/output/audio/audio.wav"
        dest = run_root / audio_rel.replace("/", "\\") if "\\" in str(run_root) else run_root / audio_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_src, dest)

    if not frames_root.is_dir():
        return frame_rows, audio_rel

    duration_sec = max(0.001, (end_ns - start_ns) / 1e9)

    for topic_dir, camera in CAMERA_TOPIC_DIRS:
        cam_dir = frames_root / topic_dir
        if not cam_dir.is_dir():
            continue
        jpgs = list(cam_dir.glob("*.jpg"))
        picked = _pick_preview_frames(
            jpgs,
            duration_sec,
            preview_fps=preview_fps,
            max_frames=max_frames_per_camera,
        )
        for frame_idx, src in enumerate(picked):
            ts_match = re.match(r"(\d+)", src.stem)
            timestamp_ns = int(ts_match.group(1)) if ts_match else start_ns + frame_idx * 50_000_000
            rel = f"parsed/output/images/{camera}/{frame_idx:06d}.jpg"
            dest = run_root / rel.replace("/", "\\") if "\\" in str(run_root) else run_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            encoded = encode_frame_image(dest)
            if encoded is not None:
                dest = encoded
                rel = str(dest.relative_to(run_root)).replace("\\", "/")
            frame_rows.append(
                {
                    "camera": camera,
                    "frame_idx": frame_idx,
                    "timestamp_ns": timestamp_ns,
                    "image_path": rel,
                }
            )
    return frame_rows, audio_rel


def _write_parsed_aligned(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    label_row: dict[str, Any],
    frame_rows: list[dict[str, Any]],
) -> None:
    start_ns = int(label_row.get("start_timestamp_ns") or 0)
    end_ns = int(label_row.get("end_timestamp_ns") or start_ns)
    duration = float(label_row.get("duration_sec") or max(0.0, (end_ns - start_ns) / 1e9))

    manifest = {
        "clip_id": clip_id,
        "run_id": run_id,
        "bag_stem": str(label_row.get("bag_name") or "output").replace(".bag", ""),
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
        "duration_sec": duration,
        "modalities": ["camera", "audio", "event"],
        "cameras": sorted({r["camera"] for r in frame_rows}) or [c for _, c in CAMERA_TOPIC_DIRS],
        "parsed_at": _utc_now(),
        "source": "real_data_import",
        "preview_mode": "mp4" if (run_root / MANIFEST_REL).is_file() else "frames",
    }
    _write_json(run_root / "parsed" / "manifest.json", manifest)
    (run_root / "parsed" / "events.jsonl").write_text("", encoding="utf-8")

    mc_payload = {
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": DS,
        "parse_result": {
            "frames": [
                {
                    "camera": r["camera"],
                    "frame_idx": r["frame_idx"],
                    "timestamp_ns": r["timestamp_ns"],
                    "image_path": r["image_path"],
                }
                for r in frame_rows
            ],
        },
    }
    _write_json(run_root / "parsed" / "job1_mc_payload.json", mc_payload)

    timeline = {
        "pipeline_version": "real_data_import_v1",
        "clip_id": clip_id,
        "run_id": run_id,
        "start_time_ns": start_ns,
        "end_time_ns": end_ns,
        "duration_sec": duration,
        "modalities": ["camera", "audio"],
    }
    _write_json(run_root / "aligned" / "timeline.json", timeline)
    anchor = frame_rows[0]["timestamp_ns"] if frame_rows else start_ns
    sync_line = json.dumps(
        {"anchor_timestamp_ns": anchor, "object_type": "frame", "object_id": "camera0:0"},
        ensure_ascii=False,
    )
    (run_root / "aligned" / "sync_manifest.jsonl").write_text(sync_line + "\n", encoding="utf-8")


def _write_ai_artifacts(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    label_row: dict[str, Any],
    embed_row: dict[str, Any],
    flat_labels: dict[str, Any],
    label_hints: dict[str, dict[str, Any]],
) -> None:
    model = str(label_row.get("model") or "qwen3.5-omni-plus")
    embed_model = str(embed_row.get("model") or "qwen3-vl-embedding")
    multi_ai_meta = {
        "gate": {"passed": True, "clip_score": 1.0, "threshold": 0.7},
        "disputed_label_ids": [],
        "primary_model": model,
        "secondary_model": model,
        "note": "single-model real run imported as merged",
    }
    merged_doc = {
        "clip_id": clip_id,
        "run_id": run_id,
        "label_source": "ai_merged",
        "model_version": model,
        "labels_json": flat_labels,
        "multi_ai_meta": multi_ai_meta,
        "gate_passed": True,
        "clip_agreement": 1.0,
        "scene_summary": label_row.get("scene_summary"),
        "label_hints": label_hints,
        "created_at": _utc_now(),
    }
    ai_dir = run_root / "ai"
    _write_json(ai_dir / "labels_merged.json", merged_doc)
    _write_json(ai_dir / "labels.json", merged_doc)
    if label_hints:
        _write_json(ai_dir / "label_hints.json", label_hints)
    _write_json(
        ai_dir / "consensus_meta.json",
        {
            "clip_id": clip_id,
            "run_id": run_id,
            "multi_ai_meta": multi_ai_meta,
            "disputed_label_ids": [],
            "gate_passed": True,
            "created_at": _utc_now(),
        },
    )

    vector = embed_row.get("embedding") or embed_row.get("vector") or []
    _write_json(
        ai_dir / "embedding.json",
        {
            "clip_id": clip_id,
            "run_id": run_id,
            "dim": len(vector),
            "model_version": embed_model,
            "aggregation_method": "clip_omni",
            "vector": list(vector),
            "created_at": _utc_now(),
        },
    )
    _write_json(
        ai_dir / "infer_meta.json",
        {
            "clip_id": clip_id,
            "run_id": run_id,
            "primary_model": model,
            "embed_model": embed_model,
            "finished_at": _utc_now(),
        },
    )


def _seed_db_rows(
    *,
    clip_id: str,
    run_id: str,
    dir_name: str,
    label_row: dict[str, Any],
    embed_row: dict[str, Any],
    flat_labels: dict[str, Any],
    frame_rows: list[dict[str, Any]],
    audio_rel: str | None,
    bag_oss_key: str | None = None,
) -> None:
    from hmi.sdk_ingest import seed_sqlite_from_sdk_parsed

    bag_name = str(label_row.get("bag_name") or "output.bag")
    seed_sqlite_from_sdk_parsed(
        clip_id=clip_id,
        run_id=run_id,
        ds=DS,
        clip_dir_name=dir_name,
        bag_oss_key=bag_oss_key
        or f"{REAL_DATA_BAG_OSS_PREFIX}{_slug(dir_name)}/{bag_name}",
        label_row=label_row,
        embed_row=embed_row,
        flat_labels=flat_labels,
        frame_rows=frame_rows,
        audio_relpath=audio_rel,
    )


def list_runs(
    *,
    source: str | None = None,
    all_sources: bool = False,
    data_root: Path | None = None,
) -> list[Path]:
    root_base = (data_root or REAL_DATA_ROOT).resolve()
    if not root_base.is_dir():
        return []

    def _collect_under(root: Path) -> list[Path]:
        out: list[Path] = []
        if _is_importable_run_dir(root):
            return [root]
        for child in sorted(root.iterdir()):
            if child.is_dir() and _is_importable_run_dir(child):
                out.append(child)
        return out

    if source:
        return _collect_under(root_base / source.strip())

    runs: list[Path] = []
    if not all_sources:
        nested = root_base / "pipeline_latest"
        if nested.is_dir():
            batch_runs = _collect_under(nested)
            if batch_runs:
                return batch_runs
        batch_runs = _collect_under(root_base)
        if batch_runs:
            return batch_runs

    for child in sorted(root_base.iterdir()):
        if not child.is_dir() or child.name in BATCH_CONTAINER_NAMES:
            continue
        if _is_importable_run_dir(child):
            runs.append(child)
    if not all_sources:
        return runs
    for batch in BATCH_CONTAINER_NAMES:
        runs.extend(_collect_under(root_base / batch))
    # de-dupe by folder name (prefer top-level)
    seen: set[str] = set()
    unique: list[Path] = []
    for run_dir in runs:
        if run_dir.name in seen:
            continue
        seen.add(run_dir.name)
        unique.append(run_dir)
    return sorted(unique, key=lambda p: p.name)


def import_run(
    run_dir: Path,
    *,
    seed_review: bool = True,
    preview_mode: str = DEFAULT_PREVIEW_MODE,
    preview_fps: float | None = None,
    max_frames_per_camera: int = DEFAULT_MAX_FRAMES_PER_CAMERA,
    fixed_run_id: str | None = None,
    fixed_clip_id: str | None = None,
    bag_oss_key: str | None = None,
) -> dict[str, Any]:
    labels_path = run_dir / "labels.jsonl"
    embed_path = run_dir / "fusion_embeddings.jsonl"
    if not labels_path.is_file() or not embed_path.is_file():
        raise FileNotFoundError(f"missing labels/embed jsonl under {run_dir}")

    run_dir_name = run_dir.name
    label_row = _read_jsonl_first(labels_path)
    embed_row = _read_jsonl_first(embed_path)
    flat_labels = labels_to_clip_dict(label_row.get("labels") or {})

    clip_id = fixed_clip_id or clip_id_from_bag(run_dir, label_row)
    run_id = fixed_run_id or run_id_for_run(run_dir_name)
    dir_name = display_name(run_dir, label_row)
    bag_path: Path | None = None
    if bag_oss_key:
        try:
            from hmi.local.bag_upload import resolve_local_bag_path

            bag_path = resolve_local_bag_path(bag_oss_key)
        except Exception:
            bag_path = None
    if bag_path is None or not bag_path.is_file():
        bag_path = _resolve_bag_path(run_dir, label_row)
    bag_name = bag_path.name

    run_root = artifacts_dir(clip_id, run_id)
    if run_root.is_dir():
        shutil.rmtree(run_root, ignore_errors=True)
    run_root.mkdir(parents=True, exist_ok=True)

    start_ns = int(label_row.get("start_timestamp_ns") or 0)
    end_ns = int(label_row.get("end_timestamp_ns") or start_ns)
    mode = (preview_mode or DEFAULT_PREVIEW_MODE).strip().lower()
    if mode not in ("mp4", "frames"):
        mode = DEFAULT_PREVIEW_MODE
    fps = preview_fps
    if fps is None:
        fps = DEFAULT_MP4_PREVIEW_FPS if mode == "mp4" else DEFAULT_PREVIEW_FPS
    frame_rows, audio_rel = _copy_parsed_media(
        run_dir,
        run_root,
        start_ns=start_ns,
        end_ns=end_ns,
        preview_mode=mode,
        preview_fps=fps,
        max_frames_per_camera=max_frames_per_camera,
        label_row=label_row,
    )
    _copy_sdk_jsonl_bundle(run_dir, run_root)
    _write_sdk_run_json(
        run_root,
        clip_id=clip_id,
        run_id=run_id,
        source_run_dir=run_dir_name,
        bag_oss_key=bag_oss_key
        or f"{REAL_DATA_BAG_OSS_PREFIX}{_slug(run_dir_name)}/{bag_name}",
        ds=DS,
    )
    _seed_db_rows(
        clip_id=clip_id,
        run_id=run_id,
        dir_name=dir_name,
        label_row=label_row,
        embed_row=embed_row,
        flat_labels=flat_labels,
        frame_rows=frame_rows,
        audio_rel=audio_rel,
        bag_oss_key=bag_oss_key
        or f"{REAL_DATA_BAG_OSS_PREFIX}{_slug(dir_name)}/{bag_name}",
    )

    review_status = "skipped"
    if seed_review:
        try:
            enqueue_clip(clip_id, run_id, require_job3=True)
            review_status = "pending_review"
        except Exception as exc:
            review_status = f"review_error:{exc}"

    preview_source = mode
    manifest_file = run_root / MANIFEST_REL
    if manifest_file.is_file():
        try:
            doc = json.loads(manifest_file.read_text(encoding="utf-8"))
            if isinstance(doc, dict) and doc.get("source"):
                preview_source = str(doc["source"])
        except (json.JSONDecodeError, OSError):
            pass

    return {
        "run_dir": run_dir_name,
        "clip_id": clip_id,
        "run_id": run_id,
        "display_name": dir_name,
        "frame_count": len(frame_rows),
        "label_count": len(flat_labels),
        "embed_dim": len(embed_row.get("embedding") or embed_row.get("vector") or []),
        "review": review_status,
        "preview_mode": mode,
        "preview_source": preview_source,
    }


def _purge_clip_from_stores(clip_id: str, run_id: str) -> None:
    if run_id:
        ds_rows = store.query(
            "SELECT DISTINCT ds FROM pipeline_run WHERE clip_id=? AND run_id=?",
            (clip_id, run_id),
        )
        if not ds_rows:
            ds_rows = [{"ds": DS}]
        for ds_row in ds_rows:
            store.clear_clip_data(clip_id, run_id, str(ds_row["ds"]))
        with db_conn() as conn:
            conn.execute(
                "DELETE FROM clip_label_review WHERE clip_id=? AND run_id=?",
                (clip_id, run_id),
            )
            conn.execute(
                "DELETE FROM clip_label_field_review WHERE clip_id=? AND run_id=?",
                (clip_id, run_id),
            )
            conn.commit()
    root = artifacts_dir(clip_id, run_id) if run_id else None
    if root and root.is_dir():
        shutil.rmtree(root, ignore_errors=True)


def _is_real_data_clip_row(row: dict[str, Any]) -> bool:
    bag_key = str(row.get("bag_oss_key") or "")
    if bag_key.startswith(REAL_DATA_BAG_OSS_PREFIX):
        return True
    cid = str(row.get("clip_id") or "")
    return cid.startswith("sha256:real_")


def purge_non_real_clips() -> list[str]:
    """Remove local clips that are not SDK real_data imports or demo clips."""
    ensure_schema()
    store.ensure_db()
    rows = store.query("SELECT clip_id, active_run_id, bag_oss_key FROM dim_clip")
    removed: list[str] = []
    for row in rows:
        cid = str(row["clip_id"])
        if _is_real_data_clip_row(row) or cid.startswith("sha256:demo_"):
            continue
        rid = str(row.get("active_run_id") or "")
        _purge_clip_from_stores(cid, rid)
        store.execute("DELETE FROM dim_clip WHERE clip_id=?", (cid,))
        removed.append(cid)

    with db_conn() as conn:
        kept = store.query(
            "SELECT clip_id FROM dim_clip WHERE bag_oss_key LIKE ? OR clip_id LIKE 'sha256:demo_%'",
            (f"{REAL_DATA_BAG_OSS_PREFIX}%",),
        )
        kept_ids = {str(r["clip_id"]) for r in kept}
        for table in ("clip_label_review", "clip_label_field_review"):
            for row in conn.execute(f"SELECT DISTINCT clip_id FROM {table}").fetchall():
                cid = str(row[0])
                if cid not in kept_ids:
                    conn.execute(f"DELETE FROM {table} WHERE clip_id=?", (cid,))
        conn.commit()

    clips_art = HMI_ROOT / "data" / "hmi_local" / "artifacts" / "clips"
    if clips_art.is_dir():
        kept_clip_ids = {str(r["clip_id"]) for r in store.query("SELECT clip_id FROM dim_clip")}
        safe_kept = {cid.replace(":", "__") for cid in kept_clip_ids}
        for child in clips_art.iterdir():
            if not child.is_dir() or child.name in safe_kept:
                continue
            shutil.rmtree(child, ignore_errors=True)

    real_rows = store.query(
        "SELECT clip_id, clip_dir_name FROM dim_clip WHERE bag_oss_key LIKE ?",
        (f"{REAL_DATA_BAG_OSS_PREFIX}%",),
    )
    for row in real_rows:
        name = str(row.get("clip_dir_name") or "")
        cleaned = name.replace("[真实]", "").replace("【真实】", "").strip()
        if cleaned != name:
            store.execute(
                "UPDATE dim_clip SET clip_dir_name=? WHERE clip_id=?",
                (cleaned, str(row["clip_id"])),
            )

    try:
        from hmi.db import cache_clear
        from hmi.services.overview_cache import overview_cache_clear

        cache_clear()
        overview_cache_clear()
    except Exception:
        pass

    return removed


def clear_demo_and_real_clips() -> None:
    ensure_schema()
    store.ensure_db()
    clip_ids = store.query(
        "SELECT clip_id, active_run_id FROM dim_clip WHERE clip_id LIKE 'sha256:demo_%' "
        "OR bag_oss_key LIKE ?",
        (f"{REAL_DATA_BAG_OSS_PREFIX}%",),
    )
    for row in clip_ids:
        cid = str(row["clip_id"])
        rid = str(row.get("active_run_id") or "")
        _purge_clip_from_stores(cid, rid)

    store.execute("DELETE FROM dim_clip WHERE clip_id LIKE 'sha256:demo_%'")
    store.execute("DELETE FROM dim_clip WHERE bag_oss_key LIKE ?", (f"{REAL_DATA_BAG_OSS_PREFIX}%",))

    demo_art = HMI_ROOT / "data" / "hmi_local" / "artifacts" / "clips"
    if demo_art.is_dir():
        for child in demo_art.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)


def backfill_label_hints_from_source() -> int:
    """Write ai/label_hints.json for already-imported real clips (no media recopy)."""
    updated = 0
    for run_dir in list_runs(all_sources=True):
        labels_path = run_dir / "labels.jsonl"
        if not labels_path.is_file():
            continue
        label_row = _read_jsonl_first(labels_path)
        hints = extract_label_hints(label_row.get("labels") or {})
        if not hints:
            continue
        clip_id = clip_id_from_bag(run_dir, label_row)
        run_id = run_id_for_run(run_dir.name)
        run_root = artifacts_dir(clip_id, run_id)
        if not run_root.is_dir():
            continue
        from hmi.ai_label_hints import write_ai_label_hints_local

        write_ai_label_hints_local(clip_id, run_id, hints)
        merged_path = run_root / "ai" / "labels_merged.json"
        if merged_path.is_file():
            merged = json.loads(merged_path.read_text(encoding="utf-8"))
            if isinstance(merged, dict):
                merged["label_hints"] = hints
                _write_json(merged_path, merged)
                labels_path_ai = run_root / "ai" / "labels.json"
                if labels_path_ai.is_file():
                    _write_json(labels_path_ai, merged)
        updated += 1
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(description="Import data/real_data runs into HMI local store")
    parser.add_argument("--list", action="store_true", help="List importable run folders")
    parser.add_argument("--reset", action="store_true", help="Clear demo + prior real imports first")
    parser.add_argument("--run", help="Import one run folder (name or pipeline_latest/<name>)")
    parser.add_argument(
        "--from-path",
        type=Path,
        default=None,
        help="Import from this directory instead of data/real_data (e.g. hmi_runtime/sandbox/pipeline_latest)",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Import runs under data/real_data/<source> (default: pipeline_latest when present)",
    )
    parser.add_argument(
        "--all-sources",
        action="store_true",
        help="Import all top-level runs and batch folders (not only pipeline_latest)",
    )
    parser.add_argument(
        "--materialize-media",
        action="store_true",
        help="Copy SDK clip_preview.mp4/audio.wav next to jsonl (portable sample)",
    )
    parser.add_argument(
        "--purge-test-clips",
        action="store_true",
        help="Delete local clips that are not SDK real_data imports (bag_oss_key local://real_data/) or demo",
    )
    parser.add_argument(
        "--no-review",
        action="store_true",
        help="Skip enqueue into review queue",
    )
    parser.add_argument(
        "--hints-only",
        action="store_true",
        help="Only backfill ai/label_hints.json for existing real imports",
    )
    parser.add_argument(
        "--preview-mode",
        choices=("mp4",),
        default=DEFAULT_PREVIEW_MODE,
        help="Clip-level MP4 preview (local ffmpeg; default)",
    )
    parser.add_argument(
        "--preview-fps",
        type=float,
        default=None,
        help=f"Preview encode fps (default {DEFAULT_MP4_PREVIEW_FPS} for mp4, {DEFAULT_PREVIEW_FPS} for frames)",
    )
    parser.add_argument(
        "--max-frames-per-camera",
        type=int,
        default=DEFAULT_MAX_FRAMES_PER_CAMERA,
        help="Cap frames imported per camera (default 900)",
    )
    parser.add_argument("--run-id", dest="fixed_run_id", help="Use this pipeline run_id (local SDK upload)")
    parser.add_argument("--clip-id", dest="fixed_clip_id", help="Use this clip_id (local SDK upload)")
    parser.add_argument(
        "--bag-oss-key",
        help="dim_clip bag_oss_key (e.g. local://rosbags/coll/file.bag)",
    )
    args = parser.parse_args()

    if args.purge_test_clips:
        removed = purge_non_real_clips()
        print(f"Removed {len(removed)} non-real clip(s) from local DB / artifacts")
        for cid in removed[:20]:
            print(f"  - {cid}")
        if len(removed) > 20:
            print(f"  ... and {len(removed) - 20} more")
        remaining = store.query(
            "SELECT clip_id, clip_dir_name FROM dim_clip ORDER BY clip_dir_name"
        )
        print(f"\nRemaining {len(remaining)} clip(s):")
        for row in remaining:
            print(f"  {row['clip_dir_name'][:56]:56}  {row['clip_id']}")
        return 0

    if args.hints_only:
        n = backfill_label_hints_from_source()
        print(f"Backfilled label hints on {n} clip(s)")
        return 0 if n else 1

    data_root = args.from_path.resolve() if args.from_path else REAL_DATA_ROOT
    runs = list_runs(source=args.source, all_sources=args.all_sources, data_root=data_root)
    if args.materialize_media:
        if not runs:
            print(f"error: no importable runs under {data_root}", file=sys.stderr)
            return 1
        copied = 0
        for run_dir in runs:
            result = materialize_run_media(run_dir)
            if result.get("audio.wav") or any(k.startswith("clip_preview_") for k in result):
                copied += 1
                print(f"  media OK  {run_dir.relative_to(data_root)}")
            else:
                print(f"  SKIP (no video)  {run_dir.relative_to(data_root)}", file=sys.stderr)
        print(f"\nMaterialized {copied} clip video(s)")
        return 0 if copied else 1

    if args.list:
        for run_dir in runs:
            lab = run_dir / "labels.jsonl"
            vid = run_dir / "clip_videos.jsonl"
            work_mp4 = _clip_output_dir(run_dir)
            has_work = work_mp4.is_dir() and any(work_mp4.glob("clip_preview_camera*.mp4"))
            ok = "OK" if lab.is_file() and (run_dir / "fusion_embeddings.jsonl").is_file() else "MISSING"
            media = "sdk-multicam" if vid.is_file() or has_work else "frames?"
            print(f"  [{ok}|{media}] {run_dir.relative_to(data_root)}")
        print(f"\nTotal: {len(runs)} run(s)")
        return 0

    if not runs:
        print(f"error: no importable runs under {data_root}", file=sys.stderr)
        return 1

    if args.reset:
        clear_demo_and_real_clips()
        print("Cleared demo + SDK real_data imports")

    targets = runs
    if args.run:
        run_arg = args.run.strip().replace("\\", "/")
        candidates = [
            data_root / run_arg,
            data_root / "pipeline_latest" / run_arg.split("/")[-1],
        ]
        targets = [c for c in candidates if c.is_dir()]
        if not targets:
            print(f"error: not found: {run_arg}", file=sys.stderr)
            return 1
        targets = [targets[0]]

    results: list[dict[str, Any]] = []
    for run_dir in targets:
        try:
            results.append(
                import_run(
                    run_dir,
                    seed_review=not args.no_review,
                    preview_mode=args.preview_mode,
                    preview_fps=args.preview_fps,
                    max_frames_per_camera=args.max_frames_per_camera,
                    fixed_run_id=args.fixed_run_id,
                    fixed_clip_id=args.fixed_clip_id,
                    bag_oss_key=args.bag_oss_key,
                )
            )
        except Exception as exc:
            print(f"FAIL {run_dir.name}: {exc}", file=sys.stderr)

    try:
        from hmi.db import cache_clear

        cache_clear()
    except Exception:
        pass

    from hmi.data_source import LOCAL_ARTIFACTS_ROOT, LOCAL_DB_PATH

    print(f"Imported {len(results)} clip(s) from {data_root}\n")
    for row in results:
        print(
            f"  {row['display_name'][:40]:40}  preview={row['preview_source']:16}  "
            f"labels={row['label_count']:3}  dim={row['embed_dim']}  review={row['review']}"
        )
    print(f"\nArtifacts: {LOCAL_ARTIFACTS_ROOT / 'clips'}/")
    print(f"SQLite:    {LOCAL_DB_PATH}  (ds={DS})")
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
