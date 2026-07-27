"""Canonical OSS prefix layout — SDK pipeline (sdk_v1).

SDK writes under clips/.../runs/{run_id}/: jsonl bundle + preview/.
Human-reviewed labels live under reviews/ (never mixed with SDK jsonl).
"""

from __future__ import annotations

SDK_LAYOUT_VERSION = "sdk_v1"

OSS_LAYOUT_PREFIXES: tuple[dict[str, str], ...] = (
    {
        "prefix": "rosbags/",
        "label": "Rosbags 入库",
        "hint": "原始 .bag；discover 扫描",
    },
    {
        "prefix": "clips/",
        "label": "SDK Clip 产物",
        "hint": "clips/{clip_id}/runs/{run_id}/ · labels.jsonl + preview/",
    },
    {
        "prefix": "reviews/",
        "label": "人工校核标签",
        "hint": "reviews/clips/{clip_id}/runs/{run_id}/ · 仅 HMI 写入",
    },
    {
        "prefix": "datasets/",
        "label": "训练数据集",
        "hint": "datasets/{snapshot_id}/…",
    },
    {
        "prefix": "config/taxonomy/",
        "label": "标签树",
        "hint": "published taxonomy YAML + latest.json",
    },
    {
        "prefix": "pipeline/dispatch/",
        "label": "管线调度",
        "hint": "latest.json · dispatch + HMI 自动同步轮询",
    },
    {
        "prefix": "legacy/",
        "label": "旧版 clip-omni v2",
        "hint": "parsed/ aligned/ ai/ 归档，勿作新写入目标",
    },
)

OSS_LAYOUT_MARKERS: tuple[tuple[str, str], ...] = (
    ("rosbags/.keep", "Rosbag upload root\n"),
    ("clips/.keep", "SDK clip runs (jsonl + preview)\n"),
    (
        "clips/_layout/README.txt",
        "SDK layout (sdk_v1)\n"
        "  clips/{clip_id}/runs/{run_id}/run.json\n"
        "  clips/{clip_id}/runs/{run_id}/labels.jsonl\n"
        "  clips/{clip_id}/runs/{run_id}/fusion_embeddings.jsonl\n"
        "  clips/{clip_id}/runs/{run_id}/clip_videos.jsonl\n"
        "  clips/{clip_id}/runs/{run_id}/preview/manifest.json\n"
        "  clips/{clip_id}/runs/{run_id}/preview/clip_preview_camera*.mp4\n"
        "  clips/{clip_id}/runs/{run_id}/preview/audio.wav\n"
        "Human labels: reviews/clips/{clip_id}/runs/{run_id}/labels.json\n",
    ),
    (
        "reviews/.keep",
        "Human-reviewed labels only (HMI export on save).\n",
    ),
    ("datasets/.keep", "Dataset export snapshots\n"),
    ("config/taxonomy/.keep", "Label taxonomy YAML exports\n"),
    ("pipeline/dispatch/.keep", "Dispatch manifest directory\n"),
    (
        "legacy/README.txt",
        "Deprecated clip-omni v2 parsed/aligned/ai layout.\n",
    ),
)

SDK_RUN_JSON_KEY = "run.json"
SDK_LABELS_JSONL = "labels.jsonl"
SDK_EMBEDDINGS_JSONL = "fusion_embeddings.jsonl"
SDK_VIDEOS_JSONL = "clip_videos.jsonl"

CLIP_RUN_PREVIEW_PREFIX = "preview/"
CLIP_PREVIEW_MANIFEST_KEY = "preview/manifest.json"
CLIP_PREVIEW_GRID_KEY = "preview/grid.mp4"
CLIP_PREVIEW_AUDIO_KEY = "preview/audio.wav"

# Deprecated v2 keys (legacy/ only)
CLIP_RUN_PARSED_PREFIX = "parsed/"
CLIP_RUN_ALIGNED_PREFIX = "aligned/"
CLIP_RUN_AI_PREFIX = "ai/"
CLIP_AI_LABELS_KEY = "ai/labels.json"
CLIP_AI_LABELS_PRIMARY_KEY = "ai/labels_primary.json"
CLIP_AI_LABELS_SECONDARY_KEY = "ai/labels_secondary.json"
CLIP_AI_LABELS_MERGED_KEY = "ai/labels_merged.json"
CLIP_AI_CONSENSUS_META_KEY = "ai/consensus_meta.json"
CLIP_AI_EMBEDDING_KEY = "ai/embedding.json"
CLIP_AI_INFER_META_KEY = "ai/infer_meta.json"
CLIP_ALIGNED_TIMELINE_KEY = "aligned/timeline.json"
CLIP_ALIGNED_SYNC_MANIFEST_KEY = "aligned/sync_manifest.json"
CLIP_PARSED_PREVIEW_MANIFEST_KEY = "parsed/preview/manifest.json"
CLIP_PARSED_PREVIEW_GRID_KEY = "parsed/preview/grid.mp4"

# Human review export (top-level, separate from clips/.../ai/).
def review_labels_key(clip_id: str, run_id: str) -> str:
    safe = clip_id.replace(":", "__")
    return f"reviews/clips/{safe}/runs/{run_id}/labels.json"


def review_meta_key(clip_id: str, run_id: str) -> str:
    safe = clip_id.replace(":", "__")
    return f"reviews/clips/{safe}/runs/{run_id}/meta.json"
