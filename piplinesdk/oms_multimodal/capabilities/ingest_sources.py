"""Capability: ingest_sources — build clips_index from raw video / audio / text.

Used when the user uploads media instead of (or without) a rosbag:
- video present → sample frames (抽帧) for VL/label; reuse file as preview MP4 (skip encode_preview)
- audio present → copy/link wav for ASR
- text present → attach as event / ASR seed for labeling
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from ..config import ClipConfig
from ..pipeline import _clip_video_row, write_jsonl
from ..rosbag_parser import AudioPayload, Clip, FramePayload, TextPayload
from .clip_manifest import write_clips_index
from .types import ExtractResult, RunContext

logger = logging.getLogger(__name__)

_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
_AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac"}
_TEXT_EXTS = {".txt", ".json", ".md", ".csv"}


def _as_path(raw: Any, base: Path | None = None) -> Path | None:
    if raw is None:
        return None
    p = Path(str(raw))
    if not p.is_absolute() and base is not None:
        p = base / p
    return p if p.is_file() else None


def _read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _sample_video_frames(
    video_path: Path,
    out_dir: Path,
    *,
    sample_fps: float,
    topic: str = "/source/video",
) -> tuple[list[FramePayload], float]:
    """Sample JPEGs from a video file. Returns (frames, duration_sec)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        import cv2  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("opencv-python-headless required to sample video frames") from exc

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {video_path}")

    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration_sec = (frame_count / fps) if frame_count > 0 else 0.0
    interval = max(1, int(round(fps / max(sample_fps, 0.01))))

    frames: list[FramePayload] = []
    idx = 0
    kept = 0
    while True:
        ok, mat = cap.read()
        if not ok:
            break
        if idx % interval == 0:
            ts_ns = int((idx / fps) * 1_000_000_000)
            dest = out_dir / f"frame_{kept:05d}.jpg"
            cv2.imwrite(str(dest), mat)
            frames.append(
                FramePayload(topic=topic, timestamp_ns=ts_ns, image_path=str(dest.resolve()))
            )
            kept += 1
        idx += 1
    cap.release()

    if duration_sec <= 0 and frames:
        duration_sec = frames[-1].timestamp_ns / 1_000_000_000 + (1.0 / max(sample_fps, 0.01))
    return frames, duration_sec


def _probe_audio_duration_sec(path: Path) -> float | None:
    try:
        import wave

        if path.suffix.lower() == ".wav":
            with wave.open(str(path), "rb") as wf:
                rate = wf.getframerate() or 1
                return float(wf.getnframes()) / float(rate)
    except Exception:  # noqa: BLE001
        return None
    return None


def resolve_source_paths(
    manifest: dict[str, Any],
    *,
    manifest_dir: Path | None = None,
) -> dict[str, Path | None]:
    base = manifest_dir
    video = _as_path(manifest.get("video") or manifest.get("video_path"), base)
    audio = _as_path(manifest.get("audio") or manifest.get("audio_path"), base)
    text = _as_path(manifest.get("text") or manifest.get("text_path"), base)
    return {"video": video, "audio": audio, "text": text}


