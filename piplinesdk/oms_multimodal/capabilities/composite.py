"""Capability: infer_full — 单节点复合（等价原 process_bag）。"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..config import ClipConfig
from .embed import embed_clips
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
    """sdk_infer 单节点：extract → transcribe → label → embed → preview。"""
    extracted = extract_clips(ctx, bag_path, client=client, clip_config=clip_config)
    errors: list[dict[str, str]] = []

    if not skip_asr and client.asr_config.enabled:
        tr = transcribe_clips(ctx, client)
        errors.extend(tr.errors)

    lr = label_clips(ctx, client, run_asr=False, merge_asr_file=True)
    errors.extend(lr.errors)

    er = embed_clips(ctx, client)
    errors.extend(er.errors)

    materialize_preview(ctx)

    return InferFullResult(
        extract=extracted,
        labels_out=ctx.labels_path,
        embeddings_out=ctx.embeddings_path,
        label_rows=lr.row_count,
        embedding_rows=er.row_count,
        errors=errors,
    )
