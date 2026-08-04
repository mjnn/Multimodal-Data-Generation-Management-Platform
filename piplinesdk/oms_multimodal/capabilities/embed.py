"""Capability: embed — 对 clips_index + labels 生成融合向量。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..pipeline import write_jsonl
from .clip_manifest import load_clips_from_index
from .types import EmbedResult, RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient


def _labels_by_clip_id(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if isinstance(row, dict) and row.get("clip_id"):
            out[str(row["clip_id"])] = row
    return out


def embed_clips(ctx: RunContext, client: OmsMultimodalClient) -> EmbedResult:
    """sdk_embed：读 clips_index + labels.jsonl，写 fusion_embeddings.jsonl。"""
    clips = load_clips_from_index(ctx.clips_index_path)
    labels_map = _labels_by_clip_id(ctx.labels_path)
    embedding_rows: list[dict] = []
    errors: list[dict[str, str]] = []

    for clip in clips:
        try:
            label_row = labels_map.get(clip.clip_id, {})
            extra = str(label_row.get("scene_summary") or "")
            row = client.embed_clip(clip, extra_text=extra)
            embedding_rows.append(row)
        except Exception as exc:  # noqa: BLE001
            errors.append({"clip_id": clip.clip_id, "error": str(exc)})

    count = write_jsonl(ctx.embeddings_path, iter(embedding_rows))
    return EmbedResult(embeddings_out=ctx.embeddings_path, row_count=count, errors=errors)
