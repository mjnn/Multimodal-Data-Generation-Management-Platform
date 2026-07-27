"""Parse Job3 OMS labels_json (values nested under 'values' key)."""

from __future__ import annotations

import json
from typing import Any


def parse_labels_json(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {}


def label_values(labels_json: dict[str, Any]) -> dict[str, Any]:
    values = labels_json.get("values")
    if isinstance(values, dict):
        return values
    return labels_json


def labels_to_clip_dict(raw_labels: str | dict[str, Any] | None) -> dict[str, Any]:
    """Flatten OMS labels_json into clip-level {label_id: value} map."""
    values = label_values(parse_labels_json(raw_labels))
    out: dict[str, Any] = {}
    for key, entry in values.items():
        if isinstance(entry, dict) and "value" in entry:
            out[key] = entry["value"]
        else:
            extracted = extract_value(entry)
            out[key] = extracted if extracted is not None else entry
    return out


def extract_value(entry: Any) -> str | None:
    if entry is None:
        return None
    if isinstance(entry, dict):
        if entry.get("value") is not None:
            return str(entry["value"])
        if entry.get("values") is not None:
            return str(entry["values"])
    return str(entry)


def labels_preview(labels_json: dict[str, Any], max_parts: int = 4) -> str:
    parts: list[str] = []
    for _k, v in label_values(labels_json).items():
        extracted = extract_value(v)
        if extracted:
            parts.append(extracted)
    return "，".join(parts[:max_parts])


def has_label_content(labels_json: dict[str, Any]) -> bool:
    values = label_values(labels_json)
    if not values:
        return False
    return any(extract_value(v) for v in values.values())


def label_value_ids(labels_json: dict[str, Any]) -> list[str]:
    return list(label_values(labels_json).keys())


def match_labels(
    labels_json: dict[str, Any],
    *,
    keyword: str = "",
    label_id: str | None = None,
) -> bool:
    kw = keyword.strip().lower()
    values = label_values(labels_json)
    if label_id and label_id not in values and label_id not in json.dumps(labels_json, ensure_ascii=False):
        return False
    if not kw:
        return has_label_content(labels_json)
    preview = labels_preview(labels_json).lower()
    if kw in preview:
        return True
    blob = json.dumps(values, ensure_ascii=False).lower()
    return kw in blob


def get_clip_label_value(labels_json: dict[str, Any] | None, label_id: str) -> Any:
    if not labels_json:
        return None
    if label_id in labels_json:
        return extract_value(labels_json[label_id])
    values = label_values(labels_json)
    if label_id in values:
        return extract_value(values[label_id])
    return None


def _normalize_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes", "是"):
        return True
    if text in ("false", "0", "no", "否"):
        return False
    return None


def match_label_filters(
    labels_json: dict[str, Any] | None,
    filters: dict[str, Any] | None,
) -> bool:
    if not filters:
        return True
    for label_id, expected in filters.items():
        if expected is None or expected == "":
            continue
        actual_raw = get_clip_label_value(labels_json or {}, label_id)
        if actual_raw is None:
            return False
        if isinstance(expected, bool):
            actual_bool = _normalize_bool(actual_raw)
            if actual_bool is None or actual_bool != expected:
                return False
        elif str(actual_raw) != str(expected):
            return False
    return True
