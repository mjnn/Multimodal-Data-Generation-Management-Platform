"""Capability: infer_full — 单节点复合（等价原 process_bag）。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import ClipConfig
from .annotate_bbox import annotate_bboxes
from .embed import embed_clips
from .encode_preview import encode_preview_videos, resolve_encode_variants
from .extract import extract_clips
from .label import label_clips
from .preview import materialize_preview
from .transcribe import transcribe_clips
from .types import InferFullResult, RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient


def infer_full(
    ctx: RunContext,
    bag_path: Path | str,
    client: OmsMultimodalClient,
    *,
    clip_config: ClipConfig | None = None,
    skip_asr: bool = False,
) -> InferFullResult:
    """sdk_infer：extract → [annotate_bbox] → encode_preview → asr → label → embed → preview。

    bbox / 双视频由 ``BBOX_ENABLED`` / ``ENCODE_PLAIN`` / ``ENCODE_BBOX`` 决定。
    """
    extracted = extract_clips(ctx, bag_path, client=client, clip_config=clip_config)
    errors: list[dict[str, str]] = []

    variants = resolve_encode_variants(None)
    bbox_enabled = os.getenv("BBOX_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if bbox_enabled or "bbox" in variants:
        br = annotate_bboxes(ctx, client)
        errors.extend(br.errors)
    if variants:
        er = encode_preview_videos(ctx, client, variants=variants)
        errors.extend(er.errors)

    if not skip_asr and client.asr_config.enabled:
        tr = transcribe_clips(ctx, client)
        errors.extend(tr.errors)

    lr = label_clips(ctx, client, run_asr=False, merge_asr_file=True)
    errors.extend(lr.errors)

    emb = embed_clips(ctx, client)
    errors.extend(emb.errors)

    materialize_preview(ctx)

    return InferFullResult(
        extract=extracted,
        labels_out=ctx.labels_path,
        embeddings_out=ctx.embeddings_path,
        label_rows=lr.row_count,
        embedding_rows=emb.row_count,
        errors=errors,
    )
