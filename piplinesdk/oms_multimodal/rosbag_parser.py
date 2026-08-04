"""ROS1 rosbag 多模态解析与 clip 构建。

将 bag 中的 image / audio / text topic 解析为 Clip 对象：
- 按 15–20 秒切分 clip（不足 20 秒的 bag 整体作为 1 个 clip）
- 每 clip 包含：完整音频、Omni 用 sample_fps 采样帧、clip 内全量相机帧（供 MP4）、事件文本
- 额外挑选代表帧供 embedding API 使用（最多 4 张，受 qwen3-vl-embedding 限制）

不依赖 ROS 运行时，使用 rosbags 库直接读取 ROS1 bag。
"""
from __future__ import annotations

import io
import json
import logging
import re
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

import numpy as np
from PIL import Image
from rosbags.highlevel import AnyReader
from rosbags.typesys import Stores, get_typestore

from .acoustic_panel import AcousticPanelConfig, render_acoustic_assets
from .clip_video import ClipVideoConfig, render_clip_preview_video

logger = logging.getLogger(__name__)

IMAGE_TYPES = {
    "sensor_msgs/msg/Image",
    "sensor_msgs/msg/CompressedImage",
}

TEXT_TYPES = {
    "std_msgs/msg/String",
    "std_msgs/msg/Header",
}

AUDIO_HINTS = ("audio", "sound", "mic", "voice", "speech")
IMAGE_HINTS = ("image", "camera", "rgb", "dms", "oms", "video", "frame")
TEXT_HINTS = ("event", "text", "msg", "string", "log", "annotation", "label")
AUDIO_META_HINTS = ("audio_info", "audioinfo")


@dataclass
class TopicInfo:
    """Bag 内单个 topic 的元信息。"""

    name: str
    msgtype: str
    modality: str  # image | audio | text | other
    message_count: int = 0


@dataclass
class FramePayload:
    """一帧图像及其落盘路径。"""

    topic: str
    timestamp_ns: int
    image_path: str
    width: int | None = None
    height: int | None = None


@dataclass
class AudioPayload:
    """clip 级拼接后的音频文件。"""

    topic: str
    timestamp_ns: int
    audio_path: str
    format: str
    duration_sec: float | None = None
    sample_rate: int = 48000


@dataclass
class TextPayload:
    """事件/标签类文本消息。"""

    topic: str
    timestamp_ns: int
    text: str


@dataclass
class AudioChunk:
    """原始音频分片（尚未拼接）。"""

    topic: str
    timestamp_ns: int
    pcm: bytes


