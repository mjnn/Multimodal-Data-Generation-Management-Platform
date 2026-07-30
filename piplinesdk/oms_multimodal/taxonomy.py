"""OMS 打标 taxonomy 加载与 prompt 构建。

从 oms_label_taxonomy.yaml 读取标签定义，生成 Qwen-Omni 结构化 prompt（中文），
并解析 / 规范化模型返回的 JSON 打标结果（枚举值为中文展示）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml


def _enrich_taxonomy(taxonomy: dict[str, Any]) -> dict[str, Any]:
    try:
        from shared.taxonomy_i18n import enrich_taxonomy_document

        return enrich_taxonomy_document(taxonomy)
    except ImportError:
        return taxonomy


def load_taxonomy(path: Path) -> dict[str, Any]:
    """加载 YAML taxonomy 文件并补充中文枚举 labels。"""
    with path.open("r", encoding="utf-8") as f:
        doc = yaml.safe_load(f) or {}
    return _enrich_taxonomy(doc)


def _format_allowed_values(schema: dict[str, Any]) -> str:
    labels = schema.get("labels") or {}
    enum_values: list[Any] | None = None
    if schema.get("type") == "enum":
        enum_values = schema.get("values")
    elif schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict) and items.get("type") == "enum":
            enum_values = items.get("values")
            labels = items.get("labels") or labels
    if not isinstance(enum_values, list):
        return ""
    parts: list[str] = []
    for v in enum_values:
        key = str(v)
        zh = labels.get(key) or key
        parts.append(str(zh))
    return "、".join(parts)


def taxonomy_prompt_block(
    taxonomy: dict[str, Any],
    prompt_params: dict[str, Any] | None = None,
) -> str:
    """将 taxonomy 转为 Omni 可理解的中文 prompt。"""
    from .label_prompt import build_taxonomy_prompt_block

    return build_taxonomy_prompt_block(taxonomy, prompt_params)


def normalize_model_labels(taxonomy: dict[str, Any], labels: dict[str, Any]) -> dict[str, Any]:
    try:
        from shared.taxonomy_i18n import normalize_parsed_labels

        return normalize_parsed_labels(taxonomy, labels)
    except ImportError:
        return labels


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
