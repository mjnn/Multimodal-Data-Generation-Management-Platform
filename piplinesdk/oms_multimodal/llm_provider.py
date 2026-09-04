"""LLM / multimodal provider selection: DashScope vs internal OpenAI-compatible AIGW.

Environment (new vars; DashScope path unchanged when provider=dashscope):

- ``LLM_PROVIDER`` = ``dashscope`` | ``aigw`` (default ``dashscope``)
- ``OMNI_PROVIDER`` / ``ASR_PROVIDER`` / ``EMBEDDING_PROVIDER`` — optional per-capability override
- ``AIGW_BASE_URL`` — e.g. ``https://ali.aigw.csvw.com/model/ark/llm/master-agent/v1``
- ``AIGW_API_KEY`` — Bearer token
- ``AIGW_OMNI_MODEL`` / ``AIGW_ASR_MODEL`` / ``AIGW_EMBEDDING_MODEL`` — model ids (ep-…)
- ``AIGW_TIMEOUT_SEC`` — default 900
- ``AIGW_OMNI_STREAM`` — ``1``/``0``; default ``0`` for aigw (gateway curl is non-stream)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

LlmProvider = Literal["dashscope", "aigw"]
_CAPABILITY = Literal["omni", "asr", "embedding"]


def _norm_provider(raw: str | None) -> LlmProvider:
    val = (raw or "").strip().lower()
    if val in {"aigw", "openai", "openai_compat", "gateway"}:
        return "aigw"
    return "dashscope"


def resolve_llm_provider(capability: _CAPABILITY | None = None) -> LlmProvider:
    """Resolve provider for a capability; per-cap override then ``LLM_PROVIDER``."""
    if capability:
        env_key = {
            "omni": "OMNI_PROVIDER",
            "asr": "ASR_PROVIDER",
            "embedding": "EMBEDDING_PROVIDER",
        }[capability]
        override = os.getenv(env_key, "").strip()
        if override:
            return _norm_provider(override)
    return _norm_provider(os.getenv("LLM_PROVIDER", "dashscope"))


@dataclass(frozen=True)
class AigwSettings:
    base_url: str
    api_key: str
    omni_model: str
    asr_model: str
    embedding_model: str
    timeout_sec: float
    omni_stream: bool


def load_aigw_settings() -> AigwSettings:
    base_url = (os.getenv("AIGW_BASE_URL") or "").strip().rstrip("/")
    api_key = (os.getenv("AIGW_API_KEY") or "").strip()
    default_model = (os.getenv("AIGW_MODEL") or "").strip()
    omni_model = (os.getenv("AIGW_OMNI_MODEL") or default_model or os.getenv("OMNI_MODEL") or "").strip()
    asr_model = (os.getenv("AIGW_ASR_MODEL") or default_model or os.getenv("ASR_MODEL") or "").strip()
    embedding_model = (
        os.getenv("AIGW_EMBEDDING_MODEL") or default_model or os.getenv("EMBEDDING_MODEL") or ""
    ).strip()
    timeout_sec = float(os.getenv("AIGW_TIMEOUT_SEC", os.getenv("OMNI_REQUEST_TIMEOUT_SEC", "900")))
    stream_raw = os.getenv("AIGW_OMNI_STREAM", "0").strip().lower()
    omni_stream = stream_raw in {"1", "true", "yes", "on"}
    if not base_url:
        raise RuntimeError("AIGW_BASE_URL is not configured")
    if not api_key:
        raise RuntimeError("AIGW_API_KEY is not configured")
    return AigwSettings(
        base_url=base_url,
        api_key=api_key,
        omni_model=omni_model,
        asr_model=asr_model,
        embedding_model=embedding_model,
        timeout_sec=timeout_sec,
        omni_stream=omni_stream,
    )


def make_openai_client(*, base_url: str, api_key: str, timeout_sec: float):
    """Lazy import OpenAI client for aigw."""
    from openai import OpenAI

    return OpenAI(api_key=api_key, base_url=base_url, timeout=timeout_sec)
