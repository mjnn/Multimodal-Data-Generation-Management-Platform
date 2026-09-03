"""Code-registered preprocess / detect / AI-stage operators (DataType recipes only reference ids)."""

from __future__ import annotations

from typing import Any

from hmi.platform.file_kinds import (
    AUDIO_EXTS,
    BAG_EXTS,
    IMAGE_EXTS,
    PARSE_BAG_MODALITIES,
    SOURCE_KINDS,
    TEXT_EXTS,
    VIDEO_EXTS,
    list_source_kinds,
    normalize_parse_bag_modality,
    normalize_source_kind,
)

BBOX_DETECTORS = frozenset({"opencv", "yolo"})
LABEL_MODELS = ("default", "nvh_sem_ast", "nvh_sem_heuristic")
OPERATOR_ROLES = frozenset({"preprocess", "stage"})

CATEGORY_ORDER = ("parse", "encode", "audio", "detect_ai")
CATEGORY_TITLES = {
    "parse": "解析",
    "encode": "编码与变换",
    "audio": "音频分析",
    "detect_ai": "检测与 AI",
}

_VIDEO = sorted(VIDEO_EXTS)
_AUDIO = sorted(AUDIO_EXTS)
_IMAGE = sorted(IMAGE_EXTS)
_TEXT = sorted(TEXT_EXTS)
_BAG = sorted(BAG_EXTS)

# Extra types a produced/source type may satisfy (equality is always compatible).
TYPE_PROVIDES: dict[str, tuple[str, ...]] = {
    "frames_audio_topics": ("frames", ".wav", ".jpg", "labelable"),
    "frames": tuple(_IMAGE) + ("labelable",),
    "preview_mp4": (".mp4", "labelable"),
    "pcm_pa_wavs": (".wav", "labelable"),
    "asr_jsonl": ("labelable",),
    "mel_matrix": ("labelable",),
    "stft_matrix": ("labelable",),
    "third_octave_json": ("labelable",),
    "spl_jsonl": ("labelable",),
    "structured_json": ("labelable",),
    "bboxes_jsonl": ("labelable",),
    "labels_tree": ("labelable",),
    "embeddings": (),
    "labelable": (),
}
for _ext in _BAG:
    TYPE_PROVIDES[_ext] = ("labelable",)
for _ext in _VIDEO:
    TYPE_PROVIDES[_ext] = ("labelable",)
for _ext in _IMAGE:
    TYPE_PROVIDES[_ext] = ("frames", "labelable")
for _ext in _AUDIO:
    TYPE_PROVIDES[_ext] = ("labelable",)
for _ext in _TEXT:
    TYPE_PROVIDES.setdefault(_ext, ())


