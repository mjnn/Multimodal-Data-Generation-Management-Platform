"""OMS Multimodal SDK — Rosbag 多模态打标与融合向量。

Public API::

    from oms_multimodal import OmsMultimodalClient, ClipConfig, AcousticPanelConfig

    client = OmsMultimodalClient(taxonomy_path="oms_label_taxonomy.yaml")
    result = client.process_bag("rosbag/output.bag")
"""
from __future__ import annotations

__version__ = "0.3.0"

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
from .resources import bundled_sdk_doc_path, bundled_taxonomy_path, resolve_taxonomy_path
from .embedding_client import FusionEmbeddingClient
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
from .taxonomy import load_taxonomy, parse_label_json, taxonomy_prompt_block

__all__ = [
    "__version__",
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
    "mel_matrix_to_feature_text",
    "render_acoustic_assets",
    "render_acoustic_panel",
    "render_clip_preview_video",
    "resolve_bags",
    "resolve_taxonomy_path",
    "save_mel_matrix",
    "taxonomy_prompt_block",
    "write_jsonl",
]
