"""Taxonomy version hints for dataset export (R10)."""

from __future__ import annotations

from typing import Any

from hmi.taxonomy_db import get_published_version, get_version


def taxonomy_context_for_filter(filter_json: dict[str, Any] | None) -> dict[str, Any]:
    """Return published vs filter taxonomy info and optional warning (R10)."""
    published = get_published_version()
    filt = filter_json or {}
    filter_tid = (filt.get("taxonomy_version_id") or "").strip() or None

    published_id = str(published["id"]) if published else None
    published_code = str(published["version_code"]) if published else None

    filter_code: str | None = None
    if filter_tid:
        version = get_version(filter_tid)
        filter_code = str(version["version_code"]) if version else None

    warning: str | None = None
    if filter_tid and published_id and filter_tid != published_id:
        warning = (
            f"筛选标签树版本 ({filter_code or filter_tid}) 与当前已发布版本 "
            f"({published_code or published_id}) 不一致；快照 y 仍来自各 clip 校核时的标签树版本。"
        )
    elif not filter_tid and published_id:
        warning = None  # 默认纳入各 clip 自身校核版本，无需警告

    return {
        "published_taxonomy_version_id": published_id,
        "published_taxonomy_version_code": published_code,
        "filter_taxonomy_version_id": filter_tid,
        "filter_taxonomy_version_code": filter_code,
        "taxonomy_version_warning": warning,
    }


def taxonomy_context_for_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    ctx = taxonomy_context_for_filter(snapshot.get("filter_json"))
    # Ready 快照：若 filter 未指定，提示可能混合多 taxonomy 版本
    if not ctx.get("filter_taxonomy_version_id") and snapshot.get("status") == "ready":
        ctx["taxonomy_mixed_hint"] = (
            "未锁定标签树版本；导出 clip 可能含不同标签树版本（R10 保留原校核版本）。"
        )
    return ctx
