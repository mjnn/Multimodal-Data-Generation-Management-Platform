"""将 clip 全量相机帧 + WAV 合成为 MP4 预览视频（不受 Omni sample_fps 影响）。"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image

if TYPE_CHECKING:
    from .rosbag_parser import Clip


@dataclass
class ClipVideoConfig:
    """Clip MP4 编码参数。"""

    enabled: bool = True
    filename: str = "clip_preview.mp4"
    max_width: int = 1920
    max_height: int = 1080
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 18
    camera_topic: str | None = None
    encode_all_cameras: bool = True

    @classmethod
    def from_env(cls) -> ClipVideoConfig:
        enabled_raw = os.getenv("CLIP_VIDEO_ENABLED", "true").strip().lower()
        enabled = enabled_raw not in {"0", "false", "no", "off"}
        camera_topic = os.getenv("CLIP_VIDEO_CAMERA_TOPIC", "").strip() or None
        all_raw = os.getenv("CLIP_VIDEO_ENCODE_ALL_CAMERAS", "true").strip().lower()
        encode_all = all_raw not in {"0", "false", "no", "off"}
        return cls(
            enabled=enabled,
            filename=os.getenv("CLIP_VIDEO_FILENAME", "clip_preview.mp4"),
            max_width=int(os.getenv("CLIP_VIDEO_MAX_WIDTH", "1920")),
            max_height=int(os.getenv("CLIP_VIDEO_MAX_HEIGHT", "1080")),
            video_codec=os.getenv("CLIP_VIDEO_CODEC", "libx264"),
            audio_codec=os.getenv("CLIP_VIDEO_AUDIO_CODEC", "aac"),
            crf=int(os.getenv("CLIP_VIDEO_CRF", "18")),
            camera_topic=camera_topic,
            encode_all_cameras=encode_all,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _bundled_ffmpeg_exe() -> str | None:
    """Return imageio-ffmpeg's shipped binary if the file exists (no -version probe)."""
    try:
        import imageio_ffmpeg
    except ImportError:
        return None
    binaries = Path(imageio_ffmpeg.__file__).resolve().parent / "binaries"
    if not binaries.is_dir():
        return None
    if sys.platform.startswith("win"):
        candidates = sorted(binaries.glob("ffmpeg*.exe"))
    else:
        candidates = [
            p
            for p in sorted(binaries.glob("ffmpeg*"))
            if p.is_file() and p.suffix.lower() not in {".md", ".txt", ".py"}
        ]
    for cand in candidates:
        if cand.is_file():
            return str(cand)
    return None


def resolve_ffmpeg() -> str:
    """Locate ffmpeg: IMAGEIO_FFMPEG_EXE → PATH → bundled imageio-ffmpeg binary.

    ``imageio_ffmpeg.get_ffmpeg_exe()`` can raise RuntimeError even when the
    bundled file exists (Windows ``_is_valid_exe`` / cached None). Encoding
    only needs a filesystem path.
    """
    env = (os.getenv("IMAGEIO_FFMPEG_EXE") or "").strip()
    if env:
        env_path = Path(env)
        if env_path.is_file():
            return str(env_path)
        which_env = shutil.which(env)
        if which_env:
            return which_env

    which = shutil.which("ffmpeg")
    if which:
        return which

    bundled = _bundled_ffmpeg_exe()
    if bundled:
        os.environ.setdefault("IMAGEIO_FFMPEG_EXE", bundled)
        return bundled

    try:
        import imageio_ffmpeg

        exe = str(imageio_ffmpeg.get_ffmpeg_exe() or "").strip()
    except ImportError as exc:
        raise RuntimeError(
            "ffmpeg not found on PATH and imageio-ffmpeg is not installed. "
            "Install imageio-ffmpeg or add ffmpeg to PATH."
        ) from exc
    except Exception:
        exe = ""
    if exe:
        exe_path = Path(exe)
        if exe_path.is_file():
            return str(exe_path)
        found = shutil.which(exe)
        if found:
            return found

    raise RuntimeError(
        "ffmpeg not found on PATH and imageio-ffmpeg bundled binary is unusable. "
        "Install ffmpeg, pip install imageio-ffmpeg, or set IMAGEIO_FFMPEG_EXE "
        "to the ffmpeg executable."
    )


def _resolve_ffmpeg() -> str:
    return resolve_ffmpeg()


def _video_source_frames(clip: "Clip") -> list:
    if clip.video_frames:
        return clip.video_frames
    return list(clip.frames)


def _group_frames_by_topic(frames: list) -> dict[str, list]:
    by_topic: dict[str, list] = {}
    for frame in frames:
        by_topic.setdefault(frame.topic, []).append(frame)
    for topic_frames in by_topic.values():
        topic_frames.sort(key=lambda f: f.timestamp_ns)
    return by_topic