def ingest_sources(
    ctx: RunContext,
    *,
    manifest: dict[str, Any] | None = None,
    manifest_path: Path | str | None = None,
    clip_config: ClipConfig | None = None,
    sample_fps: float | None = None,
) -> ExtractResult:
    """Build one Clip from uploaded modalities; write clips_index + clip_videos."""
    cfg = clip_config or ClipConfig()
    fps = float(sample_fps if sample_fps is not None else cfg.sample_fps)
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    ctx.work_dir.mkdir(parents=True, exist_ok=True)

    man_path = Path(manifest_path) if manifest_path else None
    if manifest is None:
        if man_path is None:
            for name in ("source_manifest.json", "sources_manifest.json"):
                cand = ctx.run_dir / name
                if cand.is_file():
                    man_path = cand
                    break
        if man_path is None or not man_path.is_file():
            raise FileNotFoundError("source_manifest.json not found for ingest_sources")
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("source_manifest must be a JSON object")

    man_dir = man_path.parent if man_path is not None else None
    # Also try paths relative to work sources/ mirror
    paths = resolve_source_paths(manifest, manifest_dir=man_dir)
    if paths["video"] is None and paths["audio"] is None and paths["text"] is None:
        # Retry against ctx.work_dir / sources
        paths = resolve_source_paths(manifest, manifest_dir=ctx.work_dir / "sources")
    if paths["video"] is None and paths["audio"] is None and paths["text"] is None:
        raise ValueError("source_manifest has no readable video/audio/text files")

    clip_id = str(manifest.get("clip_id") or ctx.clip_id or "source_clip_0")
    bag_name = str(manifest.get("source_name") or "raw_sources")
    clip_dir = ctx.work_dir / "clips" / "source_0000"
    clip_dir.mkdir(parents=True, exist_ok=True)

    frames: list[FramePayload] = []
    duration_sec = 0.0
    video_path = paths["video"]
    preview_video: Path | None = None

    if video_path is not None:
        frames_dir = clip_dir / "frames"
        frames, duration_sec = _sample_video_frames(
            video_path, frames_dir, sample_fps=fps, topic="/source/video"
        )
        # Reuse uploaded video as preview (skip encode_preview)
        dest_mp4 = clip_dir / "clip_preview_camera0.mp4"
        if video_path.resolve() != dest_mp4.resolve():
            shutil.copy2(video_path, dest_mp4)
        preview_video = dest_mp4

    audio_payload: AudioPayload | None = None
    audio_path = paths["audio"]
    if audio_path is not None:
        dest_audio = clip_dir / f"audio{audio_path.suffix.lower() or '.wav'}"
        if audio_path.resolve() != dest_audio.resolve():
            shutil.copy2(audio_path, dest_audio)
        # Prefer .wav name for downstream ASR helpers
        if dest_audio.suffix.lower() != ".wav":
            wav_dest = clip_dir / "audio.wav"
            shutil.copy2(dest_audio, wav_dest)
            dest_audio = wav_dest
        else:
            # ensure canonical name
            canonical = clip_dir / "audio.wav"
            if dest_audio.resolve() != canonical.resolve():
                shutil.copy2(dest_audio, canonical)
                dest_audio = canonical
        aud_dur = _probe_audio_duration_sec(dest_audio)
        if aud_dur and aud_dur > duration_sec:
            duration_sec = aud_dur
        audio_payload = AudioPayload(
            topic="/source/audio",
            timestamp_ns=0,
            audio_path=str(dest_audio.resolve()),
            format=dest_audio.suffix.lstrip(".") or "wav",
            duration_sec=aud_dur,
            sample_rate=16000,
        )

    events: list[TextPayload] = []
    asr_text: str | None = None
    text_path = paths["text"]
    if text_path is not None:
        text_body = _read_text_file(text_path).replace("\r\n", "\n").replace("\r", "\n").strip()
        dest_txt = clip_dir / "source_text.txt"
        dest_txt.write_text(text_body, encoding="utf-8")
        events.append(
            TextPayload(topic="/source/text", timestamp_ns=0, text=text_body)
        )
        # Seed ASR field so label can use text without running ASR when audio absent
        asr_text = text_body
        if duration_sec <= 0:
            duration_sec = max(float(cfg.min_sec), 1.0)

    if duration_sec <= 0:
        duration_sec = max(float(cfg.min_sec), 1.0)

    end_ns = int(duration_sec * 1_000_000_000)
    embedding_frames = frames[:4]
    clip = Clip(
        clip_id=clip_id,
        bag_name=bag_name,
        start_timestamp_ns=0,
        end_timestamp_ns=end_ns,
        duration_sec=duration_sec,
        frames=frames,
        video_frames=list(frames),
        embedding_frames=embedding_frames,
        audio=audio_payload,
        asr_text=asr_text,
        asr_model="source_text" if asr_text and paths["audio"] is None else None,
        clip_video_path=str(preview_video.resolve()) if preview_video else None,
        clip_video_paths={"/source/video": str(preview_video.resolve())} if preview_video else None,
        events=events,
        source_topics=[
            t
            for t, p in (
                ("/source/video", video_path),
                ("/source/audio", audio_path),
                ("/source/text", text_path),
            )
            if p is not None
        ],
    )

    # Persist manifest copy under run_dir for planner re-inspect
    out_manifest = ctx.run_dir / "source_manifest.json"
    if man_path is None or man_path.resolve() != out_manifest.resolve():
        payload = dict(manifest)
        payload.setdefault("clip_id", clip_id)
        payload.setdefault(
            "modalities",
            [m for m, p in (("video", video_path), ("audio", audio_path), ("text", text_path)) if p],
        )
        payload["has_preencoded_video"] = bool(video_path)
        out_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    clip_rows = write_clips_index(ctx.clips_index_path, iter([clip]))
    video_count = write_jsonl(ctx.videos_path, (_clip_video_row(c) for c in [clip]))
    logger.info(
        "ingest_sources clip=%s frames=%s audio=%s text=%s duration=%.2fs",
        clip_id,
        len(frames),
        bool(audio_payload),
        bool(events),
        duration_sec,
    )
    return ExtractResult(
        clips_index=ctx.clips_index_path,
        videos_out=ctx.videos_path,
        clip_rows=clip_rows,
        video_rows=video_count,
        bag=bag_name,
        topics=[
            {"name": t, "modality": m, "message_count": 1}
            for t, m, p in (
                ("/source/video", "image", video_path),
                ("/source/audio", "audio", audio_path),
                ("/source/text", "text", text_path),
            )
            if p is not None
        ],
    )
