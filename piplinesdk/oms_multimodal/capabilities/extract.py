"""Capability: extract — 解析 rosbag，写 clips_index + clip_videos（无 AI）。"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import ClipConfig
from ..pipeline import _clip_video_row, write_jsonl
from ..rosbag_parser import RosbagExtractor
from .clip_manifest import write_clips_index
from .types import ExtractResult, RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient


def extract_clips(
    ctx: RunContext,
    bag_path: Path | str,
    *,
    client: OmsMultimodalClient | None = None,
    clip_config: ClipConfig | None = None,
) -> ExtractResult:
    """sdk_extract / sdk_discover+parse：产出 clips_index.jsonl 与 clip_videos.jsonl。"""
    bag_path = Path(bag_path)
    cfg = clip_config or ClipConfig()
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    ctx.work_dir.mkdir(parents=True, exist_ok=True)

    acoustic = None
    clip_video = None
    if client is not None:
        acoustic = client.acoustic_panel_config
        clip_video = client.clip_video_config

    extractor = RosbagExtractor(bag_path, ctx.work_dir / bag_path.stem)
    topics = extractor.topics()
    clips = list(
        extractor.iter_clips(
            clip_min_sec=cfg.min_sec,
            clip_max_sec=cfg.max_sec,
            sample_fps=cfg.sample_fps,
            max_clips=cfg.max_clips,
            acoustic_panel_config=acoustic,
            clip_video_config=clip_video,
        )
    )
    index_path = ctx.clips_index_path
    clip_rows = write_clips_index(index_path, iter(clips))
    video_count = write_jsonl(ctx.videos_path, (_clip_video_row(c) for c in clips))

    return ExtractResult(
        clips_index=index_path,
        videos_out=ctx.videos_path,
        clip_rows=clip_rows,
        video_rows=video_count,
        bag=str(bag_path),
        topics=[t.__dict__ for t in topics],
    )