def _topic_slug(topic: str) -> str:
    parts = [p for p in topic.strip("/").split("/") if p]
    if parts:
        return re.sub(r"[^\w.\-]+", "_", parts[0])
    return re.sub(r"[^\w.\-]+", "_", topic) or "camera"


def _camera_output_path(base_file: Path, camera_topic: str) -> Path:
    """base_file 如 .../clip_preview.mp4 -> .../clip_preview_camera0.mp4"""
    slug = _topic_slug(camera_topic)
    return base_file.with_name(f"{base_file.stem}_{slug}{base_file.suffix}")


def _topics_to_encode(clip: "Clip", cfg: ClipVideoConfig) -> list[tuple[str, list]]:
    by_topic = _group_frames_by_topic(_video_source_frames(clip))
    if not by_topic:
        return []
    if cfg.encode_all_cameras:
        return [(t, by_topic[t]) for t in sorted(by_topic.keys())]
    if cfg.camera_topic and cfg.camera_topic in by_topic:
        return [(cfg.camera_topic, by_topic[cfg.camera_topic])]
    topic = sorted(by_topic.keys())[0]
    return [(topic, by_topic[topic])]


def _frame_durations_sec(
    frame_seq: list,
    *,
    clip_end_timestamp_ns: int,
    fallback_duration_sec: float,
) -> list[float]:
    if not frame_seq:
        return []
    if len(frame_seq) == 1:
        return [max(fallback_duration_sec, 1.0 / 120.0)]

    durations: list[float] = []
    for i in range(len(frame_seq) - 1):
        dt = (frame_seq[i + 1].timestamp_ns - frame_seq[i].timestamp_ns) / 1e9
        durations.append(max(dt, 1.0 / 120.0))
    tail = (clip_end_timestamp_ns - frame_seq[-1].timestamp_ns) / 1e9
    if tail <= 0 and durations:
        tail = durations[-1]
    durations.append(max(tail, 1.0 / 120.0))
    return durations


