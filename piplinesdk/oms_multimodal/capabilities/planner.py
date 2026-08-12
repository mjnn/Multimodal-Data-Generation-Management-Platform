"""CapabilityPlanner: params + data shape → ordered capability list."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..rosbag_parser import inspect_bag
from .encode_preview import resolve_encode_variants


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


@dataclass
class PlannedCapability:
    capability_id: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelinePlan:
    steps: list[PlannedCapability] = field(default_factory=list)

    @property
    def capability_ids(self) -> list[str]:
        return [s.capability_id for s in self.steps]


@dataclass
class RunRequest:
    """Inputs for CapabilityPlanner.plan (env fills None fields)."""

    bag_path: Path | str | None = None
    run_dir: Path | str | None = None
    # Explicit modality overrides (None = inspect bag / source_manifest / run_dir)
    has_video: bool | None = None
    has_audio: bool | None = None
    has_text: bool | None = None
    # Uploaded/pre-encoded MP4 etc.: skip encode_preview (bag-frame encode), keep 抽帧 via ingest
    has_preencoded_video: bool | None = None
    source_manifest_path: Path | str | None = None
    need_extract: bool | None = None
    need_asr: bool | None = None
    need_label: bool | None = None
    need_embed: bool | None = None
    need_preview: bool | None = None
    bbox_enabled: bool | None = None
    encode_plain: bool | None = None
    encode_bbox: bool | None = None
    # When True (default), label stage injects BBox class summary into Omni prompt if bboxes.jsonl exists
    bbox_in_label_prompt: bool | None = None
    skip_existing: bool = True


@dataclass
class _DataShape:
    has_image: bool = True
    has_audio: bool = True
    has_text: bool = False
    has_preencoded_video: bool = False
    has_clips_index: bool = False
    has_bboxes: bool = False
    inspected_bag: bool = False
    has_source_manifest: bool = False
    source_manifest: dict[str, Any] = field(default_factory=dict)


def _load_source_manifest(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _resolve_manifest_path(request: RunRequest) -> Path | None:
    if request.source_manifest_path:
        return Path(request.source_manifest_path)
    run_dir = Path(request.run_dir) if request.run_dir else None
    if run_dir is None:
        return None
    for name in ("source_manifest.json", "sources_manifest.json"):
        cand = run_dir / name
        if cand.is_file():
            return cand
    return None


def _apply_manifest(shape: _DataShape, manifest: dict[str, Any]) -> None:
    shape.has_source_manifest = True
    shape.source_manifest = manifest
    mods = {str(m).lower() for m in (manifest.get("modalities") or []) if m}
    if not mods:
        if manifest.get("video") or manifest.get("video_path"):
            mods.add("video")
        if manifest.get("audio") or manifest.get("audio_path"):
            mods.add("audio")
        if manifest.get("text") or manifest.get("text_path"):
            mods.add("text")
    if mods:
        shape.has_image = "video" in mods or "image" in mods
        shape.has_audio = "audio" in mods
        shape.has_text = "text" in mods
    if "has_preencoded_video" in manifest:
        shape.has_preencoded_video = bool(manifest.get("has_preencoded_video"))
    elif shape.has_image and (manifest.get("video") or manifest.get("video_path")):
        shape.has_preencoded_video = True


def _inspect_shape(request: RunRequest) -> _DataShape:
    shape = _DataShape()
    run_dir = Path(request.run_dir) if request.run_dir else None
    if run_dir is not None:
        clips = run_dir / "clips_index.jsonl"
        shape.has_clips_index = clips.is_file() and clips.stat().st_size > 0
        bboxes = run_dir / "bboxes.jsonl"
        shape.has_bboxes = bboxes.is_file() and bboxes.stat().st_size > 0

    manifest_path = _resolve_manifest_path(request)
    manifest = _load_source_manifest(manifest_path)
    if manifest is not None:
        _apply_manifest(shape, manifest)

    bag = Path(request.bag_path) if request.bag_path else None
    if bag is not None and bag.is_file() and bag.suffix.lower() == ".bag":
        try:
            topics = inspect_bag(bag)
            modalities = {t.modality for t in topics}
            shape.has_image = "image" in modalities
            shape.has_audio = "audio" in modalities
            shape.has_text = shape.has_text or ("text" in modalities)
            shape.inspected_bag = True
        except Exception:  # noqa: BLE001
            pass

    # Explicit overrides win
    if request.has_video is not None:
        shape.has_image = bool(request.has_video)
    if request.has_audio is not None:
        shape.has_audio = bool(request.has_audio)
    if request.has_text is not None:
        shape.has_text = bool(request.has_text)
    if request.has_preencoded_video is not None:
        shape.has_preencoded_video = bool(request.has_preencoded_video)

    return shape


class CapabilityPlanner:
    """Map run request + bag/artifact/source shape to an ordered capability plan."""

    def plan(self, request: RunRequest | None = None) -> PipelinePlan:
        req = request or RunRequest()
        shape = _inspect_shape(req)

        need_label = True if req.need_label is None else req.need_label
        need_embed = True if req.need_embed is None else req.need_embed
        need_asr = True if req.need_asr is None else req.need_asr
        need_preview = True if req.need_preview is None else req.need_preview

        if req.encode_plain is not None or req.encode_bbox is not None:
            encode_plain = bool(req.encode_plain) if req.encode_plain is not None else False
            encode_bbox = bool(req.encode_bbox) if req.encode_bbox is not None else False
            if req.encode_plain is None:
                encode_plain = _env_bool("ENCODE_PLAIN", True)
            if req.encode_bbox is None:
                encode_bbox = _env_bool("ENCODE_BBOX", False)
        else:
            variants = resolve_encode_variants(None)
            encode_plain = "plain" in variants
            encode_bbox = "bbox" in variants

        bbox_enabled = (
            req.bbox_enabled
            if req.bbox_enabled is not None
            else _env_bool("BBOX_ENABLED", encode_bbox)
        )
        if encode_bbox:
            bbox_enabled = True

        steps: list[PlannedCapability] = []

        # --- ingest_sources (raw video/audio/text; includes 抽帧 when video present) ---
        want_ingest = False
        if shape.has_source_manifest and not (
            req.bag_path and Path(req.bag_path).is_file() and Path(req.bag_path).suffix.lower() == ".bag"
        ):
            if req.skip_existing and shape.has_clips_index:
                want_ingest = False
            else:
                want_ingest = True
        if want_ingest:
            steps.append(
                PlannedCapability(
                    "ingest_sources",
                    {"manifest": shape.source_manifest},
                )
            )

        # --- extract (rosbag only) ---
        bag_ok = bool(req.bag_path) and Path(req.bag_path).is_file() and Path(req.bag_path).suffix.lower() == ".bag"
        if req.need_extract is not None:
            want_extract = req.need_extract
        elif req.skip_existing and shape.has_clips_index:
            want_extract = False
        elif want_ingest:
            want_extract = False
        else:
            want_extract = bag_ok
            if shape.inspected_bag and not shape.has_image and not shape.has_audio and not shape.has_text:
                want_extract = False
        if want_extract:
            steps.append(PlannedCapability("extract"))

        will_have_frames = (
            shape.has_image
            or want_extract
            or want_ingest
            or shape.has_clips_index
            or (not shape.inspected_bag and not shape.has_source_manifest and bag_ok)
        )

        # --- annotate_bbox ---
        want_bbox = bbox_enabled and will_have_frames and shape.has_image
        if want_bbox and req.skip_existing and shape.has_bboxes:
            want_bbox = False
        if encode_bbox and shape.has_image and not shape.has_bboxes:
            want_bbox = True
        if want_bbox and shape.inspected_bag and not shape.has_image and not shape.has_clips_index and not want_extract:
            want_bbox = False
        if want_bbox and shape.has_source_manifest and not shape.has_image:
            want_bbox = False
        if want_bbox:
            steps.append(
                PlannedCapability(
                    "annotate_bbox",
                    {"detector": os.getenv("BBOX_DETECTOR", "noop")},
                )
            )

        # --- encode_preview (skip when caller already supplied encoded video) ---
        want_encode = (encode_plain or encode_bbox) and shape.has_image and not shape.has_preencoded_video
        if want_encode and shape.inspected_bag and not shape.has_image and not shape.has_clips_index and not want_extract:
            want_encode = False
        if want_encode and shape.has_source_manifest and not shape.has_image:
            want_encode = False
        if want_encode:
            variants = [
                v
                for v in ("plain", "bbox")
                if (v == "plain" and encode_plain) or (v == "bbox" and encode_bbox)
            ]
            steps.append(PlannedCapability("encode_preview", {"variants": variants}))

        # --- asr ---
        if need_asr and shape.has_audio:
            steps.append(PlannedCapability("transcribe"))

        # Label / embed: text-only sources still run when need_* True
        can_label = shape.has_image or shape.has_audio or shape.has_text or want_extract or want_ingest or not (
            shape.inspected_bag or shape.has_source_manifest
        )
        include_bbox_in_label = (
            req.bbox_in_label_prompt
            if req.bbox_in_label_prompt is not None
            else _env_bool("BBOX_IN_LABEL_PROMPT", True)
        )
        if need_label and can_label:
            label_params: dict[str, Any] = {
                "include_bbox_context": bool(include_bbox_in_label),
            }
            steps.append(PlannedCapability("label", label_params))
        if need_embed and can_label:
            steps.append(PlannedCapability("embed"))
        if need_preview and (
            shape.has_image
            or shape.has_audio
            or shape.has_preencoded_video
            or want_extract
            or (want_ingest and (shape.has_image or shape.has_audio))
        ):
            steps.append(PlannedCapability("preview"))

        return PipelinePlan(steps=steps)
