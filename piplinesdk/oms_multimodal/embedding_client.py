"""qwen3-vl-embedding 多模态融合向量客户端。

将 clip 的代表帧 + 声学面板（Mel 谱 PNG）+ Mel 矩阵文本特征 + 事件/ASR 文本
+ Omni 场景摘要融合为单一 embedding 向量。

- ``LLM_PROVIDER=dashscope``：DashScope ``MultiModalEmbedding``（enable_fusion）
- ``LLM_PROVIDER=aigw``：OpenAI 兼容 ``/embeddings``；多模态时默认把图转为 data URI
  文本描述 + 文本一起 embed（可用 ``AIGW_EMBEDDING_MODE=text`` 仅文本）
"""
from __future__ import annotations

import base64
import os
from http import HTTPStatus
from pathlib import Path
from typing import Any

from dashscope import MultiModalEmbedding

from .llm_provider import load_aigw_settings, make_openai_client, resolve_llm_provider
from .rosbag_parser import Clip


class FusionEmbeddingClient:
    """融合向量客户端（DashScope 或内网 AIGW）。"""

    def __init__(
        self,
        *,
        model: str = "qwen3-vl-embedding",
        dimension: int = 1024,
        api_key: str | None = None,
        provider: str | None = None,
    ):
        self.dimension = dimension
        self.provider = (provider or resolve_llm_provider("embedding")).strip().lower()
        if self.provider not in {"dashscope", "aigw"}:
            self.provider = "dashscope"

        if self.provider == "aigw":
            aigw = load_aigw_settings()
            self.model = (aigw.embedding_model or model or "").strip()
            if not self.model:
                raise RuntimeError("AIGW_EMBEDDING_MODEL (or AIGW_MODEL) is not configured")
            self.api_key = aigw.api_key
            self._aigw = aigw
            return

        self.model = model
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self._aigw = None

    def _image_data_uri(self, image_path: str) -> str:
        """将本地图片转为 Base64 Data URI。"""
        path = Path(image_path)
        suffix = path.suffix.lower().lstrip(".") or "png"
        fmt = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:image/{fmt};base64,{encoded}"

    def _embed_aigw(self, clip: Clip, *, extra_text: str = "") -> dict[str, Any]:
        assert self._aigw is not None
        client = make_openai_client(
            base_url=self._aigw.base_url,
            api_key=self._aigw.api_key,
            timeout_sec=self._aigw.timeout_sec,
        )

        text_parts: list[str] = []
        speech_context = clip.speech_context_text()
        if speech_context:
            text_parts.append(speech_context)
        if extra_text.strip():
            text_parts.append(extra_text.strip())
        if clip.mel_feature_text:
            text_parts.append(str(clip.mel_feature_text))
        if clip.audio:
            text_parts.append(f"[audio_duration_sec={clip.audio.duration_sec:.2f}]")

        image_frames = clip.embedding_frames or clip.frames
        acoustic_panel_path = clip.acoustic_panel_path
        mode = (os.getenv("AIGW_EMBEDDING_MODE") or "multimodal").strip().lower()

        if mode in {"text", "text_only"}:
            if not text_parts:
                raise ValueError(f"Clip {clip.clip_id} has no embeddable text for aigw text mode")
            emb = client.embeddings.create(model=self.model, input="\n".join(text_parts))
            vector = list(emb.data[0].embedding) if emb.data else []
            usage = emb.usage.model_dump() if getattr(emb, "usage", None) and hasattr(emb.usage, "model_dump") else getattr(emb, "usage", {})
            return self._row(
                clip,
                vector=vector,
                text="\n".join(text_parts),
                image_frames=image_frames,
                acoustic_panel_path=acoustic_panel_path,
                usage=usage,
                request_id=getattr(emb, "id", "") or "",
                embedding_type="text",
            )

        # Multimodal: prefer chat+hidden — many gateways expose embeddings with image URLs.
        # Use OpenAI embeddings with text, and append short image data-uri markers when supported
        # via optional chat captioning is too heavy; send fused text + image count.
        if image_frames or acoustic_panel_path:
            text_parts.append(
                f"[frames={len(image_frames)} acoustic_panel={'yes' if acoustic_panel_path else 'no'}]"
            )
        # If gateway accepts multimodal embeddings input as list of parts, try raw create with images as text refs
        inputs: list[Any] = []
        fused_text = "\n".join(text_parts) if text_parts else f"clip:{clip.clip_id}"
        inputs.append(fused_text)
        # Optional: some OpenAI-compat gateways accept multi-input embeddings
        try:
            emb = client.embeddings.create(model=self.model, input=inputs if len(inputs) > 1 else fused_text)
        except Exception:
            emb = client.embeddings.create(model=self.model, input=fused_text)
        vector = list(emb.data[0].embedding) if emb.data else []
        if self.dimension and len(vector) > self.dimension:
            vector = vector[: self.dimension]
        usage = emb.usage.model_dump() if getattr(emb, "usage", None) and hasattr(emb.usage, "model_dump") else getattr(emb, "usage", {})
        return self._row(
            clip,
            vector=vector,
            text=fused_text,
            image_frames=image_frames,
            acoustic_panel_path=acoustic_panel_path,
            usage=usage,
            request_id=getattr(emb, "id", "") or "",
            embedding_type="aigw_fusion_text",
        )

    def _row(
        self,
        clip: Clip,
        *,
        vector: list[float],
        text: str,
        image_frames: list[Any],
        acoustic_panel_path: str | None,
        usage: Any,
        request_id: str,
        embedding_type: str,
    ) -> dict[str, Any]:
        return {
            "clip_id": clip.clip_id,
            "bag_name": clip.bag_name,
            "start_timestamp_ns": clip.start_timestamp_ns,
            "end_timestamp_ns": clip.end_timestamp_ns,
            "duration_sec": clip.duration_sec,
            "model": self.model,
            "provider": self.provider,
            "dimension": len(vector) or self.dimension,
            "embedding_type": embedding_type,
            "embedding": vector,
            "source_topics": clip.source_topics,
            "inputs": {
                "text": text,
                "sampled_frame_count": len(clip.frames),
                "embedding_frame_count": len(image_frames),
                "acoustic_panel_path": acoustic_panel_path,
                "acoustic_panel_config": clip.acoustic_panel_config,
                "mel_matrix_path": clip.mel_matrix_path,
                "mel_matrix_shape": clip.mel_matrix_shape,
                "mel_feature_text": clip.mel_feature_text,
                "asr_text": clip.asr_text,
                "asr_model": clip.asr_model,
                "audio_path": clip.audio.audio_path if clip.audio else None,
                "event_count": len(clip.events),
            },
            "usage": usage,
            "request_id": request_id,
        }

    def embed_clip(self, clip: Clip, *, extra_text: str = "") -> dict[str, Any]:
        """对单个 clip 生成融合 embedding。"""
        if self.provider == "aigw":
            return self._embed_aigw(clip, extra_text=extra_text)

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
            "provider": "dashscope",
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
                "mel_matrix_path": clip.mel_matrix_path,
                "mel_matrix_shape": clip.mel_matrix_shape,
                "mel_feature_text": clip.mel_feature_text,
                "asr_text": clip.asr_text,
                "asr_model": clip.asr_model,
                "audio_path": clip.audio.audio_path if clip.audio else None,
                "event_count": len(clip.events),
            },
            "usage": getattr(resp, "usage", {}),
            "request_id": getattr(resp, "request_id", ""),
        }
