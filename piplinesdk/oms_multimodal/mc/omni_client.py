"""MaxFrame AI 打标客户端。

Omni 已上架 bigdata_public_modelset：默认直接用 ``omni_model``（如 ``qwen3.5-omni-plus``）。
MaxFrame 2.8+ 下 ``cp.video`` + ``cp.audio`` + ``cp.text``（含 ASR transcript）；
VL fallback 仍用 image 抽帧。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ..label_prompt import build_omni_user_text, merge_omni_label_prompt
from ..rosbag_parser import Clip
from ..taxonomy import normalize_model_labels, parse_label_json, taxonomy_prompt_block
from .config import McBackendConfig
from .content_parts import (
    build_omni_label_parts,
    file_base64,
    mc_native_media_enabled,
    oss_internal_object_url,
    pick_preview_video_path,
    populate_media_columns,
    resolve_omni_mc_mode,
)
from .runtime import (
    McRuntime,
    _fetch_series,
    _normalize_llm_output,
    create_ai_model,
    escape_mf_template_text,
    extract_json_object,
    is_omni_model_name,
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
            event_text="",
            params=prompt_params,
            bbox_context=getattr(clip, "bbox_context_text", None) or "",
        )
        return f"{user_text}\n\n{prompt}"

    def _populate_input_row(self, clip: Clip, *, use_native_media: bool) -> dict[str, Any]:
        row: dict[str, Any] = {"clip_id": clip.clip_id}
        mode = self.config.resolved_image_mode()
        use_native = use_native_media and is_omni_model_name(self._effective_model)

        if use_native:
            video_path = pick_preview_video_path(clip)
            if video_path:
                populate_media_columns(
                    row,
                    config=self.config,
                    local_path=video_path,
                    column_prefix="video",
                )
            elif clip.frames:
                from .content_parts import omni_frame_paths

                for idx, image_path in enumerate(omni_frame_paths(clip, limit=4)):
                    if mode == "base64":
                        row[f"image_b64_{idx}"] = file_base64(image_path)
                    else:
                        row[f"image_url_{idx}"] = oss_internal_object_url(
                            self.config, Path(image_path).name
                        )
            if clip.audio and clip.audio.audio_path and Path(clip.audio.audio_path).is_file():
                populate_media_columns(
                    row,
                    config=self.config,
                    local_path=clip.audio.audio_path,
                    column_prefix="audio",
                )
            return row

        from .content_parts import omni_frame_paths

        for idx, image_path in enumerate(omni_frame_paths(clip, limit=4)):
            if mode == "base64":
                row[f"image_b64_{idx}"] = file_base64(image_path)
            else:
                row[f"image_url_{idx}"] = oss_internal_object_url(
                    self.config, Path(image_path).name
                )
        return row

    def label_clip(self, clip: Clip, taxonomy: dict[str, Any]) -> dict[str, Any]:
        self.runtime.prepare_for_model(self._effective_model)
        require_maxframe()
        import maxframe.dataframe as md

        llm = create_ai_model(
            self._effective_model,
            self.runtime.odps_entry,
            modelset_project=self.config.modelset_project,
        )
        use_native_media = mc_native_media_enabled()
        sends_audio = (
            use_native_media
            and is_omni_model_name(self._effective_model)
            and clip.audio
            and clip.audio.audio_path
            and Path(clip.audio.audio_path).is_file()
        )
        user_prompt = escape_mf_template_text(self._build_user_prompt(clip, taxonomy))
        row = self._populate_input_row(clip, use_native_media=use_native_media)
        df = md.DataFrame(pd.DataFrame([row]))
        gen_kwargs: dict[str, Any] = {
            "simple_output": True,
            "params": {"temperature": 0.2, "max_tokens": 4096},
        }
        running = running_options_for(self.config)
        if running:
            gen_kwargs["running_options"] = running

        mc_mode = resolve_omni_mc_mode(
            omni_model=self.omni_model,
            effective_model=self._effective_model,
            clip=clip,
            use_native_media=use_native_media,
        )

        if hasattr(llm, "content_part"):
            cp = llm.content_part
            content_parts = build_omni_label_parts(
                cp=cp,
                df=df,
                config=self.config,
                clip=clip,
                user_prompt=user_prompt,
                use_native_media=use_native_media,
                omni_model=self._effective_model,
            )
            messages = [{"role": "user", "content": content_parts}]
            try:
                result = llm.generate(df, messages=messages, **gen_kwargs)
            except TypeError:
                result = llm.generate(df, prompt_template=messages, **gen_kwargs)
        else:
            result = llm.generate(df["clip_id"], prompt=self._build_user_prompt(clip, taxonomy), **gen_kwargs)
            mc_mode = "legacy_text"

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
            "mc_mode": mc_mode,
            "mc_native_media": use_native_media,
            "mc_has_video": bool(pick_preview_video_path(clip)),
            "mc_has_audio_part": sends_audio,
            "mc_has_asr_in_text": bool((clip.asr_text or "").strip()),
        }
