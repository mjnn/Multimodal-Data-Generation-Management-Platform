"""OSS object key helpers for clip-omni pipeline v2."""

from __future__ import annotations

from hmi.config import get_settings
from hmi.oss_layout import (
    CLIP_AI_CONSENSUS_META_KEY,
    CLIP_AI_EMBEDDING_KEY,
    CLIP_AI_INFER_META_KEY,
    CLIP_AI_LABELS_KEY,
    CLIP_AI_LABELS_MERGED_KEY,
    CLIP_AI_LABELS_PRIMARY_KEY,
    CLIP_AI_LABELS_SECONDARY_KEY,
    CLIP_ALIGNED_SYNC_MANIFEST_KEY,
    CLIP_ALIGNED_TIMELINE_KEY,
    CLIP_RUN_AI_PREFIX,
    CLIP_RUN_ALIGNED_PREFIX,
    CLIP_RUN_PARSED_PREFIX,
    review_labels_key,
    review_meta_key,
)


def clip_run_prefix(clip_id: str, run_id: str) -> str:
    settings = get_settings()
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs}/"


def clip_parsed_prefix(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_RUN_PARSED_PREFIX}"


def clip_aligned_prefix(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_RUN_ALIGNED_PREFIX}"


def clip_ai_prefix(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_RUN_AI_PREFIX}"


def clip_ai_labels_merged_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_AI_LABELS_MERGED_KEY}"


def clip_ai_labels_primary_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_AI_LABELS_PRIMARY_KEY}"


def clip_ai_labels_secondary_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_AI_LABELS_SECONDARY_KEY}"


def clip_ai_consensus_meta_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_AI_CONSENSUS_META_KEY}"


def clip_ai_labels_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_AI_LABELS_KEY}"


def clip_ai_embedding_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_AI_EMBEDDING_KEY}"


def clip_ai_infer_meta_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_AI_INFER_META_KEY}"


def clip_aligned_timeline_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_ALIGNED_TIMELINE_KEY}"


def clip_aligned_sync_manifest_key(clip_id: str, run_id: str) -> str:
    return f"{clip_run_prefix(clip_id, run_id)}{CLIP_ALIGNED_SYNC_MANIFEST_KEY}"


__all__ = [
    "clip_run_prefix",
    "clip_parsed_prefix",
    "clip_aligned_prefix",
    "clip_ai_prefix",
    "clip_ai_labels_key",
    "clip_ai_labels_merged_key",
    "clip_ai_labels_primary_key",
    "clip_ai_labels_secondary_key",
    "clip_ai_consensus_meta_key",
    "clip_ai_embedding_key",
    "clip_ai_infer_meta_key",
    "clip_aligned_timeline_key",
    "clip_aligned_sync_manifest_key",
    "review_labels_key",
    "review_meta_key",
]
