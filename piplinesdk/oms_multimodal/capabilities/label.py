"""Capability: label — 对 clips_index 中 clip 打标。"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from ..bbox import load_bbox_context_by_clip
from ..pipeline import write_jsonl
from .clip_manifest import load_clips_from_index
from .transcribe import merge_asr_into_clips
from .types import LabelResult, RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _resolve_include_bbox_context(include_bbox_context: bool | None) -> bool:
    """Default ON when unset; ``BBOX_IN_LABEL_PROMPT=0`` forces off."""
    if include_bbox_context is not None:
        return bool(include_bbox_context)
    return _env_bool("BBOX_IN_LABEL_PROMPT", True)


def attach_bbox_context_to_clips(
    ctx: RunContext,
    clips: list,
    *,
    include_bbox_context: bool | None = None,
) -> None:
    """When enabled and ``bboxes.jsonl`` exists, set ``clip.bbox_context_text``."""
    if not _resolve_include_bbox_context(include_bbox_context):
        return
    if not ctx.bboxes_path.is_file() or ctx.bboxes_path.stat().st_size <= 0:
        return
    by_clip = load_bbox_context_by_clip(ctx.bboxes_path)
    if not by_clip:
        return
    fallback = by_clip.get("") or ""
    for clip in clips:
        text = by_clip.get(clip.clip_id) or fallback
        if text:
            clip.bbox_context_text = text


def label_clips(
    ctx: RunContext,
    client: OmsMultimodalClient,
    *,
    run_asr: bool = False,
    merge_asr_file: bool = True,
    include_bbox_context: bool | None = None,
) -> LabelResult:
    """sdk_label：读 clips_index（可选 merge asr.jsonl / bbox 检出文本），写 labels.jsonl。"""
    if merge_asr_file and ctx.asr_path.is_file():
        merge_asr_into_clips(ctx)

    clips = load_clips_from_index(ctx.clips_index_path)
    attach_bbox_context_to_clips(ctx, clips, include_bbox_context=include_bbox_context)
    taxonomy = client.taxonomy
    label_rows: list[dict] = []
    errors: list[dict[str, str]] = []

    for clip in clips:
        try:
            row = client.label_clip(clip, taxonomy=taxonomy, run_asr=run_asr)
            if getattr(clip, "bbox_context_text", None):
                row["bbox_context"] = clip.bbox_context_text
            label_rows.append(row)
        except Exception as exc:  # noqa: BLE001
            errors.append({"clip_id": clip.clip_id, "error": str(exc)})

    count = write_jsonl(ctx.labels_path, iter(label_rows))
    return LabelResult(labels_out=ctx.labels_path, row_count=count, errors=errors)
