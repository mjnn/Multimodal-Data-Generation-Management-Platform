"""qwen3-vl-embedding 多模态融合向量客户端。

将 clip 的代表帧 + 声学面板（log 频谱图）+ 事件文本 + Omni 场景摘要
融合为单一 embedding 向量。

注意：DashScope embedding API 不支持原始 audio 输入；
clip 音频先渲染为声学面板 PNG，再作为 image 输入参与 fusion。
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from dashscope import MultiModalEmbedding
from http import HTTPStatus

from .rosbag_parser import Clip


class FusionEmbeddingClient:
    """调用 qwen3-vl-embedding 生成 enable_fusion=True 的融合向量。"""

    def __init__(
        self,
        *,
        model: str = "qwen3-vl-embedding",
        dimension: int = 1024,
        api_key: str | None = None,
    ):
        self.model = model
        self.dimension = dimension
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")

    def _image_data_uri(self, image_path: str) -> str:
        """将本地图片转为 Base64 Data URI。"""
        path = Path(image_path)
        suffix = path.suffix.lower().lstrip(".") or "png"
        fmt = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:image/{fmt};base64,{encoded}"

    def embed_clip(self, clip: Clip, *, extra_text: str = "") -> dict[str, Any]:
        """对单个 clip 生成融合 embedding。

        Args:
            clip: 含 embedding_frames（≤4 代表帧）、事件文本、音频元信息。
            extra_text: 通常为 Omni 返回的 scene_summary，增强语义。

        Returns:
            可写入 fusion_embeddings.jsonl 的一行 dict。
        """
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")

        text_parts = []
        speech_context = clip.speech_context_text()
        if speech_context:
            text_parts.append(speech_context)
        if extra_text.strip():
            text_parts.append(extra_text.strip())
        if clip.audio:
            text_parts.append(f"[audio_duration_sec={clip.audio.duration_sec:.2f}]")

        image_frames = clip.embedding_frames or clip.frames
        acoustic_panel_path = clip.acoustic_panel_path
        if not text_parts and not image_frames and not acoustic_panel_path:
            raise ValueError(f"Clip {clip.clip_id} has no embeddable content")

        input_data: list[dict[str, Any]] = []
        if text_parts:
            input_data.append({"text": "\n".join(text_parts)})
        for frame in image_frames:
            input_data.append({"image": self._image_data_uri(frame.image_path)})
        if acoustic_panel_path:
            input_data.append({"image": self._image_data_uri(acoustic_panel_path)})

        resp = MultiModalEmbedding.call(
            api_key=self.api_key,
            model=self.model,
            input=input_data,
            enable_fusion=True,
            dimension=self.dimension,
        )
        if resp.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"Embedding failed: status={resp.status_code}, code={getattr(resp, 'code', '')}, "
                f"message={getattr(resp, 'message', '')}"
            )

        embeddings = resp.output.get("embeddings", [])
        if not embeddings:
            raise RuntimeError("Embedding response missing embeddings")

        primary = embeddings[0]
        return {
            "clip_id": clip.clip_id,
            "bag_name": clip.bag_name,
            "start_timestamp_ns": clip.start_timestamp_ns,
            "end_timestamp_ns": clip.end_timestamp_ns,
            "duration_sec": clip.duration_sec,
            "model": self.model,
            "dimension": self.dimension,
            "embedding_type": primary.get("type", "fusion"),
            "embedding": primary.get("embedding", []),
            "source_topics": clip.source_topics,
            "inputs": {
                "text": "\n".join(text_parts),
                "sampled_frame_count": len(clip.frames),
                "embedding_frame_count": len(image_frames),
                "acoustic_panel_path": acoustic_panel_path,
                "acoustic_panel_config": clip.acoustic_panel_config,
                "asr_text": clip.asr_text,
                "asr_model": clip.asr_model,
                "audio_path": clip.audio.audio_path if clip.audio else None,
                "event_count": len(clip.events),
            },
            "usage": getattr(resp, "usage", {}),
            "request_id": getattr(resp, "request_id", ""),
        }
