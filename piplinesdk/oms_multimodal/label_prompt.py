"""Structured Omni labeling prompt scaffold and tunable parameters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Keys users may override via HMI / ClientConfig.omni_label_prompt
OMNI_LABEL_PROMPT_KEYS = (
    "system_role",
    "output_instruction",
    "json_format_hint",
    "labeling_rules",
    "labels_section_title",
    "user_task_intro",
    "user_modality_hint",
    "user_taxonomy_task",
    "user_asr_hint",
)

DEFAULT_OMNI_LABEL_PROMPT: dict[str, str] = {
    "system_role": "你是车内 OMS/DMS 多模态标注助手。",
    "output_instruction": "请结合图像、音频与文本事件，输出**仅含合法 JSON** 的对象，格式如下：",
    "json_format_hint": (
        '{\n'
        '  "scene_summary": "用中文简要描述整段场景（1~3 句）",\n'
        '  "labels": {\n'
        '    "<label_id>": {"value": <按类型取值>, "confidence": 0.0-1.0, "evidence": "中文简要依据"}\n'
        "  }\n"
        "}"
    ),
    "labeling_rules": (
        "label_id 必须与下方定义完全一致（英文 id，勿改）。\n"
        "仅输出有依据的标签；不确定则省略该 label_id。\n"
        "confidence 为 0~1 浮点数。\n"
        "**枚举类 value 必须使用下方「允许取值」中的中文，不得使用英文代号。**\n"
        "布尔类 value 使用「是」或「否」。\n"
        "数组 / 复合类型按 JSON 数组或对象填写。"
    ),
    "labels_section_title": "标签定义（name 为中文名）：",
    "user_task_intro": "请分析这段完整车内 rosbag clip（时长 {duration_sec:.1f} 秒）。",
    "user_modality_hint": (
        "video 为按时间排序的多相机帧序列，audio 覆盖整段。"
    ),
    "user_taxonomy_task": "请为整段场景填写 taxonomy 标签。",
    "user_asr_hint": "若提供了 ASR 文本，请以其为语音内容的依据，并与音视频交叉验证。",
}

OMNI_LABEL_PROMPT_FIELD_META: list[dict[str, Any]] = [
    {
        "key": "system_role",
        "label": "角色设定",
        "description": "模型角色与领域定位（system 段前的 taxonomy 脚手架首行）。",
        "multiline": False,
    },
    {
        "key": "output_instruction",
        "label": "输出要求",
        "description": "要求仅输出 JSON 的说明，紧接在角色设定之后。",
        "multiline": False,
    },
    {
        "key": "json_format_hint",
        "label": "JSON 结构示例",
        "description": "scene_summary 与 labels 字段的结构模板（勿删关键字段名）。",
        "multiline": True,
    },
    {
        "key": "labeling_rules",
        "label": "打标规则",
        "description": "每条规则一行；会列在 taxonomy 标签定义之前。",
        "multiline": True,
    },
    {
        "key": "labels_section_title",
        "label": "标签列表标题",
        "description": "taxonomy 各 label 定义块前的标题行。",
        "multiline": False,
    },
    {
        "key": "user_task_intro",
        "label": "用户任务开场",
        "description": "多模态 user 消息中的任务描述；可用占位符 {duration_sec:.1f}。",
        "multiline": False,
    },
    {
        "key": "user_modality_hint",
        "label": "模态说明",
        "description": "说明 video / audio 与时间覆盖范围。",
        "multiline": False,
    },
    {
        "key": "user_taxonomy_task",
        "label": "打标任务句",
        "description": "明确要求填写 taxonomy 标签的一句话。",
        "multiline": False,
    },
    {
        "key": "user_asr_hint",
        "label": "ASR 使用说明",
        "description": "当存在 ASR 或事件文本时，如何与音视频交叉验证。",
        "multiline": False,
    },
]


def default_omni_label_prompt() -> dict[str, str]:
    return deepcopy(DEFAULT_OMNI_LABEL_PROMPT)


def merge_omni_label_prompt(overrides: dict[str, Any] | None) -> dict[str, str]:
    """Merge user overrides onto SDK defaults (unknown keys ignored)."""
    merged = default_omni_label_prompt()
    if not overrides or not isinstance(overrides, dict):
        return merged
    for key in OMNI_LABEL_PROMPT_KEYS:
        if key not in overrides:
            continue
        val = overrides[key]
        if val is None:
            continue
        text = str(val).strip()
        if text:
            merged[key] = text
    return merged


def omni_label_prompt_overrides_only(merged: dict[str, str]) -> dict[str, str]:
    """Strip values identical to defaults for compact persistence."""
    defaults = DEFAULT_OMNI_LABEL_PROMPT
    out: dict[str, str] = {}
    for key in OMNI_LABEL_PROMPT_KEYS:
        val = merged.get(key, defaults.get(key, ""))
        if str(val).strip() and str(val).strip() != str(defaults.get(key, "")).strip():
            out[key] = str(val).strip()
    return out


def build_taxonomy_prompt_block(taxonomy: dict[str, Any], params: dict[str, str] | None) -> str:
    """Build taxonomy + rules prompt section (from label_prompt params + taxonomy)."""
    from .taxonomy import _format_allowed_values  # noqa: PLC0415 — avoid cycle at import

    p = merge_omni_label_prompt(params)
    lines = [
        p["system_role"],
        p["output_instruction"],
        p["json_format_hint"],
        "",
        "规则：",
    ]
    for rule in p["labeling_rules"].splitlines():
        rule = rule.strip()
        if rule:
            lines.append(f"- {rule}")
    lines.extend(["", p["labels_section_title"]])
    for item in taxonomy.get("labels", []):
        schema = item.get("value_schema") or {}
        stype = schema.get("type", item.get("dtype"))
        line = (
            f"- {item['id']} | {item.get('name', '')} | 类型={stype}"
            f" | 说明={item.get('definition', '')}"
        )
        allowed = _format_allowed_values(schema)
        if allowed:
            line += f" | 允许取值={allowed}"
        if schema.get("range_hint"):
            line += f" | 范围={schema['range_hint']}"
        lines.append(line)
    return "\n".join(lines)


def build_omni_user_text(
    *,
    duration_sec: float,
    speech_context: str,
    event_text: str,
    params: dict[str, str] | None,
) -> str:
    p = merge_omni_label_prompt(params)
    try:
        intro = p["user_task_intro"].format(duration_sec=duration_sec)
    except (KeyError, ValueError):
        intro = p["user_task_intro"].replace("{duration_sec:.1f}", f"{duration_sec:.1f}")
    parts = [intro, p["user_modality_hint"], p["user_taxonomy_task"], p["user_asr_hint"]]
    user_text = " ".join(s.strip() for s in parts if s.strip())
    if speech_context:
        user_text += f"\n\nMultimodal text context:\n{speech_context}"
    elif event_text:
        user_text += f"\n\nEvent texts:\n{event_text}"
    return user_text
