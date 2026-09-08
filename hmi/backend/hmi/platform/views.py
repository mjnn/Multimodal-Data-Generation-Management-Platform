"""Code-registered overview templates and composable view widgets.

Recipes keep `overview_view` as a preset id (`custom`). Runtime honors
`recipe.overview.list` and `recipe.overview.detail` atomic cards.
"""

from __future__ import annotations

from typing import Any

VIEW_TEMPLATES: dict[str, dict[str, Any]] = {
    "custom": {
        "id": "custom",
        "title": "自定义展示页",
        "description": "按原子组件拼版",
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
    "spectrum_timeline": {
        "id": "spectrum_timeline",
        "surface": "detail",
        "title": "频谱时间轴",
        "description": "单路梅尔或 STFT + 该路波形/SPL",
        "needs": ["mel_matrix", "stft_matrix"],
    },
    "video_timeline": {
        "id": "video_timeline",
        "surface": "detail",
        "title": "视频时间轴",
        "description": "单路预览画面",
        "needs": ["preview_mp4", "frames"],
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
    "labels_tree": {
        "id": "labels_tree",
        "surface": "detail",
        "title": "标签树",
        "description": "当前 run 的 labels_json",
        "needs": ["labels_tree"],
    },
}

VIEW_WIDGET_IDS = frozenset(VIEW_WIDGETS)

PRESET_LAYOUTS: dict[str, dict[str, list[str]]] = {
    "custom": {"list": [], "detail": []},
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
    card: dict[str, Any] = {
        "key": key,
        "widget_id": widget_id,
        "bindings": _normalize_bindings(raw.get("bindings")),
    }
    sync = str(raw.get("sync_group") or "").strip()
    if sync:
        card["sync_group"] = sync
    return card


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
    """Return normalized overview object. Missing lists stay empty (no preset fill)."""
    preset = str(recipe.get("overview_view") or "").strip() or "custom"
    raw = recipe.get("overview")
    if not isinstance(raw, dict):
        raw = {}
    stored_preset = str(raw.get("preset") or "").strip() or preset
    has_lists = "list" in raw or "detail" in raw
    filled = {"list": [], "detail": []}
    list_cards = _normalize_card_list(raw.get("list") if has_lists else filled["list"], surface="list")
    detail_cards = _normalize_card_list(
        raw.get("detail") if has_lists else filled["detail"], surface="detail"
    )
    return {"preset": stored_preset, "list": list_cards, "detail": detail_cards}


def overview_widget_ids(overview: dict[str, Any], surface: str) -> list[str]:
    cards = overview.get(surface) or []
    return [str(c.get("widget_id") or "") for c in cards if isinstance(c, dict)]
