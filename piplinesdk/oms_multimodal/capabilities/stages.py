from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import ClipConfig
from .annotate_bbox import annotate_bboxes
from .embed import embed_clips
from .encode_preview import encode_preview_videos
from .extract import extract_clips
from .ingest_sources import ingest_sources
from .label import label_clips
from .planner import CapabilityPlanner, PipelinePlan, RunRequest
from .preview import materialize_preview
from .run_meta import write_run_json
from .transcribe import transcribe_clips
from .types import RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient

DRIVER_STAGES = frozenset({"discover", "mc_write", "dispatch"})
UDF_STAGES = frozenset(
    {"ingest", "extract", "bbox", "encode", "asr", "preview", "label", "embed", "upload"}
)
ALL_STAGES = DRIVER_STAGES | UDF_STAGES

_ALIASES = {
    "ingest_sources": "ingest",
    "transcribe": "asr",
    "annotate_bbox": "bbox",
    "encode_preview": "encode",
}


def parse_stages(raw: str | None) -> frozenset[str]:
    if raw is None or not str(raw).strip():
        return ALL_STAGES
    out: set[str] = set()
    for token in str(raw).split(","):
        name = token.strip().lower()
        if not name:
            continue
        name = _ALIASES.get(name, name)
        if name not in ALL_STAGES:
            raise ValueError(f"unknown stage {name!r}; choose from {sorted(ALL_STAGES)}")
        out.add(name)
    return frozenset(out) if out else ALL_STAGES


@dataclass
class StagesResult:
    stages_done: list[str] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    preview_ok: bool = False
    extract_clip_rows: int = 0
    label_rows: int = 0
    embedding_rows: int = 0
    bbox_frame_count: int = 0
    encode_plain_count: int = 0
    encode_bbox_count: int = 0
    plan: PipelinePlan | None = None


def _stage_to_capability(stage: str) -> str:
    return {
        "ingest": "ingest_sources",
        "extract": "extract",
        "bbox": "annotate_bbox",
        "encode": "encode_preview",
        "asr": "transcribe",
        "label": "label",
        "embed": "embed",
        "preview": "preview",
        "upload": "upload",
    }.get(stage, stage)


def run_stages(
    ctx: RunContext,
    bag_path: Path | str,
    client: "OmsMultimodalClient",
    *,
    stages: frozenset[str],
    clip_config: ClipConfig | None = None,
    bag_oss_key: str = "",
    ds: str = "",
    model_backend: str = "mc",
    cleanup_work: bool = False,
) -> StagesResult:
    """Run UDF-side stages in order. Driver-only stages are ignored here."""
    from .planner import PlannedCapability

    bag_path = Path(bag_path)
    wanted = stages & UDF_STAGES
    order = ("ingest", "extract", "bbox", "encode", "asr", "preview", "label", "embed", "upload")
    plan = PipelinePlan(
        steps=[PlannedCapability(_stage_to_capability(s)) for s in order if s in wanted]
    )
    return run_plan(
        ctx,
        bag_path,
        client,
        plan,
        clip_config=clip_config,
        bag_oss_key=bag_oss_key,
        ds=ds,
        model_backend=model_backend,
        cleanup_work=cleanup_work,
    )


