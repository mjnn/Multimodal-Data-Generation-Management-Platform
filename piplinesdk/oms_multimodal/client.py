"""OmsMultimodalClient — SDK 主入口。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv as _load_dotenv

from .acoustic_panel import AcousticPanelConfig, render_acoustic_assets, render_acoustic_panel
from .asr_client import AsrClient, AsrConfig
from .clip_video import ClipVideoConfig, encode_clip_mp4, render_clip_preview_video
from .config import BagProcessResult, ClientConfig, ClipConfig, ModelBackend, OutputConfig, StorageBackend
from .embedding_client import FusionEmbeddingClient
from .exceptions import ConfigurationError
from .omni_client import OmniLabelClient
from .pipeline import LabelEmbeddingPipeline, resolve_bags, write_jsonl
from .rosbag_parser import Clip, RosbagExtractor, TopicInfo, inspect_bag
from .taxonomy import load_taxonomy, parse_label_json, taxonomy_prompt_block


class OmsMultimodalClient:
    """Rosbag 多模态 OMS 打标与融合向量 SDK 客户端。

    典型用法::

        client = OmsMultimodalClient(
            api_key="sk-...",
            workspace_id="ws-...",
            taxonomy_path="oms_label_taxonomy.yaml",
        )
        result = client.process_bag("rosbag/output.bag")
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        workspace_id: str | None = None,
        region: str | None = None,
        taxonomy_path: str | Path | None = None,
        work_dir: str | Path | None = None,
        omni_model: str | None = None,
        embedding_model: str | None = None,
        embedding_dimension: int | None = None,
        acoustic_panel_config: AcousticPanelConfig | None = None,
        asr_config: AsrConfig | None = None,
        clip_video_config: ClipVideoConfig | None = None,
        config: ClientConfig | None = None,
        load_dotenv: bool = True,
        model_backend: ModelBackend | None = None,
        storage_backend: StorageBackend | None = None,
    ):
        if load_dotenv:
            _load_dotenv()

        base = config or ClientConfig.from_env(
            taxonomy_path=Path(taxonomy_path) if taxonomy_path else None,
        )
        self.api_key = api_key or base.api_key
        self.workspace_id = workspace_id or base.workspace_id
        self.region = region or base.region
        self.work_dir = Path(work_dir) if work_dir else base.work_dir
        self.omni_model = omni_model or base.omni_model
        self.embedding_model = embedding_model or base.embedding_model
        self.embedding_dimension = embedding_dimension or base.embedding_dimension
        self.acoustic_panel_config = acoustic_panel_config or base.acoustic_panel_config or AcousticPanelConfig.from_env()
        self.asr_config = asr_config or base.asr_config or AsrConfig.from_env()
        self.clip_video_config = clip_video_config or base.clip_video_config or ClipVideoConfig.from_env()
        self.model_backend: ModelBackend = model_backend or base.model_backend
        self.storage_backend: StorageBackend = storage_backend or base.storage_backend
        self.omni_label_prompt = base.omni_label_prompt
        resolved_taxonomy_path = Path(taxonomy_path) if taxonomy_path else base.taxonomy_path
        if resolved_taxonomy_path is None:
            self.taxonomy_path = None
            self._taxonomy = None
        else:
            self.taxonomy_path = Path(resolved_taxonomy_path)
            self._taxonomy = load_taxonomy(self.taxonomy_path)

        self._pipeline: LabelEmbeddingPipeline | None = None
        self._omni: OmniLabelClient | None = None
        self._embedding: FusionEmbeddingClient | None = None
        self._asr: AsrClient | None = None

    @property
    def taxonomy(self) -> dict[str, Any]:
        if self._taxonomy is None:
            raise ConfigurationError("taxonomy_path is not configured")
        return self._taxonomy

    def _bag_work_dir(self, bag_path: Path) -> Path:
        return self.work_dir / bag_path.stem

    def _get_pipeline(self) -> LabelEmbeddingPipeline:
        if self._pipeline is None:
            if self.taxonomy_path is None:
                raise ConfigurationError("taxonomy_path is required for pipeline operations")
            self._pipeline = LabelEmbeddingPipeline(
                taxonomy_path=self.taxonomy_path,
                work_dir=self.work_dir,
                embedding_client=self._get_embedding_client(),
                omni_client=self._get_omni_client(),
                asr_client=self._get_asr_client(),
                acoustic_panel_config=self.acoustic_panel_config,
                clip_video_config=self.clip_video_config,
            )
        return self._pipeline

    def _get_omni_client(self) -> OmniLabelClient:
        if self.model_backend == "mc":
            raise ConfigurationError(
                "MODEL_BACKEND=mc is not implemented yet; use api until Omni is available in MC modelset"
            )
        if self._omni is None:
            self._omni = OmniLabelClient(
                model=self.omni_model,
                api_key=self.api_key,
                workspace_id=self.workspace_id,
                region=self.region,
                omni_label_prompt=self.omni_label_prompt,
            )
        return self._omni

    def _get_embedding_client(self) -> FusionEmbeddingClient:
        if self._embedding is None:
            self._embedding = FusionEmbeddingClient(
                model=self.embedding_model,
                dimension=self.embedding_dimension,
                api_key=self.api_key,
            )
        return self._embedding

    def _get_asr_client(self) -> AsrClient | None:
        if not self.asr_config.enabled:
            return None
        if self._asr is None:
            self._asr = AsrClient(
                config=self.asr_config,
                api_key=self.api_key,
                workspace_id=self.workspace_id,
            )
        return self._asr

    @staticmethod
    def resolve_bags(manifest_path: str | Path) -> list[Path]:
        """从 manifest.json 解析 bag 路径列表。"""
        return resolve_bags(Path(manifest_path))

    def inspect_bag(self, bag_path: str | Path) -> list[TopicInfo]:
        """查看 bag 内 topic 列表与 modality。"""
        return inspect_bag(Path(bag_path))

    def iter_clips(
        self,
        bag_path: str | Path,
        *,
        clip_config: ClipConfig | None = None,
    ) -> Iterator[Clip]:
        """迭代解析 bag 中的多模态 Clip（含声学面板）。"""
        bag_path = Path(bag_path)
        cfg = clip_config or ClipConfig()
        extractor = RosbagExtractor(bag_path, self._bag_work_dir(bag_path))
        yield from extractor.iter_clips(
            clip_min_sec=cfg.min_sec,
            clip_max_sec=cfg.max_sec,
            sample_fps=cfg.sample_fps,
            max_clips=cfg.max_clips,
            acoustic_panel_config=self.acoustic_panel_config,
            clip_video_config=self.clip_video_config,
        )

    def transcribe_clip(self, clip: Clip) -> dict[str, Any]:
        """对 clip 音频做 ASR，并写入 clip.asr_text。"""
        client = self._get_asr_client()
        if client is None:
            return {"skipped": True, "reason": "asr_disabled", "text": ""}
        return client.transcribe_clip(clip)

    def label_clip(
        self,
        clip: Clip,
        *,
        taxonomy: dict[str, Any] | None = None,
        run_asr: bool = True,
    ) -> dict[str, Any]:
        """对单个 clip 调用 Qwen-Omni 打标（可选先跑 ASR）。"""
        tax = taxonomy or self.taxonomy
        asr_meta = None
        if run_asr:
            asr_meta = self.transcribe_clip(clip)
        label_row = self._get_omni_client().label_clip(clip, tax)
        if asr_meta is not None and not asr_meta.get("skipped"):
            label_row["asr"] = asr_meta
        return label_row

    def embed_clip(self, clip: Clip, *, extra_text: str = "") -> dict[str, Any]:
        """对单个 clip 生成 fusion embedding。"""
        return self._get_embedding_client().embed_clip(clip, extra_text=extra_text)

    def process_clip(self, clip: Clip, *, run_asr: bool = True) -> tuple[dict[str, Any], dict[str, Any]]:
        """对单个 clip 依次 ASR（可选）→ 打标 → embedding。"""
        label_row = self.label_clip(clip, run_asr=run_asr)
        embedding_row = self.embed_clip(clip, extra_text=label_row.get("scene_summary", ""))
        return label_row, embedding_row

    def extract_bag(
        self,
        bag_path: str | Path,
        *,
        clip_config: ClipConfig | None = None,
        output: OutputConfig | None = None,
    ) -> BagProcessResult:
        """仅本地提取 clip，不调用云端模型。"""
        bag_path = Path(bag_path)
        cfg = clip_config or ClipConfig()
        out = output or OutputConfig()
        pipeline = self._get_pipeline()
        summary = pipeline.extract_bag(
            bag_path,
            clips_out=out.clips_out,
            videos_out=out.videos_out,
            clip_min_sec=cfg.min_sec,
            clip_max_sec=cfg.max_sec,
            sample_fps=cfg.sample_fps,
            max_clips=cfg.max_clips,
        )
        return BagProcessResult(
            bag=summary["bag"],
            topics=summary["topics"],
            clips_out=summary["clips_out"],
            videos_out=summary.get("videos_out"),
            clip_rows=summary["clip_rows"],
            video_rows=summary.get("video_rows", 0),
        )

    def process_bag(
        self,
        bag_path: str | Path,
        *,
        clip_config: ClipConfig | None = None,
        output: OutputConfig | None = None,
    ) -> BagProcessResult:
        """完整处理 bag：Omni 打标 + fusion embedding。"""
        bag_path = Path(bag_path)
        cfg = clip_config or ClipConfig()
        out = output or OutputConfig()
        pipeline = self._get_pipeline()
        summary = pipeline.process_bag(
            bag_path,
            embeddings_out=out.embeddings_out,
            labels_out=out.labels_out,
            videos_out=out.videos_out,
            clip_min_sec=cfg.min_sec,
            clip_max_sec=cfg.max_sec,
            sample_fps=cfg.sample_fps,
            max_clips=cfg.max_clips,
        )
        return BagProcessResult(
            bag=summary["bag"],
            topics=summary["topics"],
            embeddings_out=summary["embeddings_out"],
            labels_out=summary["labels_out"],
            videos_out=summary.get("videos_out"),
            embedding_rows=summary["embedding_rows"],
            label_rows=summary["label_rows"],
            video_rows=summary.get("video_rows", 0),
            errors=summary["errors"],
        )

    def publish_run_storage(
        self,
        run_dir: Path,
        *,
        clip_id: str,
        run_id: str,
    ) -> str | None:
        """After process_bag, mirror or upload artifacts per storage_backend."""
        from .storage_backend import (
            mirror_outputs_to_local_runtime,
            upload_run_dir_to_oss,
        )

        run_dir = Path(run_dir)
        if self.storage_backend == "local":
            dest = mirror_outputs_to_local_runtime(run_dir=run_dir, clip_id=clip_id, run_id=run_id)
            return str(dest)
        return upload_run_dir_to_oss(run_dir, clip_id=clip_id, run_id=run_id)

    def render_acoustic_panel(
        self,
        wav_path: str | Path,
        output_path: str | Path,
        *,
        config: AcousticPanelConfig | None = None,
    ) -> str:
        """将 WAV 渲染为声学面板 PNG。"""
        return render_acoustic_panel(
            wav_path,
            output_path,
            config=config or self.acoustic_panel_config,
        )

    def render_acoustic_assets(
        self,
        wav_path: str | Path,
        output_dir: str | Path,
        *,
        config: AcousticPanelConfig | None = None,
    ) -> dict[str, Any]:
        """渲染声学面板 PNG，并导出 Mel 矩阵 csv/文本特征。"""
        return render_acoustic_assets(
            wav_path,
            output_dir,
            config=config or self.acoustic_panel_config,
        )
