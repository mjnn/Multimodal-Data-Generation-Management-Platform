"""Clip 跨节点 manifest：extract 写入，asr/label/embed/bbox/encode 读取。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from ..pipeline import write_jsonl
from ..rosbag_parser import AudioPayload, Clip, FramePayload, TextPayload


def _frames_to_rows(frames: list[FramePayload]) -> list[dict[str, Any]]:
    return [
        {"topic": f.topic, "timestamp_ns": f.timestamp_ns, "image_path": f.image_path}
        for f in frames
    ]


def _frames_from_rows(rows: Any) -> list[FramePayload]:
    out: list[FramePayload] = []
    for f in rows or []:
        if not isinstance(f, dict):
            continue
        out.append(
            FramePayload(
                topic=str(f["topic"]),
                timestamp_ns=int(f["timestamp_ns"]),
                image_path=str(f["image_path"]),
            )
        )
    return out


def clip_to_manifest(clip: Clip) -> dict[str, Any]:
    """可序列化 clip 状态（含文件路径），供下游节点 reload。"""
    row = clip.to_meta()
    row["frames"] = _frames_to_rows(clip.frames)
    # Persist full-rate frames so encode_preview can run after extract without inline encode.
    row["video_frames"] = _frames_to_rows(clip.video_frames or clip.frames)
    row["embedding_frames"] = _frames_to_rows(clip.embedding_frames)
    row["events"] = [
        {"topic": e.topic, "timestamp_ns": e.timestamp_ns, "text": e.text} for e in clip.events
    ]
    if clip.audio:
        row["audio"] = {
            "topic": clip.audio.topic,
            "timestamp_ns": clip.audio.timestamp_ns,
            "audio_path": clip.audio.audio_path,
            "format": clip.audio.format,
            "duration_sec": clip.audio.duration_sec,
            "sample_rate": clip.audio.sample_rate,
        }
    return row


def clip_from_manifest(row: dict[str, Any]) -> Clip:
    frames = _frames_from_rows(row.get("frames"))
    video_frames = _frames_from_rows(row.get("video_frames")) or list(frames)
    embedding_frames = _frames_from_rows(row.get("embedding_frames")) or frames[:4]
    audio_raw = row.get("audio")
    audio = None
    if isinstance(audio_raw, dict) and audio_raw.get("audio_path"):
        audio = AudioPayload(
            topic=str(audio_raw.get("topic") or ""),
            timestamp_ns=int(audio_raw.get("timestamp_ns") or 0),
            audio_path=str(audio_raw["audio_path"]),
            format=str(audio_raw.get("format") or "wav"),
            duration_sec=audio_raw.get("duration_sec"),
            sample_rate=int(audio_raw.get("sample_rate") or 48000),
        )
    events = [
        TextPayload(
            topic=str(e["topic"]),
            timestamp_ns=int(e["timestamp_ns"]),
            text=str(e.get("text") or ""),
        )
        for e in (row.get("events") or [])
        if isinstance(e, dict)
    ]
    bbox_paths = row.get("bbox_frame_paths")
    if bbox_paths is not None and not isinstance(bbox_paths, dict):
        bbox_paths = None
    return Clip(
        clip_id=str(row["clip_id"]),
        bag_name=str(row.get("bag_name") or ""),
        start_timestamp_ns=int(row.get("start_timestamp_ns") or 0),
        end_timestamp_ns=int(row.get("end_timestamp_ns") or 0),
        duration_sec=float(row.get("duration_sec") or 0),
        frames=frames,
        video_frames=video_frames,
        embedding_frames=embedding_frames,
        audio=audio,
        acoustic_panel_path=row.get("acoustic_panel_path"),
        acoustic_panel_config=row.get("acoustic_panel_config"),
        mel_matrix_path=row.get("mel_matrix_path"),
        mel_matrix_npy_path=row.get("mel_matrix_npy_path"),
        mel_matrix_meta_path=row.get("mel_matrix_meta_path"),
        mel_matrix_shape=row.get("mel_matrix_shape"),
        mel_feature_text=row.get("mel_feature_text"),
        asr_text=row.get("asr_text"),
        asr_model=row.get("asr_model"),
        clip_video_path=row.get("clip_video_path"),
        clip_video_paths=row.get("clip_video_paths"),
        clip_video_config=row.get("clip_video_config"),
        bbox_enabled=bool(row.get("bbox_enabled")),
        bbox_frame_paths=bbox_paths,
        clip_video_bbox_path=row.get("clip_video_bbox_path"),
        clip_video_bbox_paths=row.get("clip_video_bbox_paths"),
        events=events,
        source_topics=list(row.get("source_topics") or []),
    )


def read_clips_index(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def write_clips_index(path: Path, clips: Iterator[Clip]) -> int:
    return write_jsonl(path, (clip_to_manifest(c) for c in clips))


def load_clips_from_index(path: Path) -> list[Clip]:
    return [clip_from_manifest(row) for row in read_clips_index(path)]
