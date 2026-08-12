"""Capability: encode_preview — optional plain and/or bbox MP4 from clip frames."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from ..clip_video import ClipVideoConfig, render_clip_preview_video
from ..pipeline import _clip_video_row, write_jsonl
from .clip_manifest import load_clips_from_index, write_clips_index
from .types import EncodePreviewResult, RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def resolve_encode_variants(variants: Sequence[str] | None = None) -> list[str]:
    if variants is not None:
        out = [v.strip().lower() for v in variants if v and str(v).strip()]
        return [v for v in out if v in {"plain", "bbox"}]
    plain = _env_bool("ENCODE_PLAIN", True)
    bbox = _env_bool("ENCODE_BBOX", False)
    selected: list[str] = []
    if plain:
        selected.append("plain")
    if bbox:
        selected.append("bbox")
    return selected or ["plain"]


def encode_preview_videos(
    ctx: RunContext,
    client: OmsMultimodalClient | None = None,
    *,
    variants: Sequence[str] | None = None,
    config: ClipVideoConfig | None = None,
) -> EncodePreviewResult:
    """sdk_encode：按 variants 产出 plain 和/或 bbox 预览 MP4，回写 clips_index + clip_videos.jsonl。"""
    cfg = config
    if cfg is None and client is not None:
        cfg = client.clip_video_config
    cfg = cfg or ClipVideoConfig.from_env()
    cfg.enabled = True

    wanted = resolve_encode_variants(variants)
    clips = load_clips_from_index(ctx.clips_index_path)
    errors: list[dict[str, str]] = []
    plain_count = 0
    bbox_count = 0
    updated = []

    for clip in clips:
        if clip.audio and clip.audio.audio_path:
            clip_dir = Path(clip.audio.audio_path).parent
        elif clip.frames:
            clip_dir = Path(clip.frames[0].image_path).parent
        else:
            errors.append({"clip_id": clip.clip_id, "error": "no frames/audio for encode"})
            updated.append(clip)
            continue
        clip_dir.mkdir(parents=True, exist_ok=True)
        source_frames = list(clip.video_frames or clip.frames)

        try:
            if "plain" in wanted:
                path = render_clip_preview_video(
                    clip,
                    clip_dir / (cfg.filename or "clip_preview.mp4"),
                    config=cfg,
                    frames=source_frames,
                    filename_stem=Path(cfg.filename or "clip_preview.mp4").stem,
                    assign_clip_fields=True,
                )
                if path:
                    plain_count += 1

            if "bbox" in wanted:
                path_map = clip.bbox_frame_paths or {}
                if not path_map:
                    logger.warning("encode bbox skipped for %s: no bbox_frame_paths", clip.clip_id)
                else:
                    bbox_stem = "clip_preview_bbox"
                    path = render_clip_preview_video(
                        clip,
                        clip_dir / f"{bbox_stem}.mp4",
                        config=cfg,
                        frames=source_frames,
                        path_map=path_map,
                        filename_stem=bbox_stem,
                        assign_clip_fields=False,
                    )
                    if path:
                        meta = clip.clip_video_config or {}
                        topic_paths = {
                            str(item.get("camera_topic")): str(item.get("path"))
                            for item in (meta.get("encoded_cameras") or [])
                            if item.get("camera_topic") and item.get("path")
                        }
                        clip.clip_video_bbox_paths = topic_paths or {"default": path}
                        clip.clip_video_bbox_path = path
                        bbox_count += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("encode_preview failed for %s: %s", clip.clip_id, exc)
            errors.append({"clip_id": clip.clip_id, "error": str(exc)})

        updated.append(clip)

    write_clips_index(ctx.clips_index_path, iter(updated))
    video_rows = []
    for clip in updated:
        row = _clip_video_row(clip)
        row["clip_video_bbox_path"] = clip.clip_video_bbox_path
        row["clip_video_bbox_paths"] = clip.clip_video_bbox_paths
        video_rows.append(row)
    write_jsonl(ctx.videos_path, iter(video_rows))

    return EncodePreviewResult(
        videos_out=ctx.videos_path,
        plain_count=plain_count,
        bbox_count=bbox_count,
        variants=list(wanted),
        errors=errors,
    )
