"""Rosbag 多模态打标与融合向量流水线编排。

串联 rosbag 解析 → ASR → Qwen-Omni 打标 → qwen3-vl-embedding 融合向量，
输出 fusion_embeddings.jsonl 与 labels.jsonl。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv

from .acoustic_panel import AcousticPanelConfig
from .asr_client import AsrClient, AsrConfig
from .clip_video import ClipVideoConfig
from .config import BagProcessResult, ClientConfig, ClipConfig, OutputConfig
from .embedding_client import FusionEmbeddingClient
from .omni_client import OmniLabelClient
from .rosbag_parser import RosbagExtractor, inspect_bag
from .taxonomy import load_taxonomy


def write_jsonl(path: Path, rows: Iterator[dict[str, Any]]) -> int:
    """将 dict 迭代器写入 JSONL 文件，返回写入行数。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            count += 1
    return count


def _clip_video_row(clip) -> dict[str, Any]:
    return {
        "clip_id": clip.clip_id,
        "bag_name": clip.bag_name,
        "duration_sec": clip.duration_sec,
        "frame_count": len(clip.frames),
        "video_frame_count": len(clip.video_frames),
        "clip_video_path": clip.clip_video_path,
        "clip_video_paths": clip.clip_video_paths,
        "audio_path": clip.audio.audio_path if clip.audio else None,
        "clip_video_config": clip.clip_video_config,
    }


