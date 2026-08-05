"""MaxFrame AI 融合向量客户端（bigdata_modelset）。"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pandas as pd

from ..exceptions import ConfigurationError
from ..rosbag_parser import Clip
from .config import McBackendConfig
from .runtime import (
    McRuntime,
    _fetch_series,
    create_ai_model,
    require_maxframe,
    running_options_for,
)


def _image_b64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def _normalize_embedding_vector(vector_raw: Any) -> list[float]:
    """Normalize MaxFrame embed output to a flat float vector.

    Without ``enable_fusion``, multimodal embed returns ``[[...], ...]`` (one
    vector per modality). With fusion it returns a single ``[...]``.
    """
    if isinstance(vector_raw, str):
        import json

        try:
            vector_raw = json.loads(vector_raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(vector_raw, list) or not vector_raw:
        return []
    # Nested batch / per-modality vectors → take first (fusion should already be flat)
    while (
        isinstance(vector_raw, list)
        and vector_raw
        and isinstance(vector_raw[0], (list, tuple))
    ):
        if len(vector_raw) == 1:
            vector_raw = list(vector_raw[0])
            continue
        # Multiple modality vectors without fusion: mean-pool
        dim = len(vector_raw[0])
        if dim <= 0 or any(not isinstance(v, (list, tuple)) or len(v) != dim for v in vector_raw):
            vector_raw = list(vector_raw[0])
            break
        n = float(len(vector_raw))
        vector_raw = [sum(float(v[i]) for v in vector_raw) / n for i in range(dim)]
        break
    if not isinstance(vector_raw, list):
        return []
    try:
        return [float(x) for x in vector_raw]
    except (TypeError, ValueError):
        return []


def _oss_image_url(config: McBackendConfig, image_path: str) -> str:
    if not config.oss_bucket:
        raise ConfigurationError("MC embedding oss_url mode requires MC_OSS_BUCKET")
    region_id = config.cloud_region.replace("_", "-")
    key = Path(image_path).name
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{config.oss_bucket}/{key}"


class McFusionEmbeddingClient:
    """通过 MaxFrame AI embed 生成 clip 融合向量。"""

    def __init__(
        self,
        *,
        runtime: McRuntime,
        config: McBackendConfig,
        model: str = "qwen3-vl-embedding",
        dimension: int = 1024,
    ):
        self.runtime = runtime
        self.config = config
        self.model = model
        self.dimension = dimension

    def embed_clip(self, clip: Clip, *, extra_text: str = "") -> dict[str, Any]:
        text_parts: list[str] = []
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

        self.runtime.prepare_for_model(self.model)
        require_maxframe()
        import maxframe.dataframe as md
        from maxframe.learn.contrib.llm import ImageContentType

        llm = create_ai_model(
            self.model,
            self.runtime.odps_entry,
            modelset_project=self.config.modelset_project,
        )
        mode = self.config.resolved_image_mode()
        storage = self.config.storage_options()

        row: dict[str, Any] = {"clip_id": clip.clip_id}
        image_paths: list[str] = [f.image_path for f in image_frames]
        if acoustic_panel_path:
            image_paths.append(acoustic_panel_path)

        if mode == "base64":
            for idx, path in enumerate(image_paths):
                row[f"image_b64_{idx}"] = _image_b64(path)
        else:
            for idx, path in enumerate(image_paths):
                row[f"image_url_{idx}"] = _oss_image_url(self.config, path)

        df = md.DataFrame(pd.DataFrame([row]))
        running = running_options_for(self.config)
        embed_kwargs: dict[str, Any] = {
            "params": {
                "enable_fusion": True,
                "dimension": int(self.dimension),
            },
        }
        if running:
            embed_kwargs["running_options"] = running

        if hasattr(llm, "content_part") and image_paths:
            cp = llm.content_part
            parts: list[Any] = []
            if text_parts:
                parts.append(cp.text("\n".join(text_parts)))
            for idx in range(len(image_paths)):
                if mode == "base64":
                    parts.append(
                        cp.image(
                            data=getattr(df, f"image_b64_{idx}"),
                            type=ImageContentType.BASE64,
                            mime_type="image/jpeg",
                        )
                    )
                else:
                    if not storage:
                        raise ConfigurationError(
                            "MC embedding oss_url mode requires OSS_VL_ACCESS_KEY_ID/SECRET"
                        )
                    parts.append(
                        cp.image(
                            data=getattr(df, f"image_url_{idx}"),
                            type=ImageContentType.IMAGE_URL,
                            storage_options=storage,
                        )
                    )
            try:
                result = llm.embed(df, input=parts, simple_output=True, **embed_kwargs)
            except TypeError:
                result = llm.embed(df, input=parts, **embed_kwargs)
        elif text_parts:
            text_df = md.DataFrame(pd.DataFrame({"text": ["\n".join(text_parts)]}))
            embed_kwargs_text: dict[str, Any] = {"simple": True, **embed_kwargs}
            result = llm.embed(text_df["text"], **embed_kwargs_text)
        else:
            raise ConfigurationError(f"Model {self.model} cannot embed images in MC mode")

        outputs = _fetch_series(result, ("output", "embedding", "embeddings", "vector"))
        embedding = _normalize_embedding_vector(outputs[0] if outputs else [])
        if self.dimension > 0 and len(embedding) > self.dimension:
            embedding = embedding[: self.dimension]

        return {
            "clip_id": clip.clip_id,
            "bag_name": clip.bag_name,
            "start_timestamp_ns": clip.start_timestamp_ns,
            "end_timestamp_ns": clip.end_timestamp_ns,
            "duration_sec": clip.duration_sec,
            "model": self.model,
            "dimension": self.dimension,
            "embedding_type": "fusion",
            "embedding": embedding,
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
                "backend": "maxframe_mc",
                "image_mode": mode,
            },
            "usage": {},
            "request_id": "",
        }
