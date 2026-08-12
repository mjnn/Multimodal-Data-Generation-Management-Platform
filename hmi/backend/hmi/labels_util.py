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


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        text = str(value).strip().replace(",", "")
        try:
            return float(text)
        except (TypeError, ValueError):
            return None


def _match_one_expected(actual_raw: Any, expected: Any) -> bool:
    """Match a single filter value: bool / scalar / list(OR) / {in|eq|min|max}."""
    if expected is None or expected == "":
        return True
    if isinstance(expected, bool):
        actual_bool = _normalize_bool(actual_raw)
        return actual_bool is not None and actual_bool == expected

    if isinstance(expected, (list, tuple, set)):
        opts = [v for v in expected if v is not None and v != ""]
        if not opts:
            return True
        return any(_match_one_expected(actual_raw, v) for v in opts)

    if isinstance(expected, dict):
        if "in" in expected:
            return _match_one_expected(actual_raw, expected.get("in"))
        if "eq" in expected and expected.get("eq") is not None and expected.get("eq") != "":
            return _match_one_expected(actual_raw, expected.get("eq"))
        has_range = expected.get("min") is not None or expected.get("max") is not None
        if has_range:
            actual_num = _to_float(actual_raw)
            if actual_num is None:
                return False
            lo = _to_float(expected.get("min"))
            hi = _to_float(expected.get("max"))
            if lo is not None and actual_num < lo:
                return False
            if hi is not None and actual_num > hi:
                return False
            return True
        return True

    actual_bool = _normalize_bool(actual_raw)
    expected_bool = _normalize_bool(expected)
    if actual_bool is not None and expected_bool is not None:
        return actual_bool == expected_bool
    return str(actual_raw).strip() == str(expected).strip()


def _filter_value_active(expected: Any) -> bool:
    if expected is None or expected == "":
        return False
    if isinstance(expected, (list, tuple, set)):
        return any(v is not None and v != "" for v in expected)
    if isinstance(expected, dict):
        if expected.get("min") is not None and expected.get("min") != "":
            return True
        if expected.get("max") is not None and expected.get("max") != "":
            return True
        if expected.get("eq") is not None and expected.get("eq") != "":
            return True
        inn = expected.get("in")
        if isinstance(inn, (list, tuple, set)):
            return any(v is not None and v != "" for v in inn)
        return inn is not None and inn != ""
    return True


def match_label_filters(
    labels_json: dict[str, Any] | None,
    filters: dict[str, Any] | None,
) -> bool:
    """AND across labels. Per-label value may be scalar, list (OR), or range dict."""
    if not filters:
        return True
    for label_id, expected in filters.items():
        if not _filter_value_active(expected):
            continue
        actual_raw = get_clip_label_value(labels_json or {}, label_id)
        if actual_raw is None:
            return False
        if not _match_one_expected(actual_raw, expected):
            return False
    return True


def extract_scene_description(
    labels_json: dict[str, Any] | None,
    *,
    scene_summary: str | None = None,
) -> str:
    """Prefer explicit scene_summary, then scene_* labels, else short label preview."""
    if scene_summary and str(scene_summary).strip():
        return str(scene_summary).strip()
    parsed = labels_json if isinstance(labels_json, dict) else {}
    root = parsed.get("scene_summary")
    if isinstance(root, str) and root.strip():
        return root.strip()
    values = label_values(parsed)
    for key, entry in values.items():
        key_l = str(key).lower()
        if "scene" in key_l and ("summary" in key_l or "desc" in key_l or "描述" in str(key)):
            text = extract_value(entry)
            if text and text.strip():
                return text.strip()
        name_hint = str(entry.get("name") if isinstance(entry, dict) else "")
        if any(h in name_hint for h in ("场景描述", "场景概述", "场景摘要")):
            text = extract_value(entry)
            if text and text.strip():
                return text.strip()
    # Flat map {label_id: value}
    for key, entry in parsed.items():
        if key in ("values", "scene_summary"):
            continue
        key_l = str(key).lower()
        if "scene" in key_l and ("summary" in key_l or "desc" in key_l):
            text = extract_value(entry) if not isinstance(entry, str) else entry
            if text and str(text).strip():
                return str(text).strip()
    preview = labels_preview(parsed, max_parts=8)
    return preview.strip()
