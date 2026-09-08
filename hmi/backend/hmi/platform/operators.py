"""Code-registered preprocess / detect / AI-stage operators (DataType recipes only reference ids)."""

from __future__ import annotations

import json
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

from hmi.platform.label_model_params import (
    CALL_FIELDS_BY_MODEL,
    LABEL_MODEL_TITLES,
    LABEL_MODELS,
    OMNI_PROMPT_FIELDS,
    label_params_schema,
)

BBOX_DETECTORS = frozenset({"opencv", "yolo"})
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

_CHANNEL_EXPAND_PARAMS: dict[str, Any] = {
    "channel_count": {"type": "integer", "minimum": 1, "maximum": 16},
    "port_titles": {"type": "object"},
}

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
    "json_value": ("labelable",),
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


def _port(
    port_id: str,
    types: list[str],
    title: str = "",
    *,
    multiple: bool = False,
    min_count: int = 1,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": port_id,
        "types": list(types),
        "multiple": bool(multiple),
        "min_count": max(0, int(min_count)),
    }
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
    description: str = "",
    expand_outputs_from: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
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
    if description:
        out["description"] = description
    if expand_outputs_from:
        out["expand_outputs_from"] = expand_outputs_from
    return out


_JSON_IN_TYPES = [
    "structured_json",
    "json_value",
    ".json",
    "asr_jsonl",
    "third_octave_json",
    "spl_jsonl",
    "labels_tree",
]
LEGACY_LABEL_TITLES = frozenset({"打标器", "label", "labeler"})


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
        params_schema=dict(_CHANNEL_EXPAND_PARAMS),
        expand_outputs_from="channel_count",
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
        params_schema=dict(_CHANNEL_EXPAND_PARAMS),
        expand_outputs_from="channel_count",
        description="解码 PCM .wav 或 HEAD .dat；mp3 等压缩格式请先转 wav。wav 的 SPL 未按声压标定。",
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
        params_schema=dict(_CHANNEL_EXPAND_PARAMS),
        expand_outputs_from="channel_count",
        description="解码 PCM .wav 或 HEAD .dat；压缩音频请先转 wav。",
    ),
    "third_octave": _op(
        op_id="third_octave",
        title="1/3 倍频程",
        category="audio",
        input_kinds=_AUDIO,
        product="third_octave_json",
        input_ports=[_port("in", _AUDIO, "音频文件", multiple=True)],
        output_ports=[_port("out", ["third_octave_json"], "带级")],
        params_schema=dict(_CHANNEL_EXPAND_PARAMS),
        expand_outputs_from="channel_count",
        description="解码 PCM .wav 或 HEAD .dat；压缩音频请先转 wav。wav 的 SPL 未按声压标定。",
    ),
    "spl_timeline": _op(
        op_id="spl_timeline",
        title="SPL 时间线",
        category="audio",
        input_kinds=_AUDIO,
        product="spl_jsonl",
        input_ports=[_port("in", _AUDIO, "音频文件", multiple=True)],
        output_ports=[_port("out", ["spl_jsonl"], "SPL")],
        params_schema=dict(_CHANNEL_EXPAND_PARAMS),
        expand_outputs_from="channel_count",
        description="解码 PCM .wav 或 HEAD .dat；压缩音频请先转 wav。wav 的 SPL 相对满幅，不是标定声压。",
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
    "json_extract": _op(
        op_id="json_extract",
        title="JSON 值提取",
        category="parse",
        input_kinds=_TEXT + ["structured_json", "json_value"],
        product="json_value",
        input_ports=[_port("in", list(_JSON_IN_TYPES), "JSON")],
        output_ports=[_port("out", ["json_value"], "提取值")],
        description="按键路径从 JSON 取出值，可供条件分支或标签填写使用。",
        params_schema={"path_keys": {"type": "array", "items": {"type": "string"}}},
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
    "label_tree_input": _op(
        op_id="label_tree_input",
        title="标签树输入",
        category="detect_ai",
        input_kinds=["json_value", "structured_json", ".json", "labelable"],
        product="labels_tree",
        input_ports=[
            _port(
                "in",
                ["json_value", "structured_json", ".json", "labelable"],
                "取值来源",
                multiple=True,
                min_count=0,
            )
        ],
        output_ports=[_port("out", ["labels_tree"], "标签树")],
        description="从绑定标签树选择条目并填值（常量或上游），规则可判的标签不必走 AI打标器。",
        params_schema={
            "assignments": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "label_id": {"type": "string"},
                        "mode": {"enum": ["const", "upstream"]},
                        "value": {},
                        "bind_step_key": {"type": "string"},
                        "bind_port_id": {"type": "string"},
                    },
                },
            }
        },
    ),
}

