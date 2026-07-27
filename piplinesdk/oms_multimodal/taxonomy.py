"""OMS 打标 taxonomy 加载与 prompt 构建。

从 oms_label_taxonomy.yaml 读取 68 个标签定义，生成 Qwen-Omni 的结构化 prompt，
并解析模型返回的 JSON 打标结果。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def load_taxonomy(path: Path) -> dict[str, Any]:
    """加载 YAML taxonomy 文件。"""
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def taxonomy_prompt_block(taxonomy: dict[str, Any]) -> str:
    """将 taxonomy 转为 Omni 可理解的英文 prompt 块。

    包含输出 JSON schema、规则和每个标签的 id/类型/枚举值/定义。
    """
    lines = [
        "You are an in-cabin OMS/DMS labeling assistant.",
        "Analyze the provided image, audio, and event text together.",
        "Return ONLY valid JSON with this shape:",
        "{",
        '  "scene_summary": "short natural language summary",',
        '  "labels": {',
        '    "<label_id>": {"value": <typed_value>, "confidence": 0.0-1.0, "evidence": "brief reason"}',
        "  }",
        "}",
        "",
        "Rules:",
        "- Use label ids exactly as defined below.",
        "- Only include labels you can infer from the multimodal evidence.",
        "- Respect enum values and dtypes; use null if unknown.",
        "- confidence must be between 0 and 1.",
        "- For array/composite schemas, use JSON arrays/objects.",
        "",
        "Label taxonomy:",
    ]
    for item in taxonomy.get("labels", []):
        schema = item.get("value_schema", {})
        enum_values = None
        if schema.get("type") == "enum":
            enum_values = schema.get("values")
        elif schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            enum_values = schema["items"].get("values")
        line = (
            f"- {item['id']} ({item['name']}): "
            f"type={schema.get('type', item.get('dtype'))}; "
            f"definition={item.get('definition', '')}"
        )
        if enum_values:
            line += f"; allowed={enum_values}"
        if schema.get("range_hint"):
            line += f"; range={schema['range_hint']}"
        lines.append(line)
    return "\n".join(lines)


def parse_label_json(raw_text: str) -> dict[str, Any]:
    """从 Omni 回复中提取 JSON 对象（兼容 markdown 代码块包裹）。"""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("Model response does not contain JSON object")
    return json.loads(text[start : end + 1])
