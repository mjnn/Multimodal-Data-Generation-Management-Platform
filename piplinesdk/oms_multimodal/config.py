"""SDK 配置 dataclass。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .acoustic_panel import AcousticPanelConfig
from .asr_client import AsrConfig
from .clip_video import ClipVideoConfig

if TYPE_CHECKING:
    from .mc.config import McBackendConfig

ModelBackend = Literal["api", "mc"]
StorageBackend = Literal["local", "cloud"]


@dataclass
class ClientConfig:
    """SDK 客户端全局配置。"""

    api_key: str | None = None
    workspace_id: str | None = None
    region: str = "cn-beijing"
    taxonomy_path: Path | None = None
    work_dir: Path = field(default_factory=lambda: Path("output/work"))
    omni_model: str = "qwen3.5-omni-plus"
    embedding_model: str = "qwen3-vl-embedding"
    embedding_dimension: int = 1024
    omni_label_prompt: dict[str, Any] | None = None
    acoustic_panel_config: AcousticPanelConfig | None = None
    asr_config: AsrConfig | None = None
    clip_video_config: ClipVideoConfig | None = None
    load_dotenv: bool = True
    # api: DashScope / MaaS 直连；mc: MaxCompute MaxFrame AI / 模型集
    model_backend: ModelBackend = "api"
    mc_odps_entry: Any | None = None
    mc_config: McBackendConfig | None = None
    # local: 写入 HMI_RUNTIME_ROOT/oss 镜像；cloud: 处理后上传 OSS
    storage_backend: StorageBackend = "local"

    @classmethod
    def from_env(cls, *, taxonomy_path: Path | None = None) -> ClientConfig:
        backend_raw = os.getenv("MODEL_BACKEND", "api").strip().lower()
        model_backend: ModelBackend = "mc" if backend_raw == "mc" else "api"
        storage_raw = os.getenv("STORAGE_BACKEND", "local").strip().lower()
        storage_backend: StorageBackend = "cloud" if storage_raw == "cloud" else "local"
        return cls(
            api_key=os.getenv("DASHSCOPE_API_KEY") or None,
            workspace_id=os.getenv("DASHSCOPE_WORKSPACE_ID") or None,
            region=os.getenv("DASHSCOPE_REGION", "cn-beijing"),
            taxonomy_path=taxonomy_path,
            omni_model=os.getenv("OMNI_MODEL", "qwen3.5-omni-plus"),
            embedding_model=os.getenv("EMBEDDING_MODEL", "qwen3-vl-embedding"),
            embedding_dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
            acoustic_panel_config=AcousticPanelConfig.from_env(),
            asr_config=AsrConfig.from_env(),
            clip_video_config=ClipVideoConfig.from_env(),
            model_backend=model_backend,
            storage_backend=storage_backend,
        )


@dataclass
class ClipConfig:
    """Clip 切分与采样参数。"""

    min_sec: float = 15.0
    max_sec: float = 20.0
    sample_fps: float = 1.0
    max_clips: int | None = None


@dataclass
class OutputConfig:
    """流水线输出路径。"""

    embeddings_out: Path = field(default_factory=lambda: Path("output/fusion_embeddings.jsonl"))
    labels_out: Path = field(default_factory=lambda: Path("output/labels.jsonl"))
    clips_out: Path = field(default_factory=lambda: Path("output/clips.jsonl"))
    videos_out: Path = field(default_factory=lambda: Path("output/clip_videos.jsonl"))


@dataclass
class BagProcessResult:
    """单 bag 处理结果摘要。"""

    bag: str
    topics: list[dict[str, Any]]
    embeddings_out: str | None = None
    labels_out: str | None = None
    clips_out: str | None = None
    videos_out: str | None = None
    embedding_rows: int = 0
    label_rows: int = 0
    clip_rows: int = 0
    video_rows: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bag": self.bag,
            "topics": self.topics,
            "embeddings_out": self.embeddings_out,
            "labels_out": self.labels_out,
            "clips_out": self.clips_out,
            "videos_out": self.videos_out,
            "embedding_rows": self.embedding_rows,
            "label_rows": self.label_rows,
            "clip_rows": self.clip_rows,
            "video_rows": self.video_rows,
            "errors": self.errors,
        }