STAGE_OPERATORS: dict[str, dict[str, Any]] = {
    "label": _op(
        op_id="label",
        title="AI打标器",
        category="detect_ai",
        role="stage",
        description="用模型生成标签树；规则可判的字段请用标签树输入。",
        input_kinds=_IMAGE + _VIDEO + _AUDIO + _BAG,
        product="labels_tree",
        input_ports=[_port("in", ["labelable"], "需打标数据", multiple=True)],
        output_ports=[_port("out", ["labels_tree"], "AI 标签树")],
        params_schema=label_params_schema(),
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
CATALOG["label"]["call_fields_by_model"] = CALL_FIELDS_BY_MODEL
CATALOG["label"]["omni_prompt_fields"] = OMNI_PROMPT_FIELDS
CATALOG["label"]["models"] = [
    {"id": mid, "title": LABEL_MODEL_TITLES.get(mid, mid)} for mid in LABEL_MODELS
]


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


def normalize_path_keys(raw: Any) -> list[str]:
    """Inspector segments or a compiled dotted path → non-empty key list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        return [p.strip() for p in raw.split(".") if p.strip()]
    if isinstance(raw, list):
        out: list[str] = []
        for item in raw:
            s = str(item or "").strip()
            if s:
                out.append(s)
        return out
    return []


def extract_json_path(data: Any, keys: list[str] | None) -> Any:
    """Walk dict keys / list indices. Missing path → None. Empty keys → data as-is."""
    cur: Any = data
    if isinstance(cur, (bytes, bytearray)):
        cur = cur.decode("utf-8", errors="replace")
    if isinstance(cur, str):
        text = cur.strip()
        if text[:1] in "{[":
            try:
                cur = json.loads(text)
            except json.JSONDecodeError:
                return None
    path = [str(k).strip() for k in (keys or []) if str(k).strip()]
    for key in path:
        if isinstance(cur, dict):
            if key not in cur:
                return None
            cur = cur[key]
        elif isinstance(cur, list):
            try:
                idx = int(key)
            except (TypeError, ValueError):
                return None
            if idx < 0 or idx >= len(cur):
                return None
            cur = cur[idx]
        else:
            return None
    return cur


def apply_label_tree_assignments(
    assignments: Any,
    *,
    resolve_upstream: Any | None = None,
) -> dict[str, Any]:
    """Build OMS-style labels_json ``{values: {label_id: {value}}}`` from inspector rows."""
    values: dict[str, Any] = {}
    rows = assignments if isinstance(assignments, list) else []
    getter = resolve_upstream if callable(resolve_upstream) else (lambda _bind: None)
    for item in rows:
        if not isinstance(item, dict):
            continue
        lid = str(item.get("label_id") or "").strip()
        if not lid:
            continue
        mode = str(item.get("mode") or "const").strip() or "const"
        if mode == "upstream":
            bind = {
                "kind": "upstream",
                "step_key": str(item.get("bind_step_key") or "").strip(),
                "port_id": str(item.get("bind_port_id") or "out").strip() or "out",
            }
            val = getter(bind)
        else:
            val = item.get("value")
        values[lid] = {"value": val}
    return {"values": values}


def is_generic_node_title(stored: str, op_id: str, key: str | None = None) -> bool:
    """True when ``stored`` is a hydrate alias / op id, not a user-authored name."""
    t = str(stored or "").strip()
    if not t:
        return True
    if t == op_id:
        return True
    if key and t == key:
        return True
    if t.startswith("prep-"):
        return True
    if op_id and t == f"stage-{op_id}":
        return True
    if op_id == "label" and t in LEGACY_LABEL_TITLES:
        return True
    return False


def display_op_title(op_id: str, stored_title: str | None = None, key: str | None = None) -> str:
    """User-visible title: catalog wins for hydrate aliases and legacy labeler names."""
    spec = CATALOG.get(op_id) or {}
    catalog_title = str(spec.get("title") or "").strip()
    stored = str(stored_title or "").strip()
    if catalog_title and is_generic_node_title(stored, op_id, key):
        return catalog_title
    if stored:
        return stored
    return catalog_title or op_id


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