@dataclass
class Clip:
    """最小处理单元：15–20 秒完整多模态片段。

    Attributes:
        frames: 按 sample_fps 采样的帧序列，供 Omni 作为 video 序列输入。
        video_frames: clip 时间范围内各路相机的全量帧（供预览 MP4，不受 sample_fps 影响）。
        embedding_frames: 每路相机的代表帧（≤4），供 fusion embedding 使用。
        audio: clip 时间范围内的完整音频。
        acoustic_panel_path: 由 clip 音频渲染的 log 频谱图，供 VL-embedding 使用。
        mel_matrix_path: Mel 矩阵 csv（文本），供打标/向量化特征与下游分析。
        mel_feature_text: 压缩后的 Mel 矩阵文本特征（注入 Omni / Embedding text）。
        events: clip 时间范围内的事件文本。
    """

    clip_id: str
    bag_name: str
    start_timestamp_ns: int
    end_timestamp_ns: int
    duration_sec: float
    frames: list[FramePayload] = field(default_factory=list)
    video_frames: list[FramePayload] = field(default_factory=list)
    embedding_frames: list[FramePayload] = field(default_factory=list)
    audio: AudioPayload | None = None
    acoustic_panel_path: str | None = None
    acoustic_panel_config: dict[str, Any] | None = None
    mel_matrix_path: str | None = None
    mel_matrix_npy_path: str | None = None
    mel_matrix_meta_path: str | None = None
    mel_matrix_shape: list[int] | None = None
    mel_feature_text: str | None = None
    asr_text: str | None = None
    asr_model: str | None = None
    clip_video_path: str | None = None
    clip_video_paths: dict[str, str] | None = None
    clip_video_config: dict[str, Any] | None = None
    events: list[TextPayload] = field(default_factory=list)
    source_topics: list[str] = field(default_factory=list)

    def fusion_text(self) -> str:
        """合并 clip 内所有事件文本，供 embedding 与 prompt 使用。"""
        parts: list[str] = []
        for event in self.events:
            if event.text.strip():
                parts.append(event.text.strip())
        return "\n".join(parts)

    def speech_context_text(self) -> str:
        """事件文本 + ASR 文本 + Mel 矩阵特征（供多模态文本侧输入）。"""
        parts: list[str] = []
        if self.asr_text and self.asr_text.strip():
            parts.append(f"[ASR transcript]\n{self.asr_text.strip()}")
        fusion = self.fusion_text()
        if fusion:
            parts.append(f"[Event texts]\n{fusion}")
        if self.mel_feature_text and self.mel_feature_text.strip():
            parts.append(self.mel_feature_text.strip())
        return "\n\n".join(parts)

    def to_meta(self) -> dict[str, Any]:
        return {
            "clip_id": self.clip_id,
            "bag_name": self.bag_name,
            "start_timestamp_ns": self.start_timestamp_ns,
            "end_timestamp_ns": self.end_timestamp_ns,
            "duration_sec": round(self.duration_sec, 3),
            "source_topics": self.source_topics,
            "frame_topics": sorted({f.topic for f in self.frames}),
            "frame_count": len(self.frames),
            "video_frame_topics": sorted({f.topic for f in self.video_frames}),
            "video_frame_count": len(self.video_frames),
            "embedding_frame_count": len(self.embedding_frames),
            "audio_topic": self.audio.topic if self.audio else None,
            "audio_duration_sec": self.audio.duration_sec if self.audio else None,
            "acoustic_panel_path": self.acoustic_panel_path,
            "acoustic_panel_config": self.acoustic_panel_config,
            "mel_matrix_path": self.mel_matrix_path,
            "mel_matrix_npy_path": self.mel_matrix_npy_path,
            "mel_matrix_meta_path": self.mel_matrix_meta_path,
            "mel_matrix_shape": self.mel_matrix_shape,
            "mel_feature_text": self.mel_feature_text,
            "asr_text": self.asr_text,
            "asr_model": self.asr_model,
            "clip_video_path": self.clip_video_path,
            "clip_video_paths": self.clip_video_paths,
            "clip_video_config": self.clip_video_config,
            "event_topics": sorted({e.topic for e in self.events}),
            "event_text": self.fusion_text(),
        }


# Backward-compatible alias
Segment = Clip


def _guess_modality(topic: str, msgtype: str) -> str:
    """根据 topic 名和 msgtype 推断 modality（image/audio/text/other）。"""
    lower = topic.lower()
    if any(h in lower for h in AUDIO_META_HINTS):
        return "other"
    if msgtype in IMAGE_TYPES or any(h in lower for h in IMAGE_HINTS):
        return "image"
    if msgtype in TEXT_TYPES or any(h in lower for h in TEXT_HINTS):
        return "text"
    if msgtype.endswith("/AudioData") or any(h in lower for h in AUDIO_HINTS):
        return "audio"
    return "other"


