"""Capability: transcribe — 对 clips_index 中 clip 做 ASR。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..pipeline import write_jsonl
from .clip_manifest import clip_to_manifest, load_clips_from_index, read_clips_index
from .types import RunContext, TranscribeResult

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def merge_asr_into_clips(ctx: RunContext) -> None:
    """将 asr.jsonl 合并进 clips_index（label 节点前可选调用）。"""
    asr_by_id = {str(r.get("clip_id")): r for r in _read_jsonl(ctx.asr_path) if r.get("clip_id")}
    if not asr_by_id:
        return
    merged: list[dict[str, Any]] = []
    for row in read_clips_index(ctx.clips_index_path):
        cid = str(row.get("clip_id") or "")
        asr = asr_by_id.get(cid)
        if asr:
            text = str(asr.get("text") or "").strip()
            if text:
                row["asr_text"] = text
                row["asr_model"] = asr.get("model")
        merged.append(row)
    write_jsonl(ctx.clips_index_path, iter(merged))


def transcribe_clips(ctx: RunContext, client: OmsMultimodalClient) -> TranscribeResult:
    """sdk_asr：读 clips_index，写 asr.jsonl 并回写 clips_index（含 asr_text）。"""
    clips = load_clips_from_index(ctx.clips_index_path)
    asr_rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    updated_manifest: list[dict[str, Any]] = []

    for clip in clips:
        try:
            meta = client.transcribe_clip(clip)
            asr_rows.append({"clip_id": clip.clip_id, **meta})
        except Exception as exc:  # noqa: BLE001
            errors.append({"clip_id": clip.clip_id, "error": str(exc)})
        updated_manifest.append(clip_to_manifest(clip))

    asr_count = write_jsonl(ctx.asr_path, iter(asr_rows))
    write_jsonl(ctx.clips_index_path, iter(updated_manifest))

    return TranscribeResult(asr_out=ctx.asr_path, row_count=asr_count, errors=errors)