def _long_edge_fit_image(src: Path, dst: Path, *, max_width: int, max_height: int) -> None:
    """Scale by long-edge (source long → target long), then center; pad short side, crop only if still oversized."""
    with Image.open(src) as im:
        im = im.convert("RGB")
        w, h = im.size
        if w <= 0 or h <= 0:
            raise ValueError(f"invalid image size for {src}: {w}x{h}")
        src_long = max(w, h)
        tgt_long = max(max_width, max_height)
        scale = tgt_long / float(src_long)
        new_w = max(1, int(round(w * scale)))
        new_h = max(1, int(round(h * scale)))
        resized = im.resize((new_w, new_h), Image.Resampling.BILINEAR)
        if new_w > max_width or new_h > max_height:
            left = max(0, (new_w - max_width) // 2)
            top = max(0, (new_h - max_height) // 2)
            resized = resized.crop(
                (left, top, left + min(new_w, max_width), top + min(new_h, max_height))
            )
            new_w, new_h = resized.size
        canvas = Image.new("RGB", (max_width, max_height), (0, 0, 0))
        ox = (max_width - new_w) // 2
        oy = (max_height - new_h) // 2
        canvas.paste(resized, (ox, oy))
        dst.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(dst, format="JPEG", quality=90)


def _encode_one_camera_mp4(
    clip: "Clip",
    frames: list,
    output_path: Path,
    *,
    cfg: ClipVideoConfig,
    camera_topic: str,
) -> str:
    if not frames:
        raise ValueError(f"Clip {clip.clip_id} has no frames for topic {camera_topic}")
    if not clip.audio or not clip.audio.audio_path:
        raise ValueError(f"Clip {clip.clip_id} has no audio for MP4 encoding")

    audio_path = Path(clip.audio.audio_path)
    if not audio_path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg = _resolve_ffmpeg()
    frame_durations = _frame_durations_sec(
        frames,
        clip_end_timestamp_ns=clip.end_timestamp_ns,
        fallback_duration_sec=clip.duration_sec,
    )

    with tempfile.TemporaryDirectory(prefix="oms_clip_video_") as tmp:
        tmp_dir = Path(tmp)
        normalized: list[Path] = []
        for idx, frame in enumerate(frames):
            src = Path(frame.image_path)
            if not src.exists():
                raise FileNotFoundError(f"Frame image not found: {src}")
            dst = tmp_dir / f"frame_{idx:06d}.jpg"
            _long_edge_fit_image(src, dst, max_width=cfg.max_width, max_height=cfg.max_height)
            normalized.append(dst)

        concat_list = tmp_dir / "frames.txt"
        with concat_list.open("w", encoding="utf-8") as f:
            for path, duration in zip(normalized, frame_durations, strict=True):
                escaped = path.resolve().as_posix().replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")
                f.write(f"duration {duration:.6f}\n")
            last = normalized[-1].resolve().as_posix().replace("'", "'\\''")
            f.write(f"file '{last}'\n")

        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-i",
            str(audio_path.resolve()),
            "-c:v",
            cfg.video_codec,
            "-pix_fmt",
            "yuv420p",
            "-crf",
            str(cfg.crf),
            "-c:a",
            cfg.audio_codec,
            "-shortest",
            str(output_path.resolve()),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed for {camera_topic} (code={proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )

    return str(output_path.resolve())


def encode_clip_mp4(
    clip: "Clip",
    output_path: str | Path,
    *,
    config: ClipVideoConfig | None = None,
    camera_topic: str | None = None,
) -> str:
    """将单路相机全量帧合成为 MP4 并 mux WAV（多路请用 render_clip_preview_video）。"""
    cfg = config or ClipVideoConfig()
    output_path = Path(output_path)
    pairs = _topics_to_encode(clip, cfg)
    if camera_topic:
        by_topic = dict(_group_frames_by_topic(_video_source_frames(clip)))
        if camera_topic not in by_topic:
            raise ValueError(f"Camera topic not in clip: {camera_topic}")
        topic, frames = camera_topic, by_topic[camera_topic]
    elif len(pairs) == 1 and not cfg.encode_all_cameras:
        topic, frames = pairs[0]
    elif len(pairs) == 1:
        topic, frames = pairs[0]
    else:
        topic, frames = pairs[0]
        output_path = _camera_output_path(output_path, topic)

    path = _encode_one_camera_mp4(clip, frames, output_path, cfg=cfg, camera_topic=topic)
    meta = cfg.to_dict()
    meta["camera_topic"] = topic
    meta["encoded_frame_count"] = len(frames)
    clip.clip_video_config = meta
    return path


def render_clip_preview_video(
    clip: "Clip",
    output_path: str | Path,
    *,
    config: ClipVideoConfig | None = None,
    frames: list | None = None,
    path_map: dict[str, str] | None = None,
    filename_stem: str | None = None,
    assign_clip_fields: bool = True,
) -> str | None:
    """生成预览 MP4：默认每路相机各一个文件，并写入 clip.clip_video_paths。

    Args:
        frames: 若给定则用该帧列表代替 clip.video_frames/frames。
        path_map: 原始 image_path → 替代路径（如 bbox 图）。
        filename_stem: 覆盖输出文件 stem（默认用 output_path.stem）。
        assign_clip_fields: True 时写入 clip.clip_video_path(s)；bbox 编码应传 False。
    """
    cfg = config or ClipVideoConfig()
    if not cfg.enabled:
        return None
    source = list(frames) if frames is not None else _video_source_frames(clip)
    if not source or not clip.audio:
        return None

    if path_map:
        remapped = []
        for frame in source:
            alt = path_map.get(frame.image_path) or path_map.get(str(Path(frame.image_path).resolve()))
            if alt:
                remapped.append(
                    type(frame)(
                        topic=frame.topic,
                        timestamp_ns=frame.timestamp_ns,
                        image_path=alt,
                        width=getattr(frame, "width", None),
                        height=getattr(frame, "height", None),
                    )
                )
            else:
                remapped.append(frame)
        source = remapped

    base = Path(output_path)
    if filename_stem:
        base = base.with_name(f"{filename_stem}{base.suffix or '.mp4'}")

    by_topic = _group_frames_by_topic(source)
    if not by_topic:
        return None
    if cfg.encode_all_cameras:
        pairs = [(t, by_topic[t]) for t in sorted(by_topic.keys())]
    elif cfg.camera_topic and cfg.camera_topic in by_topic:
        pairs = [(cfg.camera_topic, by_topic[cfg.camera_topic])]
    else:
        topic = sorted(by_topic.keys())[0]
        pairs = [(topic, by_topic[topic])]

    paths: dict[str, str] = {}
    encoded: list[dict[str, Any]] = []
    for topic, topic_frames in pairs:
        if cfg.encode_all_cameras and len(pairs) > 1:
            out = _camera_output_path(base, topic)
        else:
            out = base
        path = _encode_one_camera_mp4(clip, topic_frames, out, cfg=cfg, camera_topic=topic)
        paths[topic] = path
        encoded.append({"camera_topic": topic, "path": path, "encoded_frame_count": len(topic_frames)})

    meta = cfg.to_dict()
    meta["encoded_cameras"] = encoded
    meta["filename_stem"] = base.stem
    clip.clip_video_config = meta
    if assign_clip_fields:
        clip.clip_video_paths = paths
        clip.clip_video_path = paths[pairs[0][0]]
    return paths[pairs[0][0]] if paths else None
