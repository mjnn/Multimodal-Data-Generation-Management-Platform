"""多节点管线共享类型：RunContext + 各 capability 结果。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

MediaInputMode = Literal["local", "oss", "auto"]

# DataWorks step_id → SDK 原子能力（多节点编排时一节点一能力）
CAPABILITY_IDS = (
    "extract",      # sdk_extract — 解析 bag，无 AI
    "transcribe",   # sdk_asr
    "label",        # sdk_label
    "embed",        # sdk_embed
    "preview",      # sdk_preview — 整理 preview/ 目录
)

STEP_TO_CAPABILITY: dict[str, str] = {
    "sdk_extract": "extract",
    "sdk_discover": "extract",  # discover 可只做登记；extract 含解析
    "sdk_asr": "transcribe",
    "sdk_label": "label",
    "sdk_embed": "embed",
    "sdk_preview": "preview",
    "sdk_infer": "infer_full",  # 复合：extract→asr→label→embed→preview（单节点便利）
}


@dataclass
class RunContext:
    """一次 SDK run 的目录与媒体引用方式（跨节点 handoff）。"""

    run_dir: Path
    work_dir: Path | None = None
    clip_id: str = ""
    run_id: str = ""
    # local：读写 run_dir/_sdk_work 下路径；oss：AI 读 oss://…/clips/…/runs/…/
    media_mode: MediaInputMode = "auto"
    oss_bucket: str = ""
    oss_run_prefix: str = ""
    cloud_region: str = "cn-shanghai"

    def __post_init__(self) -> None:
        self.run_dir = Path(self.run_dir)
        if self.work_dir is None:
            self.work_dir = self.run_dir / "_sdk_work"

    def resolved_media_mode(self) -> Literal["local", "oss"]:
        if self.media_mode == "local":
            return "local"
        if self.media_mode == "oss":
            return "oss"
        # auto：已 upload、有 run 前缀 → oss；否则 local（extract/asr 在 upload 前）
        if self.oss_run_prefix.strip() and self.oss_bucket.strip():
            return "oss"
        return "local"

    @property
    def clips_index_path(self) -> Path:
        return self.run_dir / "clips_index.jsonl"

    @property
    def asr_path(self) -> Path:
        return self.run_dir / "asr.jsonl"

    @property
    def labels_path(self) -> Path:
        return self.run_dir / "labels.jsonl"

    @property
    def embeddings_path(self) -> Path:
        return self.run_dir / "fusion_embeddings.jsonl"

    @property
    def videos_path(self) -> Path:
        return self.run_dir / "clip_videos.jsonl"


@dataclass
class ExtractResult:
    clips_index: Path
    videos_out: Path
    clip_rows: int
    video_rows: int
    bag: str
    topics: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class TranscribeResult:
    asr_out: Path
    row_count: int
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class LabelResult:
    labels_out: Path
    row_count: int
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class EmbedResult:
    embeddings_out: Path
    row_count: int
    errors: list[dict[str, str]] = field(default_factory=list)


@dataclass
class InferFullResult:
    """复合 sdk_infer 等价结果。"""
    extract: ExtractResult
    labels_out: Path
    embeddings_out: Path
    label_rows: int
    embedding_rows: int
    errors: list[dict[str, str]] = field(default_factory=list)
