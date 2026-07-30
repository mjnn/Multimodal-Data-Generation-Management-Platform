"""Qwen-Omni 场景理解与 OMS 打标客户端。

通过 OpenAI 兼容接口调用 qwen3.5-omni-plus：
- 输入：clip 的 video 帧序列 + 完整音频 + 事件文本 + taxonomy prompt
- 输出：scene_summary + 结构化 labels JSON

注意：所有 Omni 请求必须 stream=True。
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from .rosbag_parser import Clip
from .taxonomy import parse_label_json, taxonomy_prompt_block, normalize_model_labels


class OmniLabelClient:
    """Qwen-Omni 打标客户端，使用 OpenAI 兼容 HTTP 接口。"""

    def __init__(
        self,
        *,
        model: str = "qwen3.5-omni-plus",
        api_key: str | None = None,
        workspace_id: str | None = None,
        region: str = "cn-beijing",
        omni_label_prompt: dict[str, Any] | None = None,
    ):
        self.model = model
        self.omni_label_prompt = omni_label_prompt
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.workspace_id = workspace_id or os.getenv("DASHSCOPE_WORKSPACE_ID", "")
        self.region = region or os.getenv("DASHSCOPE_REGION", "cn-beijing")
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if not self.workspace_id:
            raise RuntimeError("DASHSCOPE_WORKSPACE_ID is not configured")

        base_url = f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com/compatible-mode/v1"
        timeout_sec = float(os.getenv("OMNI_REQUEST_TIMEOUT_SEC", "900"))
        self.client = OpenAI(api_key=self.api_key, base_url=base_url, timeout=timeout_sec)

    def _frame_data_uri(self, image_path: str) -> str:
        """将本地图片转为 Base64 Data URI。"""
        path = Path(image_path)
        suffix = path.suffix.lower().lstrip(".") or "png"
        fmt = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
        encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
        return f"data:image/{fmt};base64,{encoded}"

    def _audio_part(self, audio_path: str, fmt: str = "wav") -> dict[str, Any]:
        """构造 Omni input_audio 内容块。"""
        encoded = base64.b64encode(Path(audio_path).read_bytes()).decode("utf-8")
        return {
            "type": "input_audio",
            "input_audio": {
                "data": f"data:;base64,{encoded}",
                "format": fmt,
            },
        }

    def label_clip(self, clip: Clip, taxonomy: dict[str, Any]) -> dict[str, Any]:
        """对单个 clip 做多模态场景理解并打标。

        帧数 ≥2 时使用 video 序列类型；仅 1 帧时退化为 image_url。
        返回 dict 可直接写入 labels.jsonl 的一行。
        """
        content: list[dict[str, Any]] = []

        if len(clip.frames) >= 2:
            content.append(
                {
                    "type": "video",
                    "video": [self._frame_data_uri(f.image_path) for f in clip.frames],
                }
            )
        elif len(clip.frames) == 1:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._frame_data_uri(clip.frames[0].image_path)},
                }
            )

        if clip.audio and clip.audio.audio_path:
            content.append(self._audio_part(clip.audio.audio_path, clip.audio.format))

        event_text = clip.fusion_text()
        speech_context = clip.speech_context_text()
        from .label_prompt import build_omni_user_text, merge_omni_label_prompt

        prompt_params = merge_omni_label_prompt(self.omni_label_prompt)
        prompt = taxonomy_prompt_block(taxonomy, prompt_params)
        user_text = build_omni_user_text(
            duration_sec=clip.duration_sec,
            speech_context=speech_context,
            event_text=event_text,
            params=prompt_params,
        )
        content.append({"type": "text", "text": f"{user_text}\n\n{prompt}"})

        completion = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            modalities=["text"],
            stream=True,
            stream_options={"include_usage": True},
        )

        chunks: list[str] = []
        usage = None
        request_id = ""
        for chunk in completion:
            request_id = getattr(chunk, "id", request_id) or request_id
            if chunk.usage:
                usage = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else chunk.usage
            if chunk.choices and chunk.choices[0].delta.content:
                chunks.append(chunk.choices[0].delta.content)

        raw_text = "".join(chunks)
        parsed = parse_label_json(raw_text)
        raw_labels = parsed.get("labels", {}) or {}
        if isinstance(raw_labels, dict):
            parsed = {**parsed, "labels": normalize_model_labels(taxonomy, raw_labels)}
        return {
            "clip_id": clip.clip_id,
            "bag_name": clip.bag_name,
            "start_timestamp_ns": clip.start_timestamp_ns,
            "end_timestamp_ns": clip.end_timestamp_ns,
            "duration_sec": clip.duration_sec,
            "model": self.model,
            "source_topics": clip.source_topics,
            "scene_summary": parsed.get("scene_summary", ""),
            "labels": parsed.get("labels", {}),
            "asr_text": clip.asr_text or "",
            "asr_model": clip.asr_model,
            "raw_response": raw_text,
            "usage": usage,
            "request_id": request_id,
        }
