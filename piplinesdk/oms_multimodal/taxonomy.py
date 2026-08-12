"""OMS 打标 taxonomy 加载与 prompt 构建。

从 oms_label_taxonomy.yaml 读取标签定义，生成 Qwen-Omni 结构化 prompt（中文），
并解析 / 规范化模型返回的 JSON 打标结果（枚举值为中文展示）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .taxonomy_tree import (
    LabelingTaxonomyOptions,
    crop_taxonomy_for_labeling,
    format_enum_tree_for_prompt,
    is_enum_tree_schema,
    normalize_tree_value,
    resolve_labeling_taxonomy_options,
    tree_output_mode_rule,
)


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


def prepare_taxonomy_for_labeling(
    taxonomy: dict[str, Any],
    *,
    options: LabelingTaxonomyOptions | None = None,
) -> tuple[dict[str, Any], LabelingTaxonomyOptions]:
    """Enrich is assumed done; crop by LABEL_TAXONOMY_DEPTH* for Omni prompt + normalize."""
    return crop_taxonomy_for_labeling(taxonomy, options=options)


def _format_allowed_values(schema: dict[str, Any]) -> str:
    if is_enum_tree_schema(schema):
        tree_text = format_enum_tree_for_prompt(schema)
        return "嵌套取值树：\n" + tree_text if tree_text else ""

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
        if isinstance(v, dict):
            key = str(v.get("id") or v)
        else:
            key = str(v)
        zh = labels.get(key) or key
        parts.append(str(zh))
    return "、".join(parts)


def taxonomy_prompt_block(
    taxonomy: dict[str, Any],
    prompt_params: dict[str, Any] | None = None,
    *,
    options: LabelingTaxonomyOptions | None = None,
) -> str:
    """将 taxonomy 转为 Omni 可理解的中文 prompt（按深度参数裁剪）。"""
    from .label_prompt import build_taxonomy_prompt_block

    cropped, opts = prepare_taxonomy_for_labeling(taxonomy, options=options)
    return build_taxonomy_prompt_block(cropped, prompt_params, tree_output_mode=opts.output_mode)


def normalize_model_labels(
    taxonomy: dict[str, Any],
    labels: dict[str, Any],
    *,
    options: LabelingTaxonomyOptions | None = None,
) -> dict[str, Any]:
    cropped, opts = prepare_taxonomy_for_labeling(taxonomy, options=options)
    try:
        from shared.taxonomy_i18n import normalize_parsed_labels

        try:
            return normalize_parsed_labels(
                cropped,
                labels,
                tree_output_mode=opts.output_mode,
            )
        except TypeError:
            return normalize_parsed_labels(cropped, labels)
    except ImportError:
        return _normalize_labels_local(cropped, labels, output_mode=opts.output_mode)


def _normalize_labels_local(
    taxonomy: dict[str, Any],
    labels: dict[str, Any],
    *,
    output_mode: str,
) -> dict[str, Any]:
    by_id = {str(it["id"]): it for it in taxonomy.get("labels") or [] if it.get("id")}
    out: dict[str, Any] = {}
    for label_id, entry in labels.items():
        item = by_id.get(str(label_id))
        schema = item.get("value_schema") if item else None
        if isinstance(entry, dict) and "value" in entry:
            new_entry = dict(entry)
            val = entry.get("value")
            if isinstance(schema, dict) and is_enum_tree_schema(schema):
                normalized = normalize_tree_value(schema, val, output_mode=output_mode)
                if normalized is None:
                    continue
                new_entry["value"] = normalized
            else:
                new_entry["value"] = val
            out[label_id] = new_entry
        else:
            if isinstance(schema, dict) and is_enum_tree_schema(schema):
                normalized = normalize_tree_value(schema, entry, output_mode=output_mode)
                if normalized is None:
                    continue
                out[label_id] = normalized
            else:
                out[label_id] = entry
    return out


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


__all__ = [
    "LabelingTaxonomyOptions",
    "crop_taxonomy_for_labeling",
    "load_taxonomy",
    "normalize_model_labels",
    "parse_label_json",
    "prepare_taxonomy_for_labeling",
    "resolve_labeling_taxonomy_options",
    "taxonomy_prompt_block",
    "tree_output_mode_rule",
]