def inspect_bag(bag_path: Path) -> list[TopicInfo]:
    """扫描 bag，返回所有 topic 的元信息列表（不解析消息体）。"""
    typestore = get_typestore(Stores.ROS1_NOETIC)
    counts: dict[str, int] = {}
    msgtypes: dict[str, str] = {}

    with AnyReader([bag_path], default_typestore=typestore) as reader:
        for connection in reader.connections:
            msgtypes[connection.topic] = connection.msgtype
            counts[connection.topic] = 0
        for connection, _timestamp, _rawdata in reader.messages():
            counts[connection.topic] = counts.get(connection.topic, 0) + 1

    topics: list[TopicInfo] = []
    for topic, msgtype in sorted(msgtypes.items()):
        topics.append(
            TopicInfo(
                name=topic,
                msgtype=msgtype,
                modality=_guess_modality(topic, msgtype),
                message_count=counts.get(topic, 0),
            )
        )
    return topics


def _safe_name(value: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", value.strip("/")) or "root"


def _to_bytes(data: Any) -> bytes:
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    if isinstance(data, np.ndarray):
        return data.tobytes()
    if isinstance(data, list):
        return bytes(data)
    raise TypeError(f"Unsupported binary payload type: {type(data)}")


def _image_to_file_bytes(msg: Any, msgtype: str) -> tuple[bytes, int, int, str]:
    if msgtype == "sensor_msgs/msg/CompressedImage":
        ext = "jpg"
        fmt = getattr(msg, "format", "") or ""
        if "png" in fmt.lower():
            ext = "png"
        return _to_bytes(msg.data), 0, 0, ext
    encoding = getattr(msg, "encoding", "rgb8").lower()
    height = int(msg.height)
    width = int(msg.width)
    arr = np.frombuffer(_to_bytes(msg.data), dtype=np.uint8)
    if encoding in {"rgb8", "bgr8"}:
        arr = arr.reshape((height, width, 3))
        if encoding == "bgr8":
            arr = arr[:, :, ::-1]
        image = Image.fromarray(arr, mode="RGB")
    elif encoding in {"mono8", "8uc1"}:
        arr = arr.reshape((height, width))
        image = Image.fromarray(arr, mode="L")
    else:
        raise ValueError(f"Unsupported image encoding: {encoding}")
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue(), width, height, "png"


def _extract_text(msg: Any, msgtype: str) -> str:
    if msgtype == "std_msgs/msg/String":
        return str(msg.data)
    if hasattr(msg, "data") and isinstance(msg.data, str):
        return msg.data
    return json.dumps(asdict(msg) if hasattr(msg, "__dataclass_fields__") else str(msg), ensure_ascii=False)


def _write_wav_pcm16(path: Path, pcm: bytes, sample_rate: int = 48000, channels: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        data_size = len(pcm)
        byte_rate = sample_rate * channels * 2
        block_align = channels * 2
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + data_size))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, channels, sample_rate, byte_rate, block_align, 16))
        f.write(b"data")
        f.write(struct.pack("<I", data_size))
        f.write(pcm)


def _extract_audio_chunk(msg: Any) -> bytes:
    if hasattr(msg, "data"):
        return _to_bytes(msg.data)
    payload = asdict(msg) if hasattr(msg, "__dataclass_fields__") else {}
    for key in ("audio", "pcm", "samples", "chunk"):
        if key in payload:
            return _to_bytes(payload[key])
    raise ValueError("Unsupported audio chunk message")


