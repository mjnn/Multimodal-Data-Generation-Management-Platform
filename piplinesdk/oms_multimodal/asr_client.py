"""Clip 音频 ASR（默认 Qwen3-ASR-Flash，可选 Paraformer Recognition）。"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any

import dashscope
from dashscope import MultiModalConversation
from dashscope.audio.asr import Recognition, RecognitionCallback

from .rosbag_parser import Clip


class _SilentAsrCallback(RecognitionCallback):
    """Recognition.call 同步模式所需占位 callback。"""


@dataclass
class AsrConfig:
    """ASR 配置。"""

    enabled: bool = True
    model: str = "qwen3-asr-flash"
    audio_format: str = "wav"
    enable_itn: bool = False
    language: str | None = "zh"

    @classmethod
    def from_env(cls) -> AsrConfig:
        enabled_raw = os.getenv("ASR_ENABLED", "true").strip().lower()
        enabled = enabled_raw not in {"0", "false", "no", "off"}
        lang = os.getenv("ASR_LANGUAGE", "zh").strip()
        return cls(
            enabled=enabled,
            model=os.getenv("ASR_MODEL", "qwen3-asr-flash"),
            audio_format=os.getenv("ASR_AUDIO_FORMAT", "wav"),
            enable_itn=os.getenv("ASR_ENABLE_ITN", "false").strip().lower() in {"1", "true", "yes"},
            language=lang or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sentences_to_text(sentences: Any) -> str:
    if not sentences:
        return ""
    if isinstance(sentences, dict):
        return str(sentences.get("text", "")).strip()
    if isinstance(sentences, list):
        parts = [str(s.get("text", "")).strip() for s in sentences if isinstance(s, dict)]
        return " ".join(p for p in parts if p)
    return ""


def _extract_qwen_asr_text(response: Any) -> str:
    output = getattr(response, "output", None) or {}
    choices = output.get("choices") if isinstance(output, dict) else getattr(output, "choices", None)
    if not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else getattr(choices[0], "message", None)
    if not message:
        return ""
    content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
    if not content:
        return ""
    for part in content:
        if isinstance(part, dict) and part.get("text"):
            return str(part["text"]).strip()
    return ""


def _is_qwen_asr_model(model: str) -> bool:
    lower = model.lower()
    return lower.startswith("qwen3-asr") or lower.startswith("qwen-asr")


class AsrClient:
    """对 clip WAV 做语音识别，供 Omni 打标与 VL-embedding 文本融合。"""

    def __init__(
        self,
        *,
        config: AsrConfig | None = None,
        api_key: str | None = None,
        workspace_id: str | None = None,
    ):
        self.config = config or AsrConfig.from_env()
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY", "")
        self.workspace_id = workspace_id or os.getenv("DASHSCOPE_WORKSPACE_ID") or None
        if self.config.enabled and not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    def _apply_api_key(self) -> None:
        if self.api_key:
            dashscope.api_key = self.api_key
            os.environ.setdefault("DASHSCOPE_API_KEY", self.api_key)

    def _transcribe_qwen_asr(self, wav_path: str) -> dict[str, Any]:
        self._apply_api_key()
        resolved = Path(wav_path).resolve()
        audio_uri = f"file://{resolved.as_posix()}"
        messages = [
            {"role": "system", "content": [{"text": ""}]},
            {"role": "user", "content": [{"audio": audio_uri}]},
        ]
        asr_options: dict[str, Any] = {"enable_itn": self.config.enable_itn}
        if self.config.language:
            asr_options["language"] = self.config.language

        response = MultiModalConversation.call(
            api_key=self.api_key,
            model=self.config.model,
            messages=messages,
            result_format="message",
            workspace=self.workspace_id,
            asr_options=asr_options,
        )
        if response.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"ASR failed: status={response.status_code}, code={getattr(response, 'code', '')}, "
                f"message={getattr(response, 'message', '')}"
            )

        text = _extract_qwen_asr_text(response)
        usage = getattr(response, "usage", None)
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        return {
            "model": self.config.model,
            "text": text,
            "sentences": None,
            "request_id": getattr(response, "request_id", ""),
            "usage": usage,
            "backend": "MultiModalConversation",
        }

    def _transcribe_paraformer(self, wav_path: str, *, sample_rate: int) -> dict[str, Any]:
        self._apply_api_key()
        recognizer = Recognition(
            model=self.config.model,
            callback=_SilentAsrCallback(),
            format=self.config.audio_format,
            sample_rate=sample_rate,
            workspace=self.workspace_id,
        )
        result = recognizer.call(wav_path)
        if result.status_code != HTTPStatus.OK:
            raise RuntimeError(
                f"ASR failed: status={result.status_code}, code={getattr(result, 'code', '')}, "
                f"message={getattr(result, 'message', '')}"
            )

        sentences = result.get_sentence()
        text = _sentences_to_text(sentences)
        return {
            "model": self.config.model,
            "text": text,
            "sentences": sentences,
            "request_id": result.get_request_id(),
            "usage": getattr(result, "usage", None),
            "backend": "Recognition",
        }

    def transcribe_wav(
        self,
        wav_path: str,
        *,
        sample_rate: int = 48000,
    ) -> dict[str, Any]:
        """识别本地 WAV，返回 text + 元数据。"""
        if _is_qwen_asr_model(self.config.model):
            return self._transcribe_qwen_asr(wav_path)
        return self._transcribe_paraformer(wav_path, sample_rate=sample_rate)

    def transcribe_clip(self, clip: Clip) -> dict[str, Any]:
        """对 clip 音频做 ASR；无音频时返回空文本。"""
        if not clip.audio or not clip.audio.audio_path:
            return {
                "model": self.config.model,
                "text": "",
                "sentences": None,
                "request_id": "",
                "usage": None,
                "skipped": True,
                "reason": "no_audio",
            }

        row = self.transcribe_wav(
            clip.audio.audio_path,
            sample_rate=clip.audio.sample_rate,
        )
        row["skipped"] = False
        clip.asr_text = row["text"] or None
        clip.asr_model = row["model"]
        return row