def _port(port_id: str, types: list[str], title: str = "", *, multiple: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {"id": port_id, "types": list(types), "multiple": bool(multiple)}
    if title:
        out["title"] = title
    return out


def _op(
    *,
    op_id: str,
    title: str,
    category: str,
    input_kinds: list[str],
    product: str,
    input_ports: list[dict[str, Any]],
    output_ports: list[dict[str, Any]],
    role: str = "preprocess",
    params_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "op_id": op_id,
        "title": title,
        "category": category,
        "role": role,
        "input_kinds": list(input_kinds),
        "product": product,
        "input_ports": input_ports,
        "output_ports": output_ports,
        "params_schema": dict(params_schema or {}),
    }


OPERATORS: dict[str, dict[str, Any]] = {
    "parse_bag": _op(
        op_id="parse_bag",
        title="ROSBAG 解析器",
        category="parse",
        input_kinds=_BAG,
        product="frames",
        input_ports=[_port("in", _BAG, ".bag")],
        output_ports=[
            _port("frames", ["frames"], "连续帧"),
            _port(".wav", [".wav"], ".wav"),
            _port(".json", [".json"], ".json"),
        ],
        params_schema={
            "emit_modalities": {
                "type": "array",
                "items": {"enum": list(PARSE_BAG_MODALITIES)},
            }
        },
    ),
    "extract_frames": _op(
        op_id="extract_frames",
        title="视频抽帧",
        category="parse",
        input_kinds=_VIDEO,
        product="frames",
        input_ports=[_port("in", _VIDEO, "视频文件", multiple=True)],
        output_ports=[_port("out", ["frames"], "连续帧")],
        params_schema={"sample_fps": {"type": "number"}},
    ),
    "encode_preview": _op(
        op_id="encode_preview",
        title="视频编码器",
        category="encode",
        input_kinds=_IMAGE,
        product="preview_mp4",
        input_ports=[_port("in", ["frames"], "连续帧图序列")],
        output_ports=[_port("out", ["preview_mp4"], "编码视频")],
    ),
    "transcribe": _op(
        op_id="transcribe",
        title="音频 ASR",
        category="audio",
        input_kinds=_AUDIO,
        product="asr_jsonl",
        input_ports=[_port("in", _AUDIO, "音频文件")],
        output_ports=[_port("out", ["asr_jsonl"], "转写文本")],
        params_schema={"model": {"type": "string"}},
    ),
    "mel_spectrogram": _op(
        op_id="mel_spectrogram",
        title="梅尔频谱",
        category="audio",
        input_kinds=_AUDIO,
        product="mel_matrix",
        input_ports=[_port("in", _AUDIO, "音频文件", multiple=True)],
        output_ports=[_port("out", ["mel_matrix"], "梅尔频谱")],
    ),
    "parse_head_dat": _op(
        op_id="parse_head_dat",
        title="HEAD .dat 解析",
        category="parse",
        input_kinds=[".dat"],
        product="pcm_pa_wavs",
        input_ports=[_port("in", [".dat"], ".dat")],
        output_ports=[_port("out", ["pcm_pa_wavs"], "PCM 声压")],
    ),
    "stft_spectrogram": _op(
        op_id="stft_spectrogram",
        title="STFT 频谱",
        category="audio",
        input_kinds=_AUDIO,
        product="stft_matrix",
        input_ports=[_port("in", _AUDIO, "音频文件", multiple=True)],
        output_ports=[_port("out", ["stft_matrix"], "STFT 频谱")],
    ),
    "third_octave": _op(
        op_id="third_octave",
        title="1/3 倍频程",
        category="audio",
        input_kinds=_AUDIO,
        product="third_octave_json",
        input_ports=[_port("in", _AUDIO, "音频文件", multiple=True)],
        output_ports=[_port("out", ["third_octave_json"], "带级")],
    ),
    "spl_timeline": _op(
        op_id="spl_timeline",
        title="SPL 时间线",
        category="audio",
        input_kinds=_AUDIO,
        product="spl_jsonl",
        input_ports=[_port("in", _AUDIO, "音频文件", multiple=True)],
        output_ports=[_port("out", ["spl_jsonl"], "SPL")],
    ),
    "text_to_json": _op(
        op_id="text_to_json",
        title="文本结构化",
        category="parse",
        input_kinds=_TEXT,
        product="structured_json",
        input_ports=[_port("in", _TEXT, "文本文件")],
        output_ports=[_port("out", ["structured_json"], "结构化 JSON")],
        params_schema={"schema_id": {"type": "string"}},
    ),
    "detect_bbox": _op(
        op_id="detect_bbox",
        title="BBox 检测器",
        category="detect_ai",
        input_kinds=_IMAGE + _VIDEO + _BAG,
        product="bboxes_jsonl",
        input_ports=[_port("in", _IMAGE + _VIDEO + _BAG + ["frames"], "画面", multiple=True)],
        output_ports=[_port("out", ["bboxes_jsonl"], "BBox")],
        params_schema={
            "detector": {"enum": ["opencv", "yolo"]},
            "yolo_classes": {"type": "string"},
        },
    ),
}

STAGE_OPERATORS: dict[str, dict[str, Any]] = {
    "label": _op(
        op_id="label",
        title="打标器",
        category="detect_ai",
        role="stage",
        input_kinds=_IMAGE + _VIDEO + _AUDIO + _BAG,
        product="labels_tree",
        input_ports=[_port("in", ["labelable"], "需打标数据", multiple=True)],
        output_ports=[_port("out", ["labels_tree"], "AI 标签树")],
        params_schema={"model": {"enum": list(LABEL_MODELS)}},
    ),
    "embed": _op(
        op_id="embed",
        title="向量化器",
        category="detect_ai",
        role="stage",
        input_kinds=_IMAGE + _VIDEO + _AUDIO + _BAG,
        product="embeddings",
        input_ports=[_port("in", ["labelable"], "需向量化数据", multiple=True)],
        output_ports=[_port("out", ["embeddings"], "融合向量")],
    ),
}

CATALOG: dict[str, dict[str, Any]] = {**OPERATORS, **STAGE_OPERATORS}


def parse_bag_emit_modalities(params: dict[str, Any] | None) -> list[str] | None:
    """Selected parse_bag products. None = unset (default all three); [] = none."""
    if not isinstance(params, dict) or "emit_modalities" not in params:
        return None
    raw = params.get("emit_modalities")
    out: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            m = normalize_parse_bag_modality(str(item))
            if m and m not in out:
                out.append(m)
    return out


def type_compatible(provided: str, needed: str) -> bool:
    if not provided or not needed:
        return False
    p = normalize_source_kind(provided) or provided
    n = normalize_source_kind(needed) or needed
    if p == n:
        return True
    return n in TYPE_PROVIDES.get(p, ())


def param_keys_for_op(op_id: str) -> set[str]:
    spec = CATALOG.get(op_id) or OPERATORS.get(op_id) or {}
    schema = spec.get("params_schema") or {}
    return set(schema.keys()) if isinstance(schema, dict) else set()


def get_operator(op_id: str) -> dict[str, Any] | None:
    spec = CATALOG.get(op_id)
    return dict(spec) if spec else None


def list_operators() -> list[dict[str, Any]]:
    return [dict(v) for v in CATALOG.values()]


def list_type_provides() -> dict[str, list[str]]:
    return {k: list(v) for k, v in TYPE_PROVIDES.items()}
