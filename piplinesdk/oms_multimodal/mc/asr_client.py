"""MaxFrame AI ASR 客户端（bigdata_modelset）。"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pandas as pd

from ..asr_client import AsrConfig
from ..exceptions import ConfigurationError
from ..rosbag_parser import Clip
from .config import McBackendConfig
from .runtime import (
    McRuntime,
    _fetch_series,
    _normalize_llm_output,
    create_ai_model,
    is_asr_capable_model,
    require_maxframe,
    running_options_for,
)


class McAsrClient:
    """通过 MaxFrame AI Function + input_audio 做 clip ASR。"""

    def __init__(
        self,
        *,
        runtime: McRuntime,
        config: McBackendConfig,
        asr_config: AsrConfig | None = None,
    ):
        self.runtime = runtime
        self.config = config
        self.asr_config = asr_config or AsrConfig.from_env()
        if not is_asr_capable_model(self.asr_config.model):
            raise ConfigurationError(
                f"MC ASR model {self.asr_config.model!r} does not look ASR-capable; "
                "register qwen3-asr-flash in bigdata_modelset or use MODEL_BACKEND=api"
            )

    def _resolve_audio_url(self, wav_path: Path) -> str:
        mode = self.config.resolved_image_mode()
        if mode == "oss_url":
            if not self.config.oss_bucket:
                raise ConfigurationError("MC ASR oss_url mode requires MC_OSS_BUCKET")
            region_id = self.config.cloud_region.replace("_", "-")
            return f"oss://oss-{region_id}-internal.aliyuncs.com/{self.config.oss_bucket}/{wav_path.name}"
        encoded = base64.b64encode(wav_path.read_bytes()).decode("utf-8")
        return f"data:audio/wav;base64,{encoded}"

    def transcribe_wav(self, wav_path: str, *, sample_rate: int = 48000) -> dict[str, Any]:
        del sample_rate  # MaxFrame ASR 从容器格式推断
        path = Path(wav_path)
        if not path.is_file():
            raise FileNotFoundError(wav_path)

        model = self.asr_config.model
        self.runtime.prepare_for_model(model)
        require_maxframe()
        import maxframe.dataframe as md

        llm = create_ai_model(model, self.runtime.odps_entry, modelset_project=self.config.modelset_project)
        audio_url = self._resolve_audio_url(path)
        df = md.DataFrame(pd.DataFrame([{"audio_url": audio_url}]))
        messages = [
            {
                "role": "user",
                "content": [{"type": "input_audio", "input_audio": {"data": "{audio_url}"}}],
            }
        ]
        params: dict[str, Any] = {"asr_options": {"enable_itn": self.asr_config.enable_itn}}
        if self.asr_config.language:
            params["asr_options"]["language"] = self.asr_config.language.split("-")[0].lower()

        gen_kwargs: dict[str, Any] = {"simple_output": True, "params": params}
        running = running_options_for(self.config)
        if running:
            gen_kwargs["running_options"] = running
        storage = self.config.storage_options()

        def _generate(**extra: Any) -> Any:
            kwargs = {**gen_kwargs, **extra}
            try:
                return llm.generate(df, messages=messages, **kwargs)
            except TypeError:
                return llm.generate(df, prompt_template=messages, **kwargs)

        if storage:
            try:
                result = _generate(storage_options=storage)
            except TypeError:
                result = _generate()
        else:
            result = _generate()

        outputs = _fetch_series(result, ("output", "generated_text", "text", "content", "response"))
        text = _normalize_llm_output(outputs[0] if outputs else "")
        return {
            "model": model,
            "text": text,
            "sentences": None,
            "request_id": "",
            "usage": None,
            "backend": "maxframe_mc",
        }

    def transcribe_clip(self, clip: Clip) -> dict[str, Any]:
        if not clip.audio or not clip.audio.audio_path:
            return {
                "model": self.asr_config.model,
                "text": "",
                "sentences": None,
                "request_id": "",
                "usage": None,
                "skipped": True,
                "reason": "no_audio",
            }
        row = self.transcribe_wav(clip.audio.audio_path, sample_rate=clip.audio.sample_rate)
        row["skipped"] = False
        clip.asr_text = row["text"] or None
        clip.asr_model = row["model"]
        return row