def run_plan(
    ctx: RunContext,
    bag_path: Path | str,
    client: "OmsMultimodalClient",
    plan: PipelinePlan,
    *,
    clip_config: ClipConfig | None = None,
    bag_oss_key: str = "",
    ds: str = "",
    model_backend: str = "mc",
    cleanup_work: bool = False,
) -> StagesResult:
    """Execute a PipelinePlan (from CapabilityPlanner or manual construction)."""
    bag_path = Path(bag_path)
    result = StagesResult(plan=plan)
    cfg = clip_config or ClipConfig()

    for step in plan.steps:
        cap = step.capability_id
        params = step.params or {}

        if cap == "ingest_sources":
            man = params.get("manifest") if isinstance(params.get("manifest"), dict) else None
            extracted = ingest_sources(
                ctx,
                manifest=man,
                clip_config=cfg,
            )
            result.extract_clip_rows = extracted.clip_rows
            result.stages_done.append("ingest")

        elif cap == "extract":
            extracted = extract_clips(ctx, bag_path, client=client, clip_config=cfg)
            result.extract_clip_rows = extracted.clip_rows
            result.stages_done.append("extract")

        elif cap == "annotate_bbox":
            from ..bbox import resolve_detector

            det_name = params.get("detector")
            br = annotate_bboxes(
                ctx,
                client,
                detector=resolve_detector(str(det_name)) if det_name else None,
            )
            result.errors.extend(br.errors)
            result.bbox_frame_count = br.frame_count
            result.stages_done.append("bbox")

        elif cap == "encode_preview":
            variants = params.get("variants")
            er = encode_preview_videos(ctx, client, variants=variants)
            result.errors.extend(er.errors)
            result.encode_plain_count = er.plain_count
            result.encode_bbox_count = er.bbox_count
            result.stages_done.append("encode")

        elif cap == "transcribe":
            tr = transcribe_clips(ctx, client)
            result.errors.extend(tr.errors)
            result.stages_done.append("asr")

        elif cap == "preview":
            preview_dir = materialize_preview(ctx)
            result.preview_ok = any(preview_dir.glob("clip_preview_*.mp4")) or (
                preview_dir / "audio.wav"
            ).is_file()
            result.stages_done.append("preview")

        elif cap == "label":
            include_bbox = params.get("include_bbox_context")
            if include_bbox is not None:
                include_bbox = bool(include_bbox)
            include_audio = params.get("include_audio")
            if include_audio is not None:
                include_audio = bool(include_audio)
            merge_asr = params.get("merge_asr_file")
            merge_asr_file = True if merge_asr is None else bool(merge_asr)
            lr = label_clips(
                ctx,
                client,
                run_asr=False,
                merge_asr_file=merge_asr_file,
                include_bbox_context=include_bbox,
                include_audio=include_audio,
            )
            result.errors.extend(lr.errors)
            result.label_rows = lr.row_count
            result.stages_done.append("label")

        elif cap == "embed":
            include_audio = params.get("include_audio")
            if include_audio is not None:
                include_audio = bool(include_audio)
            er = embed_clips(ctx, client, include_audio=include_audio)
            result.errors.extend(er.errors)
            result.embedding_rows = er.row_count
            result.stages_done.append("embed")

        elif cap == "upload":
            write_run_json(
                ctx.run_dir,
                clip_id=ctx.clip_id,
                run_id=ctx.run_id,
                ds=ds or "",
                bag_oss_key=bag_oss_key,
                stages_done=tuple(result.stages_done + ["upload"]),
                model_backend=model_backend,
            )
            result.stages_done.append("upload")

    if cleanup_work and ctx.work_dir is not None:
        import shutil

        work = Path(ctx.work_dir)
        if work.is_dir() and work != ctx.run_dir:
            shutil.rmtree(work, ignore_errors=True)

    return result


def plan_and_run(
    ctx: RunContext,
    bag_path: Path | str | None,
    client: "OmsMultimodalClient",
    *,
    request: RunRequest | None = None,
    planner: CapabilityPlanner | None = None,
    clip_config: ClipConfig | None = None,
    **kwargs: Any,
) -> StagesResult:
    """CapabilityPlanner.plan → run_plan convenience."""
    req = request or RunRequest(bag_path=bag_path, run_dir=ctx.run_dir)
    if req.bag_path is None and bag_path is not None:
        req.bag_path = bag_path
    if req.run_dir is None:
        req.run_dir = ctx.run_dir
    plan = (planner or CapabilityPlanner()).plan(req)
    effective_bag = Path(bag_path) if bag_path is not None else Path(req.bag_path or ".")
    return run_plan(ctx, effective_bag, client, plan, clip_config=clip_config, **kwargs)