class RosbagExtractor:
    """从 ROS1 bag 提取并构建 Clip 迭代器。"""

    def __init__(self, bag_path: Path, work_dir: Path):
        self.bag_path = bag_path
        self.work_dir = work_dir
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.typestore = get_typestore(Stores.ROS1_NOETIC)

    def topics(self) -> list[TopicInfo]:
        return inspect_bag(self.bag_path)

    def _load_audio_info(self, reader: AnyReader) -> tuple[int, int]:
        sample_rate = 48000
        channels = 1
        for connection, _timestamp, rawdata in reader.messages():
            if connection.topic.endswith("/audio_info") or connection.msgtype.endswith("/AudioInfo"):
                msg = reader.deserialize(rawdata, connection.msgtype)
                sample_rate = int(getattr(msg, "sample_rate", sample_rate) or sample_rate)
                channels = int(getattr(msg, "channels", channels) or channels)
                break
        return sample_rate, channels

    def iter_clips(
        self,
        *,
        clip_min_sec: float = 15.0,
        clip_max_sec: float = 20.0,
        sample_fps: float = 1.0,
        max_clips: int | None = None,
        acoustic_panel_config: AcousticPanelConfig | None = None,
        clip_video_config: ClipVideoConfig | None = None,
    ) -> Iterator[Clip]:
        """按时间切分 clip 并 yield 多模态 Clip 对象。

        Args:
            clip_min_sec: 最短 clip 时长；尾段不足此值时合并到前一段。
            clip_max_sec: 最长 clip 时长；bag 不超过此值时整 bag 为 1 clip。
            sample_fps: 每路相机每秒采样帧数（供 Omni video 序列）。
            max_clips: 最多 yield 几个 clip，None 表示不限制。
            acoustic_panel_config: 声学面板渲染参数；None 时使用默认配置。
            clip_video_config: clip 预览 MP4（帧序列 + WAV）参数；None 时使用默认配置。
        """
        panel_config = acoustic_panel_config or AcousticPanelConfig()
        video_config = clip_video_config or ClipVideoConfig()
        topics = {t.name: t for t in self.topics()}
        if not any(t.modality in {"image", "audio", "text"} for t in topics.values()):
            raise RuntimeError("No image/audio/text topics detected in bag")

        frames: list[FramePayload] = []
        audio_chunks: list[AudioChunk] = []
        texts: list[TextPayload] = []

        with AnyReader([self.bag_path], default_typestore=self.typestore) as reader:
            sample_rate, _channels = self._load_audio_info(reader)
            for connection, timestamp, rawdata in reader.messages():
                topic = connection.topic
                msgtype = connection.msgtype
                msg = reader.deserialize(rawdata, connection.msgtype)
                info = topics.get(topic)
                if info is None:
                    continue
                if info.modality == "image":
                    blob, width, height, ext = _image_to_file_bytes(msg, msgtype)
                    rel = self.work_dir / "frames" / _safe_name(topic) / f"{timestamp}.{ext}"
                    rel.parent.mkdir(parents=True, exist_ok=True)
                    rel.write_bytes(blob)
                    frames.append(
                        FramePayload(
                            topic=topic,
                            timestamp_ns=timestamp,
                            image_path=str(rel),
                            width=width or None,
                            height=height or None,
                        )
                    )
                elif info.modality == "audio":
                    audio_chunks.append(
                        AudioChunk(
                            topic=topic,
                            timestamp_ns=timestamp,
                            pcm=_extract_audio_chunk(msg),
                        )
                    )
                elif info.modality == "text":
                    texts.append(
                        TextPayload(
                            topic=topic,
                            timestamp_ns=timestamp,
                            text=_extract_text(msg, msgtype),
                        )
                    )

        if not frames and not audio_chunks and not texts:
            return

        start_ts = min(
            [frames[0].timestamp_ns] if frames else []
            + [audio_chunks[0].timestamp_ns] if audio_chunks else []
            + [texts[0].timestamp_ns] if texts else []
        )
        end_ts = max(
            [frames[-1].timestamp_ns] if frames else []
            + [audio_chunks[-1].timestamp_ns] if audio_chunks else []
            + [texts[-1].timestamp_ns] if texts else []
        )

        clip_ranges = _split_clip_ranges(start_ts, end_ts, clip_min_sec, clip_max_sec)
        for clip_idx, (clip_start, clip_end) in enumerate(clip_ranges):
            if max_clips is not None and clip_idx >= max_clips:
                break
            clip_id = f"{self.bag_path.stem}_{clip_idx:04d}"
            duration_sec = (clip_end - clip_start) / 1e9

            clip_frames = _sample_frames_in_range(frames, clip_start, clip_end, sample_fps=sample_fps)
            video_frames = _frames_in_range(frames, clip_start, clip_end)
            embedding_frames = _pick_embedding_frames(clip_frames, max_images=4)
            clip_events = _within_range(texts, clip_start, clip_end)
            clip_audio = _build_clip_audio(
                audio_chunks,
                clip_start,
                clip_end,
                sample_rate=sample_rate,
                output_path=self.work_dir / "clips" / clip_id / "audio.wav",
            )
            acoustic_panel_path: str | None = None
            mel_matrix_path: str | None = None
            mel_matrix_npy_path: str | None = None
            mel_matrix_meta_path: str | None = None
            mel_matrix_shape: list[int] | None = None
            mel_feature_text: str | None = None
            if clip_audio:
                clip_dir = self.work_dir / "clips" / clip_id
                assets = render_acoustic_assets(
                    clip_audio.audio_path,
                    clip_dir,
                    config=panel_config,
                    panel_filename="acoustic_panel.png",
                    matrix_stem="mel_matrix",
                )
                acoustic_panel_path = assets.get("acoustic_panel_path")
                mel_matrix_path = assets.get("mel_matrix_path")
                mel_matrix_npy_path = assets.get("mel_matrix_npy_path")
                mel_matrix_meta_path = assets.get("mel_matrix_meta_path")
                mel_matrix_shape = assets.get("mel_matrix_shape")
                mel_feature_text = assets.get("mel_feature_text")

            clip_video_path: str | None = None
            clip_video_meta: dict[str, Any] | None = None

            source_topics = sorted(
                {
                    *(f.topic for f in clip_frames),
                    *({clip_audio.topic} if clip_audio else set()),
                    *(e.topic for e in clip_events),
                }
            )
            if clip_frames or clip_audio or clip_events:
                clip = Clip(
                    clip_id=clip_id,
                    bag_name=self.bag_path.name,
                    start_timestamp_ns=clip_start,
                    end_timestamp_ns=clip_end,
                    duration_sec=duration_sec,
                    frames=clip_frames,
                    video_frames=video_frames,
                    embedding_frames=embedding_frames,
                    audio=clip_audio,
                    acoustic_panel_path=acoustic_panel_path,
                    acoustic_panel_config=panel_config.to_dict(),
                    mel_matrix_path=mel_matrix_path,
                    mel_matrix_npy_path=mel_matrix_npy_path,
                    mel_matrix_meta_path=mel_matrix_meta_path,
                    mel_matrix_shape=mel_matrix_shape,
                    mel_feature_text=mel_feature_text,
                    events=clip_events,
                    source_topics=source_topics,
                )
                if video_config.enabled and video_frames and clip_audio:
                    clip_dir = self.work_dir / "clips" / clip_id
                    try:
                        render_clip_preview_video(
                            clip,
                            clip_dir / video_config.filename,
                            config=video_config,
                        )
                        clip_video_path = clip.clip_video_path
                        clip_video_meta = clip.clip_video_config
                    except Exception as exc:
                        logger.warning(
                            "Clip preview MP4 failed for %s: %s",
                            clip_id,
                            exc,
                            exc_info=logger.isEnabledFor(logging.DEBUG),
                        )
                        clip_video_meta = video_config.to_dict()
                clip.clip_video_path = clip_video_path
                clip.clip_video_config = clip_video_meta
                yield clip


