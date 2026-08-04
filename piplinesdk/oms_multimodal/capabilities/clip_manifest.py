"""Clip 跨节点 manifest：extract 写入，asr/label/embed 读取。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from ..pipeline import write_jsonl
from ..rosbag_parser import AudioPayload, Clip, FramePayload, TextPayload


def clip_to_manifest(clip: Clip) -> dict[str, Any]:
    """可序列化 clip 状态（含文件路径），供下游节点 reload。"""
    row = clip.to_meta()
    row["frames"] = [
        {"topic": f.topic, "timestamp_ns": f.timestamp_ns, "image_path": f.image_path}
        for f in clip.frames
    ]
    row["embedding_frames"] = [
        {"topic": f.topic, "timestamp_ns": f.timestamp_ns, "image_path": f.image_path}
        for f in clip.embedding_frames
    ]
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
    frames = [
        FramePayload(
            topic=str(f["topic"]),
            timestamp_ns=int(f["timestamp_ns"]),
            image_path=str(f["image_path"]),
        )
        for f in (row.get("frames") or [])
        if isinstance(f, dict)
    ]
    embedding_frames = [
        FramePayload(
            topic=str(f["topic"]),
            timestamp_ns=int(f["timestamp_ns"]),
            image_path=str(f["image_path"]),
        )
        for f in (row.get("embedding_frames") or [])
        if isinstance(f, dict)
    ]
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
    return Clip(
        clip_id=str(row["clip_id"]),
        bag_name=str(row.get("bag_name") or ""),
        start_timestamp_ns=int(row.get("start_timestamp_ns") or 0),
        end_timestamp_ns=int(row.get("end_timestamp_ns") or 0),
        duration_sec=float(row.get("duration_sec") or 0),
        frames=frames,
        video_frames=frames,
        embedding_frames=embedding_frames or frames[:4],
        audio=audio,
        acoustic_panel_path=row.get("acoustic_panel_path"),
        acoustic_panel_config=row.get("acoustic_panel_config"),
        asr_text=row.get("asr_text"),
        asr_model=row.get("asr_model"),
        clip_video_path=row.get("clip_video_path"),
        clip_video_paths=row.get("clip_video_paths"),
        clip_video_config=row.get("clip_video_config"),
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
