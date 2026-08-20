"""Code-registered overview view templates (recipes only store the id)."""

from __future__ import annotations

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


def list_view_templates() -> list[dict[str, Any]]:
    return [dict(v) for v in VIEW_TEMPLATES.values()]