def _split_clip_ranges(
    start_ns: int, end_ns: int, min_sec: float, max_sec: float
) -> list[tuple[int, int]]:
    """Split timeline into 15-20s clips; shorter bags become a single clip."""
    total_sec = (end_ns - start_ns) / 1e9
    if total_sec <= max_sec:
        return [(start_ns, end_ns)]

    max_ns = int(max_sec * 1e9)
    min_ns = int(min_sec * 1e9)
    ranges: list[tuple[int, int]] = []
    cursor = start_ns
    while cursor < end_ns:
        remaining = end_ns - cursor
        if remaining <= max_ns:
            if remaining >= min_ns or not ranges:
                ranges.append((cursor, end_ns))
            else:
                prev_start, _ = ranges.pop()
                ranges.append((prev_start, end_ns))
            break
        ranges.append((cursor, cursor + max_ns))
        cursor += max_ns
    return ranges


def _sample_frames_in_range(
    frames: list[FramePayload],
    start_ns: int,
    end_ns: int,
    *,
    sample_fps: float,
) -> list[FramePayload]:
    """在 clip 时间范围内，按 sample_fps 对每路相机均匀采样。"""
    if not frames or sample_fps <= 0:
        return _frames_in_range(frames, start_ns, end_ns)

    step_ns = int(1e9 / sample_fps)
    by_topic: dict[str, list[FramePayload]] = {}
    for frame in frames:
        if start_ns <= frame.timestamp_ns < end_ns:
            by_topic.setdefault(frame.topic, []).append(frame)

    sampled: list[FramePayload] = []
    for topic_frames in by_topic.values():
        topic_frames.sort(key=lambda x: x.timestamp_ns)
        cursor = start_ns
        while cursor < end_ns:
            candidate = min(topic_frames, key=lambda f: abs(f.timestamp_ns - cursor))
            if start_ns <= candidate.timestamp_ns < end_ns:
                sampled.append(candidate)
            cursor += step_ns

    sampled.sort(key=lambda x: (x.timestamp_ns, x.topic))
    # Deduplicate identical timestamps per topic
    seen: set[tuple[str, int]] = set()
    unique: list[FramePayload] = []
    for frame in sampled:
        key = (frame.topic, frame.timestamp_ns)
        if key in seen:
            continue
        seen.add(key)
        unique.append(frame)
    return unique


