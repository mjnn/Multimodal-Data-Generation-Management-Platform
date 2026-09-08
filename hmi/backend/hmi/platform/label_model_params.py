"""Per-model call parameters for the AI labeler DAG node.

Different label models (SDK Omni vs NVH AST / heuristic / VL) do not share
the same request shape. These keys live on the label node ``params`` and are
copied onto ``recipe.stages.label`` at compile time.
"""

from __future__ import annotations

from typing import Any

LABEL_MODELS = ("default", "nvh_sem_ast", "nvh_sem_heuristic", "nvh_sem_vl")

LABEL_MODEL_TITLES: dict[str, str] = {
    "default": "default（SDK Omni / Qwen）",
    "nvh_sem_ast": "nvh_sem_ast（AudioSet AST）",
    "nvh_sem_heuristic": "nvh_sem_heuristic（客观规则）",
    "nvh_sem_vl": "nvh_sem_vl（看 Mel 的 VL）",
}

OMNI_PROMPT_FIELDS: list[dict[str, Any]] = [
    {"key": "system_role", "label": "角色设定", "multiline": False, "description": "模型角色与领域定位。"},
    {"key": "output_instruction", "label": "输出要求", "multiline": False, "description": "要求仅输出 JSON 的说明。"},
    {"key": "json_format_hint", "label": "JSON 结构示例", "multiline": True, "description": "scene_summary / labels 结构模板。"},
    {"key": "labeling_rules", "label": "打标规则 / 参考约束", "multiline": True, "description": "每条规则一行；会进 system 提示词。"},
    {"key": "labels_section_title", "label": "标签列表标题", "multiline": False, "description": "taxonomy 定义块前的标题。"},
    {"key": "user_task_intro", "label": "用户任务开场", "multiline": False, "description": "可用占位符 {duration_sec:.1f}。"},
    {"key": "user_modality_hint", "label": "模态说明", "multiline": False, "description": "说明 video / audio 覆盖范围。"},
    {"key": "user_taxonomy_task", "label": "打标任务句", "multiline": False, "description": "要求填写 taxonomy 的一句话。"},
    {"key": "user_asr_hint", "label": "ASR 使用说明", "multiline": False, "description": "如何与音视频交叉验证 ASR。"},
    {"key": "user_bbox_hint", "label": "BBox 使用说明", "multiline": False, "description": "BBox 类别如何与图像交叉验证。"},
]

CALL_FIELDS_BY_MODEL: dict[str, list[dict[str, Any]]] = {
    "default": [
        {
            "key": "omni_model_id",
            "label": "调用模型 ID",
            "type": "string",
            "placeholder": "qwen3.5-omni-plus",
            "description": "DashScope / AIGW 上的实际模型名，与上面的「打标模型」种类不同。",
        },
        {
            "key": "temperature",
            "label": "温度",
            "type": "number",
            "min": 0,
            "max": 2,
            "step": 0.1,
            "description": "采样温度；部分后端可能忽略。",
        },
        {
            "key": "max_tokens",
            "label": "max_tokens",
            "type": "integer",
            "min": 256,
            "max": 16384,
            "description": "生成上限。",
        },
        {
            "key": "bbox_in_label_prompt",
            "label": "把 BBox 写入提示词",
            "type": "boolean",
            "description": "把检出类别当作先验塞进 Omni 提示词。",
        },
        {"key": "omni_label_prompt", "label": "Omni 提示词", "type": "omni_prompt"},
    ],
    "nvh_sem_ast": [
        {
            "key": "ast_top_k",
            "label": "AudioSet top-k",
            "type": "integer",
            "min": 1,
            "max": 20,
            "description": "映射噪声类别时取前 k 个 AudioSet 类。",
        },
        {
            "key": "reference_constraints",
            "label": "参考约束",
            "type": "textarea",
            "description": "写入假设说明；不改变客观 SPL 叶子。",
        },
    ],
    "nvh_sem_heuristic": [
        {
            "key": "reference_constraints",
            "label": "参考约束 / 规则备注",
            "type": "textarea",
            "description": "规则路径没有 LLM 提示词；备注会记进 annotator_notes。",
        },
    ],
    "nvh_sem_vl": [
        {
            "key": "vl_model",
            "label": "VL 模型 ID",
            "type": "string",
            "placeholder": "qwen-vl-plus",
            "description": "看 Mel 图的视觉模型名。",
        },
        {
            "key": "vl_prompt",
            "label": "提示词",
            "type": "textarea",
            "description": "发给 VL 的任务说明与输出约束。留空用内置 NVH 语义提示词。",
        },
        {
            "key": "reference_constraints",
            "label": "参考约束",
            "type": "textarea",
            "description": "附加约束，会拼进提示词末尾。",
        },
    ],
}

LABEL_STAGE_EXTRA_KEYS = frozenset(
    {
        "omni_model_id",
        "omni_label_prompt",
        "bbox_in_label_prompt",
        "temperature",
        "max_tokens",
        "ast_top_k",
        "reference_constraints",
        "vl_prompt",
        "vl_model",
    }
)


def extra_keys_for_model(model: str | None) -> frozenset[str]:
    """Call-param keys that belong on stages.label for the selected model."""
    mid = str(model or "default").strip() or "default"
    fields = CALL_FIELDS_BY_MODEL.get(mid) or CALL_FIELDS_BY_MODEL["default"]
    return frozenset(str(f["key"]) for f in fields)


def label_params_schema() -> dict[str, Any]:
    return {
        "model": {"enum": list(LABEL_MODELS)},
        "omni_model_id": {"type": "string"},
        "omni_label_prompt": {"type": "object"},
        "bbox_in_label_prompt": {"type": "boolean"},
        "temperature": {"type": "number"},
        "max_tokens": {"type": "integer"},
        "ast_top_k": {"type": "integer"},
        "reference_constraints": {"type": "string"},
        "vl_prompt": {"type": "string"},
        "vl_model": {"type": "string"},
    }


def compact_omni_prompt(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    allowed = {str(f["key"]) for f in OMNI_PROMPT_FIELDS}
    out: dict[str, str] = {}
    for key, val in raw.items():
        kid = str(key).strip()
        if kid not in allowed or val is None:
            continue
        text = str(val).strip()
        if text:
            out[kid] = text
    return out


def label_stage_extras(params: dict[str, Any] | None) -> dict[str, Any]:
    """Subset of node params that belong on recipe.stages.label (not just model).

    Only copies keys for the selected model so Omni extras do not leak onto NVH
    stages and vice versa. Other models' keys stay on the node ``params`` object.
    """
    src = params if isinstance(params, dict) else {}
    allowed = extra_keys_for_model(src.get("model"))
    out: dict[str, Any] = {}
    for key in LABEL_STAGE_EXTRA_KEYS:
        if key not in allowed or key not in src:
            continue
        val = src[key]
        if key == "omni_label_prompt":
            compact = compact_omni_prompt(val)
            if compact:
                out[key] = compact
            continue
        if key == "bbox_in_label_prompt":
            if isinstance(val, bool):
                out[key] = val
            continue
        if key in {"temperature"}:
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                continue
            continue
        if key in {"max_tokens", "ast_top_k"}:
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                continue
            continue
        text = str(val).strip() if val is not None else ""
        if text:
            out[key] = text
    return out
