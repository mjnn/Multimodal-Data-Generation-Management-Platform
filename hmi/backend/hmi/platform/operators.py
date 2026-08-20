"""Code-registered preprocess / detect operators (DataType recipes only reference ids)."""

from __future__ import annotations

from typing import Any

SOURCE_KINDS = frozenset({"rosbag", "video", "image", "audio", "text"})

OPERATORS: dict[str, dict[str, Any]] = {
    "parse_bag": {
        "op_id": "parse_bag",
        "title": "解析 rosbag",
        "input_kinds": ["rosbag"],
        "product": "frames_audio_topics",
        "params_schema": {},
    },
    "extract_frames": {
        "op_id": "extract_frames",
        "title": "视频抽帧",
        "input_kinds": ["video"],
        "product": "frames",
        "params_schema": {"sample_fps": {"type": "number"}},
    },
    "encode_preview": {
        "op_id": "encode_preview",
        "title": "编码预览视频",
        "input_kinds": ["image", "video"],
        "product": "preview_mp4",
        "params_schema": {},
    },
    "transcribe": {
        "op_id": "transcribe",
        "title": "ASR",
        "input_kinds": ["audio"],
        "product": "asr_jsonl",
        "params_schema": {},
    },
    "mel_spectrogram": {
        "op_id": "mel_spectrogram",
        "title": "梅尔频谱",
        "input_kinds": ["audio"],
        "product": "mel_matrix",
        "params_schema": {},
    },
    "parse_head_dat": {
        "op_id": "parse_head_dat",
        "title": "解析 HEAD .dat 阵列",
        "input_kinds": ["audio"],
        "product": "pcm_pa_wavs",
        "params_schema": {},
    },
    "stft_spectrogram": {
        "op_id": "stft_spectrogram",
        "title": "STFT 频谱图",
        "input_kinds": ["audio"],
        "product": "stft_matrix",
        "params_schema": {},
    },
    "third_octave": {
        "op_id": "third_octave",
        "title": "1/3 倍频程带级",
        "input_kinds": ["audio"],
        "product": "third_octave_json",
        "params_schema": {},
    },
    "spl_timeline": {
        "op_id": "spl_timeline",
        "title": "SPL 时间线",
        "input_kinds": ["audio"],
        "product": "spl_jsonl",
        "params_schema": {},
    },
    "text_to_json": {
        "op_id": "text_to_json",
        "title": "文本结构化为 JSON",
        "input_kinds": ["text"],
        "product": "structured_json",
        "params_schema": {"schema_id": {"type": "string"}},
    },
    "detect_bbox": {
        "op_id": "detect_bbox",
        "title": "BBox 检测",
        "input_kinds": ["image", "video", "rosbag"],
        "product": "bboxes_jsonl",
        "params_schema": {
            "detector": {"enum": ["opencv", "yolo"]},
            "yolo_classes": {"type": "string"},
        },
    },
}

BBOX_DETECTORS = frozenset({"opencv", "yolo"})


def list_operators() -> list[dict[str, Any]]:
    return [dict(v) for v in OPERATORS.values()]
