"""Capability: annotate_bbox — detect + draw boxes on frames (does not overwrite originals)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from ..bbox import BBoxDetector, FrameBBoxes, draw_bboxes_on_image, resolve_detector
from ..pipeline import write_jsonl
from ..rosbag_parser import FramePayload
from .clip_manifest import load_clips_from_index, write_clips_index
from .types import BBoxResult, RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient

logger = logging.getLogger(__name__)


def _annotated_path(src: Path) -> Path:
    return src.with_name(f"{src.stem}_bbox{src.suffix or '.jpg'}")


def _frames_for_clip(clip) -> list[FramePayload]:
    """Prefer full-rate video_frames; fall back to Omni sample frames."""
    if clip.video_frames:
        return list(clip.video_frames)
    return list(clip.frames)


def annotate_bboxes(
    ctx: RunContext,
    client: OmsMultimodalClient | None = None,
    *,
    detector: BBoxDetector | None = None,
) -> BBoxResult:
    """sdk_bbox：读 clips_index，写 bboxes.jsonl + ``*_bbox.jpg``，回写 manifest。"""
    _ = client  # reserved for future MC-backed detectors via client
    det = detector or resolve_detector()
    clips = load_clips_from_index(ctx.clips_index_path)
    rows: list[dict] = []
    errors: list[dict[str, str]] = []
    box_count = 0
    frame_count = 0
    updated: list = []

    for clip in clips:
        path_map: dict[str, str] = dict(clip.bbox_frame_paths or {})
        try:
            for frame in _frames_for_clip(clip):
                src = Path(frame.image_path)
                if not src.is_file():
                    errors.append(
                        {
                            "clip_id": clip.clip_id,
                            "error": f"missing frame: {frame.image_path}",
                        }
                    )
                    continue
                boxes = det.detect(src)
                dst = _annotated_path(src)
                if boxes:
                    draw_bboxes_on_image(src, boxes, dst)
                else:
                    # Still materialize a sidecar so encode_bbox has a stable path.
                    if not dst.is_file():
                        dst.write_bytes(src.read_bytes())
                annotated = str(dst.resolve())
                path_map[str(src.resolve())] = annotated
                path_map[frame.image_path] = annotated
                frame_count += 1
                box_count += len(boxes)
                rows.append(
                    FrameBBoxes(
                        clip_id=clip.clip_id,
                        topic=frame.topic,
                        timestamp_ns=frame.timestamp_ns,
                        image_path=frame.image_path,
                        boxes=boxes,
                        annotated_image_path=annotated,
                    ).to_dict()
                )
            clip.bbox_enabled = True
            clip.bbox_frame_paths = path_map
            updated.append(clip)
        except Exception as exc:  # noqa: BLE001
            logger.warning("annotate_bbox failed for %s: %s", clip.clip_id, exc)
            errors.append({"clip_id": clip.clip_id, "error": str(exc)})
            updated.append(clip)

    write_clips_index(ctx.clips_index_path, iter(updated))
    out = ctx.bboxes_path
    write_jsonl(out, iter(rows))
    return BBoxResult(
        bboxes_out=out,
        frame_count=frame_count,
        box_count=box_count,
        clip_count=len(updated),
        errors=errors,
    )
