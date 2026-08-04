"""Capability: label — 对 clips_index 中 clip 打标。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from ..pipeline import write_jsonl
from .clip_manifest import load_clips_from_index
from .transcribe import merge_asr_into_clips
from .types import LabelResult, RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient


def label_clips(
    ctx: RunContext,
    client: OmsMultimodalClient,
    *,
    run_asr: bool = False,
    merge_asr_file: bool = True,
) -> LabelResult:
    """sdk_label：读 clips_index（可选 merge asr.jsonl），写 labels.jsonl。"""
    if merge_asr_file and ctx.asr_path.is_file():
        merge_asr_into_clips(ctx)

    clips = load_clips_from_index(ctx.clips_index_path)
    taxonomy = client.taxonomy
    label_rows: list[dict] = []
    errors: list[dict[str, str]] = []

    for clip in clips:
        try:
            row = client.label_clip(clip, taxonomy=taxonomy, run_asr=run_asr)
            label_rows.append(row)
        except Exception as exc:  # noqa: BLE001
            errors.append({"clip_id": clip.clip_id, "error": str(exc)})

    count = write_jsonl(ctx.labels_path, iter(label_rows))
    return LabelResult(labels_out=ctx.labels_path, row_count=count, errors=errors)
