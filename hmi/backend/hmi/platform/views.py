"""Code-registered overview templates and composable view widgets.

Recipes keep `overview_view` as a preset id. Runtime honors `recipe.overview.list`
and `recipe.overview.detail` card lists (see UI-DTYPE-OVERVIEW-COMPOSE).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

VIEW_TEMPLATES: dict[str, dict[str, Any]] = {
    "cabin_timeline": {
        "id": "cabin_timeline",
        "title": "舱内多模时间轴",
        "description": "四路画面 + ASR + 标签（现有 Explorer）",
    },
    "frame_gallery_bbox": {
        "id": "frame_gallery_bbox",
        "title": "帧画廊 + BBox",
        "description": "抽帧序列叠加检测框",
    },
    "audio_spec_asr": {
        "id": "audio_spec_asr",
        "title": "音频频谱 + ASR",
        "description": "波形/梅尔 + 转写（带 ASR 的音频类型）",
    },
    "audio_nvh_timeline": {
        "id": "audio_nvh_timeline",
        "title": "四通道频谱时间轴",
        "description": "四通道梅尔频谱 + 波形 + SPL 共用时间轴（无 ASR、无画面）",
    },
    "json_tree": {
        "id": "json_tree",
        "title": "JSON 结构树",
        "description": "结构化文本浏览",
    },
}

VIEW_TEMPLATE_IDS = frozenset(VIEW_TEMPLATES)

VIEW_WIDGETS: dict[str, dict[str, Any]] = {
    "clip_metrics": {
        "id": "clip_metrics",
        "surface": "list",
        "title": "Clip 统计",
        "description": "饼图 + 状态计数",
        "needs": [],
    },
    "label_search": {
        "id": "label_search",
        "surface": "list",
        "title": "标签/ASR 检索",
        "description": "总览检索条",
        "needs": ["asr_jsonl", "labels_tree"],
    },
    "clip_table": {
        "id": "clip_table",
        "surface": "list",
        "title": "Clip 表",
        "description": "状态 / 校核 / 时长",
        "needs": [],
    },
    "nvh_spl_column": {
        "id": "nvh_spl_column",
        "surface": "list",
        "title": "声压摘要列",
        "description": "表上 Leq / 通道摘要",
        "needs": ["spl_jsonl", "spl_timeline", ".wav"],
    },
    "cabin_multicam": {
        "id": "cabin_multicam",
        "surface": "detail",
        "title": "舱内多路时间轴",
        "description": "多路预览 + 时间轴",
        "needs": ["frames", "preview_mp4"],
    },
    "nvh_spectrum": {
        "id": "nvh_spectrum",
        "surface": "detail",
        "title": "四通道频谱时间轴",
        "description": "梅尔 + SPL + 波形",
        "needs": ["mel_matrix", "spl_jsonl", "spl_timeline", ".wav"],
    },
    "asr_panel": {
        "id": "asr_panel",
        "surface": "detail",
        "title": "ASR 文本",
        "description": "转写段落",
        "needs": ["asr_jsonl"],
    },
    "frame_gallery_bbox": {
        "id": "frame_gallery_bbox",
        "surface": "detail",
        "title": "帧画廊 + BBox",
        "description": "抽帧叠加检测框",
        "needs": ["frames", "bboxes_jsonl"],
    },
    "json_tree": {
        "id": "json_tree",
        "surface": "detail",
        "title": "JSON 结构",
        "description": "结构化产物 / labels",
        "needs": ["structured_json", ".json"],
    },
}

VIEW_WIDGET_IDS = frozenset(VIEW_WIDGETS)

PRESET_LAYOUTS: dict[str, dict[str, list[str]]] = {
    "cabin_timeline": {
        "list": ["clip_metrics", "label_search", "clip_table"],
        "detail": ["cabin_multicam", "asr_panel"],
    },
    "audio_nvh_timeline": {
        "list": ["clip_metrics", "nvh_spl_column", "clip_table"],
        "detail": ["nvh_spectrum"],
    },
    "audio_spec_asr": {
        "list": ["clip_metrics", "clip_table"],
        "detail": ["nvh_spectrum", "asr_panel"],
    },
    "frame_gallery_bbox": {
        "list": ["clip_metrics", "clip_table"],
        "detail": ["frame_gallery_bbox"],
    },
    "json_tree": {
        "list": ["clip_metrics", "clip_table"],
        "detail": ["json_tree"],
    },
}


def list_view_templates() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for preset_id, meta in VIEW_TEMPLATES.items():
        item = dict(meta)
        layout = PRESET_LAYOUTS.get(preset_id) or {"list": ["clip_table"], "detail": []}
        item["list"] = list(layout["list"])
        item["detail"] = list(layout["detail"])
        out.append(item)
    return out


def list_view_widgets() -> list[dict[str, Any]]:
    return [dict(v) for v in VIEW_WIDGETS.values()]


def cards_from_preset(preset_id: str, prefix: str = "") -> dict[str, list[dict[str, Any]]]:
    layout = PRESET_LAYOUTS.get(preset_id) or {"list": ["clip_table"], "detail": []}
    return {
        "list": [_default_card(wid, f"{prefix}list") for wid in layout["list"]],
        "detail": [_default_card(wid, f"{prefix}detail") for wid in layout["detail"]],
    }


def _default_card(widget_id: str, prefix: str) -> dict[str, Any]:
    return {"key": f"{prefix}-{widget_id}", "widget_id": widget_id, "bindings": {}}


def _normalize_binding(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("overview binding must be an object")
    kind = str(raw.get("kind") or "").strip()
    if kind == "slot":
        slot_id = str(raw.get("slot_id") or "").strip()
        if not slot_id:
            raise ValueError("overview slot binding requires slot_id")
        return {"kind": "slot", "slot_id": slot_id}
    if kind == "upstream":
        step_key = str(raw.get("step_key") or "").strip()
        if not step_key:
            raise ValueError("overview upstream binding requires step_key")
        out: dict[str, Any] = {"kind": "upstream", "step_key": step_key}
        port_id = str(raw.get("port_id") or "").strip()
        if port_id:
            out["port_id"] = port_id
        return out
    raise ValueError(f"overview binding.kind must be slot|upstream, got {kind!r}")


def _normalize_bindings(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("overview card.bindings must be an object")
    out: dict[str, Any] = {}
    for port_id, value in raw.items():
        pid = str(port_id or "").strip()
        if not pid:
            continue
        if isinstance(value, list):
            out[pid] = [_normalize_binding(item) for item in value]
        else:
            out[pid] = _normalize_binding(value)
    return out


def _normalize_card(raw: Any, *, surface: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"overview.{surface}[{index}] must be an object")
    widget_id = str(raw.get("widget_id") or "").strip()
    if not widget_id:
        raise ValueError(f"overview.{surface}[{index}].widget_id is required")
    spec = VIEW_WIDGETS.get(widget_id)
    if spec is None:
        raise ValueError(f"unknown overview widget_id={widget_id!r}")
    if spec["surface"] != surface:
        raise ValueError(
            f"widget {widget_id!r} belongs on {spec['surface']}, not {surface}"
        )
    key = str(raw.get("key") or "").strip() or f"{surface}-{index}-{widget_id}"
    return {
        "key": key,
        "widget_id": widget_id,
        "bindings": _normalize_bindings(raw.get("bindings")),
    }


def _normalize_card_list(raw: Any, *, surface: str) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"overview.{surface} must be a list")
    cards = [_normalize_card(item, surface=surface, index=idx) for idx, item in enumerate(raw)]
    seen: set[str] = set()
    for card in cards:
        if card["key"] in seen:
            raise ValueError(f"duplicate overview.{surface} key={card['key']!r}")
        seen.add(card["key"])
    return cards


def hydrate_overview(recipe: dict[str, Any]) -> dict[str, Any]:
    """Return normalized overview object. Missing lists are filled from preset."""
    preset = str(recipe.get("overview_view") or "").strip() or "cabin_timeline"
    raw = recipe.get("overview")
    if not isinstance(raw, dict):
        raw = {}
    stored_preset = str(raw.get("preset") or "").strip() or preset
    has_lists = "list" in raw or "detail" in raw
    filled = cards_from_preset(preset) if not has_lists else None
    list_cards = _normalize_card_list(raw.get("list") if has_lists else filled["list"], surface="list")
    detail_cards = _normalize_card_list(
        raw.get("detail") if has_lists else filled["detail"], surface="detail"
    )
    return {"preset": stored_preset, "list": list_cards, "detail": detail_cards}


def overview_widget_ids(overview: dict[str, Any], surface: str) -> list[str]:
    cards = overview.get(surface) or []
    return [str(c.get("widget_id") or "") for c in cards if isinstance(c, dict)]