class LabelEmbeddingPipeline:
    """端到端流水线：bag → clip → 打标 + embedding → JSONL。"""

    def __init__(
        self,
        *,
        taxonomy_path: Path,
        work_dir: Path,
        embedding_client: FusionEmbeddingClient | None = None,
        omni_client: OmniLabelClient | None = None,
        asr_client: AsrClient | None = None,
        acoustic_panel_config: AcousticPanelConfig | None = None,
        clip_video_config: ClipVideoConfig | None = None,
    ):
        self.taxonomy_path = taxonomy_path
        self.work_dir = work_dir
        self.taxonomy = load_taxonomy(taxonomy_path)
        load_dotenv()
        self.acoustic_panel_config = acoustic_panel_config or AcousticPanelConfig.from_env()
        self.clip_video_config = clip_video_config or ClipVideoConfig.from_env()
        self.embedding_client = embedding_client or FusionEmbeddingClient(
            model=os.getenv("EMBEDDING_MODEL", "qwen3-vl-embedding"),
            dimension=int(os.getenv("EMBEDDING_DIMENSION", "1024")),
        )
        self.omni_client = omni_client
        self.asr_client = asr_client

    def _get_asr_client(self) -> AsrClient | None:
        if self.asr_client is not None:
            return self.asr_client if self.asr_client.config.enabled else None
        config = AsrConfig.from_env()
        if not config.enabled:
            return None
        self.asr_client = AsrClient(
            config=config,
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            workspace_id=os.getenv("DASHSCOPE_WORKSPACE_ID"),
        )
        return self.asr_client

    def _run_asr(self, clip) -> dict[str, Any] | None:
        client = self._get_asr_client()
        if client is None:
            return None
        return client.transcribe_clip(clip)

    def _get_omni_client(self) -> OmniLabelClient:
        if self.omni_client is None:
            self.omni_client = OmniLabelClient(model=os.getenv("OMNI_MODEL", "qwen3.5-omni-plus"))
        return self.omni_client

    def extract_bag(
        self,
        bag_path: Path,
        *,
        clips_out: Path,
        videos_out: Path | None = None,
        clip_min_sec: float = 15.0,
        clip_max_sec: float = 20.0,
        sample_fps: float = 1.0,
        max_clips: int | None = None,
    ) -> dict[str, Any]:
        """仅提取 clip 元数据，不调用云端模型（--extract-only）。"""
        extractor = RosbagExtractor(bag_path, self.work_dir / bag_path.stem)
        topics = extractor.topics()
        clips: list = list(
            extractor.iter_clips(
                clip_min_sec=clip_min_sec,
                clip_max_sec=clip_max_sec,
                sample_fps=sample_fps,
                max_clips=max_clips,
                acoustic_panel_config=self.acoustic_panel_config,
                clip_video_config=self.clip_video_config,
            )
        )
        count = write_jsonl(clips_out, (clip.to_meta() for clip in clips))
        videos_path = videos_out or OutputConfig().videos_out
        video_count = write_jsonl(videos_path, (_clip_video_row(clip) for clip in clips))
        return {
            "bag": str(bag_path),
            "topics": [t.__dict__ for t in topics],
            "clips_out": str(clips_out),
            "videos_out": str(videos_path),
            "clip_rows": count,
            "video_rows": video_count,
        }

    def process_bag(
        self,
        bag_path: Path,
        *,
        embeddings_out: Path,
        labels_out: Path,
        videos_out: Path | None = None,
        clip_min_sec: float = 15.0,
        clip_max_sec: float = 20.0,
        sample_fps: float = 1.0,
        max_clips: int | None = None,
    ) -> dict[str, Any]:
        """完整处理：每个 clip 先 Omni 打标，再 fusion embedding。单 clip 失败不中断。"""
        extractor = RosbagExtractor(bag_path, self.work_dir / bag_path.stem)
        topics = extractor.topics()
        omni_client = self._get_omni_client()

        embedding_rows: list[dict[str, Any]] = []
        label_rows: list[dict[str, Any]] = []
        video_rows: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []

        for clip in extractor.iter_clips(
            clip_min_sec=clip_min_sec,
            clip_max_sec=clip_max_sec,
            sample_fps=sample_fps,
            max_clips=max_clips,
            acoustic_panel_config=self.acoustic_panel_config,
            clip_video_config=self.clip_video_config,
        ):
            video_rows.append(_clip_video_row(clip))
            try:
                asr_meta = self._run_asr(clip)
                label_row = omni_client.label_clip(clip, self.taxonomy)
                if asr_meta is not None:
                    label_row["asr"] = asr_meta
                if clip.clip_video_path:
                    label_row["clip_video_path"] = clip.clip_video_path
                label_rows.append(label_row)

                extra_text = label_row.get("scene_summary", "")
                embedding_row = self.embedding_client.embed_clip(clip, extra_text=extra_text)
                if clip.clip_video_path:
                    embedding_row.setdefault("inputs", {})["clip_video_path"] = clip.clip_video_path
                embedding_rows.append(embedding_row)
            except Exception as exc:  # noqa: BLE001 - collect and continue
                errors.append({"clip_id": clip.clip_id, "error": str(exc)})

        emb_count = write_jsonl(embeddings_out, iter(embedding_rows))
        label_count = write_jsonl(labels_out, iter(label_rows))
        videos_path = videos_out or OutputConfig().videos_out
        video_count = write_jsonl(videos_path, iter(video_rows))

        return {
            "bag": str(bag_path),
            "topics": [t.__dict__ for t in topics],
            "embeddings_out": str(embeddings_out),
            "labels_out": str(labels_out),
            "videos_out": str(videos_path),
            "embedding_rows": emb_count,
            "label_rows": label_count,
            "video_rows": video_count,
            "errors": errors,
        }


def resolve_bags(manifest_path: Path) -> list[Path]:
    """从 manifest.json 和 rosbag/ 目录解析可用的 .bag 文件路径。"""
    bags: list[Path] = []
    seen: set[str] = set()

    def add(path: Path) -> None:
        key = str(path.resolve()) if path.exists() else str(path)
        if path.exists() and key not in seen:
            seen.add(key)
            bags.append(path)

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest_dir = manifest_path.parent
        for item in manifest.get("bags", []):
            raw = Path(item["path"])
            add(raw)
            if not raw.exists():
                add(manifest_dir / raw.name)

    for candidate in sorted(manifest_path.parent.glob("*.bag")):
        add(candidate)

    return bags
