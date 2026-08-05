"""MaxFrame AI 打标客户端。

Omni 已上架 bigdata_modelset：默认直接用 ``omni_model``（如 ``qwen3.5-omni-plus``）。
若仍需 VL 兜底，可设 ``MC_OMNI_FALLBACK_MODEL``（显式优先于 Omni catalog 名）。
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pandas as pd

from ..label_prompt import build_omni_user_text, merge_omni_label_prompt
from ..rosbag_parser import Clip
from ..taxonomy import normalize_model_labels, parse_label_json, taxonomy_prompt_block
from .config import McBackendConfig
from ..exceptions import ConfigurationError
from .runtime import (
    McRuntime,
    _fetch_series,
    _normalize_llm_output,
    create_ai_model,
    escape_mf_template_text,
    extract_json_object,
    require_maxframe,
    running_options_for,
)


class McOmniLabelClient:
    """MaxFrame 多模态打标；优先 Omni catalog，可选 VL fallback。"""

    def __init__(
        self,
        *,
        runtime: McRuntime,
        config: McBackendConfig,
        model: str = "qwen3.5-omni-plus",
        omni_label_prompt: dict[str, Any] | None = None,
    ):
        self.runtime = runtime
        self.config = config
        self.omni_model = model
        self.omni_label_prompt = omni_label_prompt
        self._effective_model = self._resolve_effective_model()

    def _resolve_effective_model(self) -> str:
        # Explicit fallback wins (legacy VL path / A-B test).
        fallback = (self.config.omni_fallback_model or "").strip()
        if fallback:
            return fallback
        return self.omni_model

    @property
    def model(self) -> str:
        return self._effective_model

    def _build_user_prompt(self, clip: Clip, taxonomy: dict[str, Any]) -> str:
        prompt_params = merge_omni_label_prompt(self.omni_label_prompt)
        prompt = taxonomy_prompt_block(taxonomy, prompt_params)
        user_text = build_omni_user_text(
            duration_sec=clip.duration_sec,
            speech_context=clip.speech_context_text(),
            event_text=clip.fusion_text(),
            params=prompt_params,
        )
        return f"{user_text}\n\n{prompt}"

    @staticmethod
    def _image_b64(path: str) -> str:
        return base64.b64encode(Path(path).read_bytes()).decode("utf-8")

    def label_clip(self, clip: Clip, taxonomy: dict[str, Any]) -> dict[str, Any]:
        self.runtime.prepare_for_model(self._effective_model)
        require_maxframe()
        import maxframe.dataframe as md
        from maxframe.learn.contrib.llm import ImageContentType

        llm = create_ai_model(
            self._effective_model,
            self.runtime.odps_entry,
            modelset_project=self.config.modelset_project,
        )
        user_prompt = self._build_user_prompt(clip, taxonomy)
        mode = self.config.resolved_image_mode()
        storage = self.config.storage_options()

        frames = clip.frames[:4] if clip.frames else []
        row: dict[str, Any] = {"clip_id": clip.clip_id}
        if mode == "base64":
            for idx, frame in enumerate(frames):
                row[f"image_b64_{idx}"] = self._image_b64(frame.image_path)
        else:
            if not self.config.oss_bucket:
                raise ConfigurationError("MC labeling oss_url mode requires MC_OSS_BUCKET")
            region_id = self.config.cloud_region.replace("_", "-")
            for idx, frame in enumerate(frames):
                key = Path(frame.image_path).name
                row[f"image_url_{idx}"] = (
                    f"oss://oss-{region_id}-internal.aliyuncs.com/{self.config.oss_bucket}/{key}"
                )

        df = md.DataFrame(pd.DataFrame([row]))
        gen_kwargs: dict[str, Any] = {
            "simple_output": True,
            "params": {"temperature": 0.2, "max_tokens": 4096},
        }
        running = running_options_for(self.config)
        if running:
            gen_kwargs["running_options"] = running

        if hasattr(llm, "content_part"):
            cp = llm.content_part
            # MaxFrame formats message text as a template; JSON braces must be escaped.
            content_parts: list[Any] = [cp.text(escape_mf_template_text(user_prompt))]
            for idx in range(len(frames)):
                if mode == "base64":
                    content_parts.append(
                        cp.image(
                            data=getattr(df, f"image_b64_{idx}"),
                            type=ImageContentType.BASE64,
                            mime_type="image/jpeg",
                        )
                    )
                else:
                    if not storage:
                        raise ConfigurationError(
                            "MC labeling oss_url mode requires OSS_VL_ACCESS_KEY_ID/SECRET"
                        )
                    content_parts.append(
                        cp.image(
                            data=getattr(df, f"image_url_{idx}"),
                            type=ImageContentType.IMAGE_URL,
                            storage_options=storage,
                        )
                    )
            messages = [{"role": "user", "content": content_parts}]
            try:
                result = llm.generate(df, messages=messages, **gen_kwargs)
            except TypeError:
                result = llm.generate(df, prompt_template=messages, **gen_kwargs)
        else:
            result = llm.generate(df["clip_id"], prompt=user_prompt, **gen_kwargs)

        outputs = _fetch_series(result, ("output", "generated_text", "text", "content", "response"))
        raw_text = _normalize_llm_output(outputs[0] if outputs else "")
        parsed = parse_label_json(raw_text) if raw_text.strip().startswith("{") else extract_json_object(raw_text)
        if not parsed.get("scene_summary") and parsed.get("raw"):
            parsed = parse_label_json(str(parsed.get("raw", "")))
        raw_labels = parsed.get("labels", {}) or {}
        if isinstance(raw_labels, dict):
            parsed = {**parsed, "labels": normalize_model_labels(taxonomy, raw_labels)}

        return {
            "clip_id": clip.clip_id,
            "bag_name": clip.bag_name,
            "start_timestamp_ns": clip.start_timestamp_ns,
            "end_timestamp_ns": clip.end_timestamp_ns,
            "duration_sec": clip.duration_sec,
            "model": self._effective_model,
            "source_topics": clip.source_topics,
            "scene_summary": parsed.get("scene_summary", ""),
            "labels": parsed.get("labels", {}),
            "asr_text": clip.asr_text or "",
            "asr_model": clip.asr_model,
            "raw_response": raw_text,
            "usage": None,
            "request_id": "",
            "backend": "maxframe_mc",
            "omni_model_requested": self.omni_model,
            "mc_mode": "vl_fallback" if self._effective_model != self.omni_model else "omni",
        }
