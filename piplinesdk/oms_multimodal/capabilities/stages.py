from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import ClipConfig
from .embed import embed_clips
from .extract import extract_clips
from .label import label_clips
from .preview import materialize_preview
from .run_meta import write_run_json
from .transcribe import transcribe_clips
from .types import RunContext

if TYPE_CHECKING:
    from ..client import OmsMultimodalClient

DRIVER_STAGES = frozenset({"discover", "mc_write", "dispatch"})
UDF_STAGES = frozenset({"extract", "asr", "preview", "label", "embed", "upload"})
ALL_STAGES = DRIVER_STAGES | UDF_STAGES

_ALIASES = {"transcribe": "asr"}


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
    bag_path = Path(bag_path)
    wanted = stages & UDF_STAGES
    result = StagesResult()
    cfg = clip_config or ClipConfig()

    if "extract" in wanted:
        extracted = extract_clips(ctx, bag_path, client=client, clip_config=cfg)
        result.extract_clip_rows = extracted.clip_rows
        result.stages_done.append("extract")

    # stages_done: append when a capability call completes (no raise); errors still collected.
    if "asr" in wanted:
        tr = transcribe_clips(ctx, client)
        result.errors.extend(tr.errors)
        result.stages_done.append("asr")

    if "preview" in wanted:
        preview_dir = materialize_preview(ctx)
        result.preview_ok = any(preview_dir.glob("clip_preview_*.mp4")) or (preview_dir / "audio.wav").is_file()
        result.stages_done.append("preview")

    if "label" in wanted:
        lr = label_clips(ctx, client, run_asr=False, merge_asr_file=True)
        result.errors.extend(lr.errors)
        result.label_rows = lr.row_count
        result.stages_done.append("label")

    if "embed" in wanted:
        er = embed_clips(ctx, client)
        result.errors.extend(er.errors)
        result.embedding_rows = er.row_count
        result.stages_done.append("embed")

    if "upload" in wanted:
        # Mount path IS the OSS tree when run_dir is under mount; write run.json as commit marker.
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
