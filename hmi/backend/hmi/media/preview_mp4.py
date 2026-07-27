"""Build H.264 preview MP4 from SDK frame JPEGs (local ffmpeg)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Sequence

from PIL import Image

PREVIEW_REL_DIR = "preview"
LEGACY_PREVIEW_REL_DIR = "parsed/preview"
GRID_MP4_NAME = "grid.mp4"
MANIFEST_NAME = "manifest.json"


def resolve_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:
        raise RuntimeError(
            "ffmpeg not found on PATH; install ffmpeg or pip install imageio-ffmpeg"
        ) from exc


def _run_ffmpeg(args: list[str], *, cwd: Path | None = None) -> None:
    ffmpeg = resolve_ffmpeg()
    proc = subprocess.run(
        [ffmpeg, *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-2000:]
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {tail}")


def _resize_tile(img: Image.Image, w: int, h: int) -> Image.Image:
    if img.size == (w, h):
        return img
    return img.resize((w, h), Image.Resampling.LANCZOS)


def _compose_grid_frame(
    paths: Sequence[Path | None],
    *,
    tile_w: int = 640,
    tile_h: int = 360,
) -> Image.Image:
    """2x2 grid: camera0 camera1 / camera2 camera3."""
    slots = list(paths[:4])
    while len(slots) < 4:
        slots.append(None)
    tiles: list[Image.Image] = []
    blank = Image.new("RGB", (tile_w, tile_h), (32, 32, 32))
    for p in slots:
        if p and p.is_file():
            with Image.open(p) as im:
                tiles.append(_resize_tile(im.convert("RGB"), tile_w, tile_h))
        else:
            tiles.append(blank.copy())
    top = Image.new("RGB", (tile_w * 2, tile_h))
    top.paste(tiles[0], (0, 0))
    top.paste(tiles[1], (tile_w, 0))
    bot = Image.new("RGB", (tile_w * 2, tile_h))
    bot.paste(tiles[2], (0, 0))
    bot.paste(tiles[3], (tile_w, 0))
    grid = Image.new("RGB", (tile_w * 2, tile_h * 2))
    grid.paste(top, (0, 0))
    grid.paste(bot, (0, tile_h))
    return grid


def build_grid_mp4_from_frames(
    frame_sets: dict[str, list[Path]],
    out_mp4: Path,
    *,
    fps: float,
    camera_order: Sequence[str] = ("camera0", "camera1", "camera2", "camera3"),
) -> int:
    """Write a 2x2 grid MP4; returns frame count encoded."""
    counts = [len(frame_sets.get(cam) or []) for cam in camera_order if frame_sets.get(cam)]
    if not counts:
        raise ValueError("no frames for preview mp4")
    n_frames = min(counts)
    if n_frames <= 0:
        raise ValueError("empty frame lists")

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hmi_grid_") as tmp:
        tmp_path = Path(tmp)
        for i in range(n_frames):
            paths = [None, None, None, None]
            for j, cam in enumerate(camera_order):
                if j >= 4:
                    break
                lst = frame_sets.get(cam) or []
                paths[j] = lst[i] if i < len(lst) else None
            grid = _compose_grid_frame(paths)
            grid.save(tmp_path / f"{i:06d}.jpg", quality=85, optimize=True)

        pattern = str(tmp_path / "%06d.jpg")
        _run_ffmpeg(
            [
                "-y",
                "-framerate",
                str(max(0.1, fps)),
                "-i",
                pattern,
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out_mp4),
            ]
        )
    return n_frames


def build_single_camera_mp4(
    jpg_paths: list[Path],
    out_mp4: Path,
    *,
    fps: float,
) -> int:
    if not jpg_paths:
        raise ValueError("no frames")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hmi_cam_") as tmp:
        tmp_path = Path(tmp)
        for i, src in enumerate(jpg_paths):
            dest = tmp_path / f"{i:06d}.jpg"
            shutil.copy2(src, dest)
        _run_ffmpeg(
            [
                "-y",
                "-framerate",
                str(max(0.1, fps)),
                "-i",
                str(tmp_path / "%06d.jpg"),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(out_mp4),
            ]
        )
    return len(jpg_paths)


def _probe_duration_sec(video_path: Path) -> float | None:
    ffmpeg = resolve_ffmpeg()
    ffprobe = Path(ffmpeg).with_name("ffprobe.exe" if ffmpeg.lower().endswith(".exe") else "ffprobe")
    if not ffprobe.is_file():
        ffprobe = Path(shutil.which("ffprobe") or "")
    if not ffprobe.is_file():
        return None
    proc = subprocess.run(
        [
            str(ffprobe),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        val = float((proc.stdout or "").strip())
        return val if val > 0 else None
    except ValueError:
        return None


def build_grid_mp4_from_camera_mp4s(
    camera_mp4s: dict[str, Path],
    out_mp4: Path,
    *,
    camera_order: Sequence[str] = ("camera0", "camera1", "camera2", "camera3"),
    tile_w: int = 640,
    tile_h: int = 360,
) -> None:
    """Mux per-camera preview MP4s into a 2×2 grid (missing slots = black)."""
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    duration_sec: float | None = None
    for cam in camera_order:
        src = camera_mp4s.get(cam)
        if src and src.is_file():
            duration_sec = _probe_duration_sec(src)
            if duration_sec:
                break
    if duration_sec is None:
        duration_sec = 30.0

    inputs: list[str] = []
    filter_parts: list[str] = []
    stack_slots: list[str] = []
    idx = 0
    for cam in camera_order:
        src = camera_mp4s.get(cam)
        if src and src.is_file():
            inputs.extend(["-i", str(src.resolve())])
            filter_parts.append(f"[{idx}:v]scale={tile_w}:{tile_h},setsar=1[v{idx}]")
        else:
            inputs.extend(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    f"color=c=0x202020:s={tile_w}x{tile_h}:r=30:d={duration_sec:.3f}",
                ]
            )
            filter_parts.append(f"[{idx}:v]setsar=1[v{idx}]")
        stack_slots.append(f"v{idx}")
        idx += 1

    if idx != 4:
        raise ValueError("grid preview expects four camera slots")

    filter_parts.append(f"[{stack_slots[0]}][{stack_slots[1]}]hstack=inputs=2[top]")
    filter_parts.append(f"[{stack_slots[2]}][{stack_slots[3]}]hstack=inputs=2[bot]")
    filter_parts.append("[top][bot]vstack=inputs=2[outv]")
    filter_complex = ";".join(filter_parts)

    _run_ffmpeg(
        [
            "-y",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outv]",
            "-an",
            "-t",
            f"{duration_sec:.3f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
    )
