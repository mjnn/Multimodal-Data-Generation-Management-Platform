"""SDK 原子能力 — 供 DataWorks 多节点分别调用。

每个 capability 对应一个 step_id，节点只需构造 RunContext + OmsMultimodalClient。

Example (sdk_asr 节点)::

    ctx = RunContext(run_dir=Path(run_out_dir), media_mode="local")
    client = OmsMultimodalClient(...)
    transcribe_clips(ctx, client)
"""
from __future__ import annotations

from .composite import infer_full
from .embed import embed_clips
from .extract import extract_clips
from .label import label_clips
from .media import apply_run_context_to_mc_config
from .preview import materialize_preview
from .run_meta import write_run_json
from .stages import (
    ALL_STAGES,
    DRIVER_STAGES,
    UDF_STAGES,
    StagesResult,
    parse_stages,
    run_stages,
)
from .transcribe import merge_asr_into_clips, transcribe_clips
from .types import (
    CAPABILITY_IDS,
    STEP_TO_CAPABILITY,
    EmbedResult,
    ExtractResult,
    InferFullResult,
    LabelResult,
    MediaInputMode,
    RunContext,
    TranscribeResult,
)

__all__ = [
    "ALL_STAGES",
    "CAPABILITY_IDS",
    "DRIVER_STAGES",
    "STEP_TO_CAPABILITY",
    "UDF_STAGES",
    "EmbedResult",
    "ExtractResult",
    "InferFullResult",
    "LabelResult",
    "MediaInputMode",
    "RunContext",
    "StagesResult",
    "TranscribeResult",
    "apply_run_context_to_mc_config",
    "embed_clips",
    "extract_clips",
    "infer_full",
    "label_clips",
    "materialize_preview",
    "merge_asr_into_clips",
    "parse_stages",
    "run_stages",
    "transcribe_clips",
    "write_run_json",
]