def _frames_in_range(frames: list[FramePayload], start_ns: int, end_ns: int) -> list[FramePayload]:
    return [f for f in frames if start_ns <= f.timestamp_ns < end_ns]


def _pick_embedding_frames(frames: list[FramePayload], max_images: int = 4) -> list[FramePayload]:
    """Pick representative frames for fusion embedding (API limit: 5 images)."""
    if len(frames) <= max_images:
        return frames
    by_topic: dict[str, list[FramePayload]] = {}
    for frame in frames:
        by_topic.setdefault(frame.topic, []).append(frame)
    picked: list[FramePayload] = []
    for topic_frames in by_topic.values():
        topic_frames.sort(key=lambda x: x.timestamp_ns)
        mid = topic_frames[len(topic_frames) // 2]
        picked.append(mid)
    picked.sort(key=lambda x: x.topic)
    if len(picked) > max_images:
        step = max(1, len(picked) // max_images)
        picked = picked[::step][:max_images]
    return picked


def _within_range(items: list[TextPayload], start_ns: int, end_ns: int) -> list[TextPayload]:
    return [x for x in items if start_ns <= x.timestamp_ns < end_ns]


def _build_clip_audio(
    chunks: list[AudioChunk],
    start_ns: int,
    end_ns: int,
    *,
    sample_rate: int,
    output_path: Path,
) -> AudioPayload | None:
    """将 clip 时间范围内的音频 chunk 拼接为单个 WAV 文件。"""
    selected = [c for c in chunks if start_ns <= c.timestamp_ns < end_ns]
    if not selected:
        return None
    pcm = b"".join(c.pcm for c in selected)
    if not pcm:
        return None
    _write_wav_pcm16(output_path, pcm, sample_rate=sample_rate)
    duration = len(pcm) / (2 * sample_rate)
    return AudioPayload(
        topic=selected[0].topic,
        timestamp_ns=selected[0].timestamp_ns,
        audio_path=str(output_path),
        format="wav",
        duration_sec=duration,
        sample_rate=sample_rate,
    )


def _build_segment_audio(
    chunks: list[AudioChunk],
    start_ns: int,
    end_ns: int,
    *,
    sample_rate: int,
    output_path: Path,
) -> AudioPayload | None:
    return _build_clip_audio(chunks, start_ns, end_ns, sample_rate=sample_rate, output_path=output_path)
