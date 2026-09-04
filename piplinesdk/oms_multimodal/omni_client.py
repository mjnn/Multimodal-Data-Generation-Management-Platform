"""Qwen-Omni 场景理解与 OMS 打标客户端。

通过 OpenAI 兼容接口调用模型：
- ``LLM_PROVIDER=dashscope``（默认）：百炼 MaaS ``compatible-mode/v1``
- ``LLM_PROVIDER=aigw``：内网 AI 网关（``AIGW_BASE_URL`` + ``AIGW_API_KEY``）

输入：clip 的 video 帧序列 + 完整音频 + 事件文本 + taxonomy prompt
输出：scene_summary + 结构化 labels JSON

DashScope Omni 默认 stream=True；aigw 默认非流式（可用 ``AIGW_OMNI_STREAM=1`` 打开）。
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

from openai import OpenAI

from .llm_provider import load_aigw_settings, make_openai_client, resolve_llm_provider
from .rosbag_parser import Clip
from .taxonomy import normalize_model_labels, parse_label_json, taxonomy_prompt_block


class OmniLabelClient:
    """多模态打标客户端（OpenAI 兼容 HTTP）。"""

    def __init__(
        self,
        *,
        model: str = "qwen3.5-omni-plus",
        api_key: str | None = None,
        workspace_id: str | None = None,
        region: str = "cn-beijing",
        omni_label_prompt: dict[str, Any] | None = None,
        provider: str | None = None,
    ):
        self.omni_label_prompt = omni_label_prompt
        self.provider = (provider or resolve_llm_provider("omni")).strip().lower()
        if self.provider not in {"dashscope", "aigw"}:
            self.provider = "dashscope"

        if self.provider == "aigw":
            aigw = load_aigw_settings()
            self.model = (aigw.omni_model or model or "").strip()
            if not self.model:
                raise RuntimeError("AIGW_OMNI_MODEL (or AIGW_MODEL) is not configured")
            self.api_key = aigw.api_key
            self.workspace_id = ""
            self.region = region
            self._stream = aigw.omni_stream
            self._dashscope_modalities = False
            self.client = make_openai_client(
                base_url=aigw.base_url,
                api_key=aigw.api_key,
                timeout_sec=aigw.timeout_sec,
            )
            return

        self.model = model
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.workspace_id = workspace_id or os.getenv("DASHSCOPE_WORKSPACE_ID", "")
        self.region = region or os.getenv("DASHSCOPE_REGION", "cn-beijing")
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if not self.workspace_id:
            raise RuntimeError("DASHSCOPE_WORKSPACE_ID is not configured")

        base_url = f"https://{self.workspace_id}.{self.region}.maas.aliyuncs.com/compatible-mode/v1"
        timeout_sec = float(os.getenv("OMNI_REQUEST_TIMEOUT_SEC", "900"))
        self._stream = True
        self._dashscope_modalities = True
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

    def _collect_completion_text(self, completion: Any) -> tuple[str, Any, str]:
        if self._stream:
            chunks: list[str] = []
            usage = None
            request_id = ""
            for chunk in completion:
                request_id = getattr(chunk, "id", request_id) or request_id
                if chunk.usage:
                    usage = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else chunk.usage
                if chunk.choices and chunk.choices[0].delta.content:
                    chunks.append(chunk.choices[0].delta.content)
            return "".join(chunks), usage, request_id

        usage = None
        if getattr(completion, "usage", None):
            usage = (
                completion.usage.model_dump()
                if hasattr(completion.usage, "model_dump")
                else completion.usage
            )
        request_id = getattr(completion, "id", "") or ""
        choice0 = completion.choices[0] if completion.choices else None
        message = getattr(choice0, "message", None) if choice0 else None
        content = getattr(message, "content", None) if message else None
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("text"):
                    parts.append(str(part["text"]))
                elif isinstance(part, str):
                    parts.append(part)
            raw_text = "".join(parts)
        else:
            raw_text = str(content or "")
        return raw_text, usage, request_id

    def label_clip(self, clip: Clip, taxonomy: dict[str, Any]) -> dict[str, Any]:
        """对单个 clip 做多模态场景理解并打标。

        帧数 ≥2 时使用 video 序列类型；仅 1 帧时退化为 image_url。
        返回 dict 可直接写入 labels.jsonl 的一行。
        """
        content: list[dict[str, Any]] = []

        from .mc.content_parts import omni_frame_paths

        frame_paths = omni_frame_paths(clip, limit=None)
        if len(frame_paths) >= 2:
            content.append(
                {
                    "type": "video",
                    "video": [self._frame_data_uri(p) for p in frame_paths],
                }
            )
        elif len(frame_paths) == 1:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._frame_data_uri(frame_paths[0])},
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
            bbox_context=getattr(clip, "bbox_context_text", None) or "",
        )
        content.append({"type": "text", "text": f"{user_text}\n\n{prompt}"})

        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "stream": self._stream,
        }
        if self._dashscope_modalities:
            create_kwargs["modalities"] = ["text"]
        if self._stream:
            create_kwargs["stream_options"] = {"include_usage": True}

        completion = self.client.chat.completions.create(**create_kwargs)
        raw_text, usage, request_id = self._collect_completion_text(completion)
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
            "provider": self.provider,
            "source_topics": clip.source_topics,
            "scene_summary": parsed.get("scene_summary", ""),
            "labels": parsed.get("labels", {}),
            "asr_text": clip.asr_text or "",
            "asr_model": clip.asr_model,
            "mel_matrix_path": clip.mel_matrix_path,
            "mel_matrix_shape": clip.mel_matrix_shape,
            "mel_feature_included": bool(clip.mel_feature_text),
            "raw_response": raw_text,
            "usage": usage,
            "request_id": request_id,
        }
