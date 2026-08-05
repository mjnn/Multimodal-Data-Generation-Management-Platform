"""OMS Multimodal SDK — Rosbag 多模态打标与融合向量。

Public API::

    from oms_multimodal import OmsMultimodalClient, ClipConfig, AcousticPanelConfig

    client = OmsMultimodalClient(taxonomy_path="oms_label_taxonomy.yaml")
    result = client.process_bag("rosbag/output.bag")
"""
from __future__ import annotations

__version__ = "0.3.2"

from .acoustic_panel import (
    AcousticPanelConfig,
    PanelType,
    compute_mel_matrix,
    mel_matrix_to_feature_text,
    render_acoustic_assets,
    render_acoustic_panel,
    save_mel_matrix,
)
from .asr_client import AsrClient, AsrConfig
from .clip_video import ClipVideoConfig, encode_clip_mp4, render_clip_preview_video
from .client import OmsMultimodalClient
from .config import BagProcessResult, ClientConfig, ClipConfig, ModelBackend, OutputConfig
from .embedding_client import FusionEmbeddingClient
from .resources import bundled_sdk_doc_path, bundled_taxonomy_path, resolve_taxonomy_path
from .capabilities import (
    ALL_STAGES,
    CAPABILITY_IDS,
    DRIVER_STAGES,
    STEP_TO_CAPABILITY,
    UDF_STAGES,
    EmbedResult,
    ExtractResult,
    InferFullResult,
    LabelResult,
    MediaInputMode,
    RunContext,
    StagesResult,
    TranscribeResult,
    apply_run_context_to_mc_config,
    embed_clips,
    extract_clips,
    infer_full,
    label_clips,
    materialize_preview,
    merge_asr_into_clips,
    parse_stages,
    run_stages,
    transcribe_clips,
    write_run_json,
)
from .exceptions import ApiError, ConfigurationError, OmsMultimodalError, ParseError
from .omni_client import OmniLabelClient
from .pipeline import LabelEmbeddingPipeline, resolve_bags, write_jsonl
from .rosbag_parser import (
    AudioPayload,
    Clip,
    FramePayload,
    RosbagExtractor,
    TextPayload,
    TopicInfo,
    inspect_bag,
)
from .label_prompt import (
    OMNI_LABEL_PROMPT_FIELD_META,
    default_omni_label_prompt,
    merge_omni_label_prompt,
)
from .model_factory import (
    create_asr_client,
    create_embedding_client,
    create_mc_runtime,
    create_omni_client,
    validate_backend_config,
)
from .taxonomy import load_taxonomy, parse_label_json, taxonomy_prompt_block

__all__ = [
    "__version__",
    "ALL_STAGES",
    "AcousticPanelConfig",
    "ApiError",
    "AsrClient",
    "AsrConfig",
    "AudioPayload",
    "BagProcessResult",
    "bundled_sdk_doc_path",
    "bundled_taxonomy_path",
    "ClientConfig",
    "Clip",
    "ClipConfig",
    "ClipVideoConfig",
    "ConfigurationError",
    "encode_clip_mp4",
    "FramePayload",
    "CAPABILITY_IDS",
    "DRIVER_STAGES",
    "STEP_TO_CAPABILITY",
    "UDF_STAGES",
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
    "EmbedResult",
    "ExtractResult",
    "InferFullResult",
    "LabelResult",
    "MediaInputMode",
    "RunContext",
    "StagesResult",
    "TranscribeResult",
    "FusionEmbeddingClient",
    "LabelEmbeddingPipeline",
    "ModelBackend",
    "OmsMultimodalClient",
    "OmsMultimodalError",
    "OmniLabelClient",
    "OutputConfig",
    "PanelType",
    "ParseError",
    "RosbagExtractor",
    "TextPayload",
    "TopicInfo",
    "inspect_bag",
    "load_taxonomy",
    "merge_omni_label_prompt",
    "default_omni_label_prompt",
    "OMNI_LABEL_PROMPT_FIELD_META",
    "parse_label_json",
    "compute_mel_matrix",
    "create_asr_client",
    "create_embedding_client",
    "create_mc_runtime",
    "create_omni_client",
    "mel_matrix_to_feature_text",
    "render_acoustic_assets",
    "render_acoustic_panel",
    "render_clip_preview_video",
    "resolve_bags",
    "resolve_taxonomy_path",
    "save_mel_matrix",
    "taxonomy_prompt_block",
    "validate_backend_config",
    "write_jsonl",
]
