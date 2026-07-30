"""Chinese display labels for OMS taxonomy enum values (SDK + HMI)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from shared.repo_paths import SHARED_ROOT

_ENUM_ZH_PATH = SHARED_ROOT / "config" / "oms_enum_zh.yaml"


@lru_cache(maxsize=1)
def load_enum_zh_map() -> dict[str, str]:
    if not _ENUM_ZH_PATH.is_file():
        return {}
    data = yaml.safe_load(_ENUM_ZH_PATH.read_text(encoding="utf-8")) or {}
    values = data.get("values") or {}
    if not isinstance(values, dict):
        return {}
    return {str(k): str(v) for k, v in values.items()}


def zh_for_enum_value(raw: str, *, enum_map: dict[str, str] | None = None) -> str:
    key = str(raw).strip()
    mapping = enum_map if enum_map is not None else load_enum_zh_map()
    if key in mapping:
        return mapping[key]
    low = key.lower()
    if low in ("true", "1", "yes"):
        return "是"
    if low in ("false", "0", "no"):
        return "否"
    return key.replace("_", " ")


def _schema_enum_values(schema: dict[str, Any]) -> list[str] | None:
    if schema.get("type") == "enum":
        vals = schema.get("values")
        return [str(v) for v in vals] if isinstance(vals, list) else None
    if schema.get("type") == "array":
        items = schema.get("items")
        if isinstance(items, dict) and items.get("type") == "enum":
            vals = items.get("values")
            return [str(v) for v in vals] if isinstance(vals, list) else None
    return None


def enrich_value_schema(schema: dict[str, Any] | None, *, enum_map: dict[str, str] | None = None) -> dict[str, Any] | None:
    if not schema or not isinstance(schema, dict):
        return schema
    out = dict(schema)
    mapping = dict(enum_map or load_enum_zh_map())
    enum_values = _schema_enum_values(out)
    if enum_values is not None:
        labels = dict(out.get("labels") or {})
        for v in enum_values:
            if v not in labels:
                labels[v] = zh_for_enum_value(v, enum_map=mapping)
        out["labels"] = labels
    if out.get("type") == "bool":
        out.setdefault("true_label", "是")
        out.setdefault("false_label", "否")
    return out


def enrich_taxonomy_document(taxonomy: dict[str, Any]) -> dict[str, Any]:
    """Attach Chinese labels to enum value_schema entries (in-place copy)."""
    enum_map = load_enum_zh_map()
    labels_out: list[dict[str, Any]] = []
    for item in taxonomy.get("labels") or []:
        row = dict(item)
        schema = row.get("value_schema")
        if isinstance(schema, dict):
            row["value_schema"] = enrich_value_schema(schema, enum_map=enum_map)
        labels_out.append(row)
    return {**taxonomy, "labels": labels_out}


def _allowed_zh_values(schema: dict[str, Any]) -> list[str]:
    labels = schema.get("labels") or {}
    enum_values = _schema_enum_values(schema) or []
    allowed: list[str] = []
    for v in enum_values:
        zh = labels.get(v) or zh_for_enum_value(v)
        allowed.append(str(zh))
    return allowed


def normalize_label_value(raw: Any, schema: dict[str, Any] | None) -> Any:
    if raw is None or schema is None:
        return raw
    stype = schema.get("type")
    labels = schema.get("labels") or {}
    enum_map = load_enum_zh_map()

    if stype == "bool":
        text = str(raw).strip().lower()
        if text in ("true", "1", "yes", "是"):
            return schema.get("true_label") or "是"
        if text in ("false", "0", "no", "否"):
            return schema.get("false_label") or "否"
        return raw

    if stype == "enum":
        key = str(raw).strip()
        if key in labels:
            return labels[key]
        # model returned English canonical
        if key in enum_map:
            return enum_map[key]
        # model returned Chinese already
        for canon, zh in labels.items():
            if key == zh:
                return zh
        return zh_for_enum_value(key, enum_map=enum_map)

    if stype == "array":
        items = schema.get("items")
        if isinstance(items, dict) and items.get("type") == "enum":
            item_schema = enrich_value_schema(items)
            if isinstance(raw, list):
                return [normalize_label_value(v, item_schema) for v in raw]
            return raw

    return raw


def normalize_parsed_labels(taxonomy: dict[str, Any], labels: dict[str, Any]) -> dict[str, Any]:
    by_id = {str(it["id"]): it for it in taxonomy.get("labels") or [] if it.get("id")}
    out: dict[str, Any] = {}
    for label_id, entry in labels.items():
        item = by_id.get(str(label_id))
        schema = None
        if item and isinstance(item.get("value_schema"), dict):
            schema = enrich_value_schema(item["value_schema"])
        if isinstance(entry, dict) and "value" in entry:
            new_entry = dict(entry)
            new_entry["value"] = normalize_label_value(entry.get("value"), schema)
            out[label_id] = new_entry
        else:
            out[label_id] = normalize_label_value(entry, schema)
    return out


def display_label_value(raw: Any, schema: dict[str, Any] | None) -> str:
    if raw is None or raw == "":
        return "—"
    normalized = normalize_label_value(raw, enrich_value_schema(schema) if schema else None)
    if isinstance(normalized, list):
        return "、".join(str(x) for x in normalized if x is not None and str(x) != "")
    if isinstance(normalized, bool):
        return "是" if normalized else "否"
    return str(normalized)
