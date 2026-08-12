"""MaxFrame 2.8+ ContentPart 构造：从 Clip 生成 image / audio / video parts。"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Literal

from ..exceptions import ConfigurationError
from ..rosbag_parser import Clip
from .config import McBackendConfig

McMediaMode = Literal["base64", "oss_url"]


def mc_native_media_enabled() -> bool:
    """Omni MC 是否优先用 content_part 的 audio/video（MaxFrame 2.8+）。"""
    raw = os.getenv("MC_OMNI_NATIVE_MEDIA", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def file_base64(path: str | Path) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode("utf-8")


def oss_internal_object_url(config: McBackendConfig, object_key: str) -> str:
    if not config.oss_bucket:
        raise ConfigurationError("MC oss_url mode requires MC_OSS_BUCKET / OSS_BUCKET")
    region_id = config.cloud_region.replace("_", "-")
    key = str(object_key).lstrip("/")
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{config.oss_bucket}/{key}"


def resolved_media_mode(config: McBackendConfig) -> McMediaMode:
    mode = config.resolved_image_mode()
    return "oss_url" if mode == "oss_url" else "base64"


def pick_preview_video_path(clip: Clip) -> str | None:
    """按 OMNI_VIDEO_VARIANT=plain|bbox|auto 选择预览 MP4。

    - plain: 仅原视频
    - bbox: 优先带框图，否则回退 plain
    - auto（默认）: 有 bbox 视频则用 bbox，否则 plain
    """
    variant = omni_video_variant()
    plain = _first_existing_video(clip.clip_video_path, clip.clip_video_paths)
    bbox = _first_existing_video(clip.clip_video_bbox_path, clip.clip_video_bbox_paths)
    if variant == "plain":
        return plain
    if variant == "bbox":
        return bbox or plain
    return bbox or plain


def resolve_omni_frame_path(clip: Clip, image_path: str) -> str:
    """帧序列路径：与 OMNI_VIDEO_VARIANT 同策略，有 bbox 图时可选 remap。"""
    variant = omni_video_variant()
    if variant == "plain":
        return image_path
    path_map = clip.bbox_frame_paths or {}
    if not path_map:
        return image_path
    alt = path_map.get(image_path) or path_map.get(str(Path(image_path).resolve()))
    if alt and Path(alt).is_file():
        return alt
    return image_path


def omni_frame_paths(clip: Clip, *, limit: int | None = 4) -> list[str]:
    frames = list(clip.frames or [])
    if limit is not None:
        frames = frames[:limit]
    return [resolve_omni_frame_path(clip, f.image_path) for f in frames]


def _first_existing_video(
    primary: str | None,
    paths: dict[str, str] | None,
) -> str | None:
    if primary and Path(primary).is_file():
        return primary
    if paths:
        for path in paths.values():
            if path and Path(path).is_file():
                return path
    return None


def omni_video_variant() -> str:
    raw = os.getenv("OMNI_VIDEO_VARIANT", "auto").strip().lower()
    if raw in {"plain", "bbox", "auto"}:
        return raw
    return "auto"


def speech_context_without_asr(clip: Clip) -> str:
    """文本侧不含 ASR 全文的 speech context（仅事件 + Mel；Omni 默认仍用 ``speech_context_text`` 含 ASR）。"""
    parts: list[str] = []
    fusion = clip.fusion_text()
    if fusion:
        parts.append(f"[Event texts]\n{fusion}")
    if clip.mel_feature_text and clip.mel_feature_text.strip():
        parts.append(clip.mel_feature_text.strip())
    return "\n\n".join(parts)


def _require_storage(config: McBackendConfig) -> dict[str, str]:
    storage = config.storage_options()
    if not storage:
        raise ConfigurationError(
            "MC oss_url media mode requires OSS_VL_ACCESS_KEY_ID/SECRET"
        )
    return storage


def add_audio_part(
    parts: list[Any],
    *,
    cp: Any,
    df: Any,
    config: McBackendConfig,
    column_prefix: str,
    wav_path: str,
    fmt: str = "wav",
) -> None:
    from maxframe.learn.contrib.llm import AudioContentType

    mode = resolved_media_mode(config)
    mime = f"audio/{fmt or 'wav'}"
    if mode == "base64":
        parts.append(
            cp.audio(
                data=getattr(df, f"{column_prefix}_b64"),
                type=AudioContentType.BASE64,
                mime_type=mime,
            )
        )
    else:
        storage = _require_storage(config)
        parts.append(
            cp.audio(
                data=getattr(df, f"{column_prefix}_url"),
                type=AudioContentType.URL,
                mime_type=mime,
                storage_options=storage,
            )
        )
    _ = wav_path


def add_video_part(
    parts: list[Any],
    *,
    cp: Any,
    df: Any,
    config: McBackendConfig,
    column_prefix: str,
    video_path: str,
) -> None:
    from maxframe.learn.contrib.llm import VideoContentType

    mode = resolved_media_mode(config)
    mime = "video/mp4"
    if mode == "base64":
        parts.append(
            cp.video(
                data=getattr(df, f"{column_prefix}_b64"),
                type=VideoContentType.BASE64,
                mime_type=mime,
            )
        )
    else:
        storage = _require_storage(config)
        parts.append(
            cp.video(
                data=getattr(df, f"{column_prefix}_url"),
                type=VideoContentType.URL,
                mime_type=mime,
                storage_options=storage,
            )
        )
    _ = video_path


def add_image_parts(
    parts: list[Any],
    *,
    cp: Any,
    df: Any,
    config: McBackendConfig,
    frame_count: int,
    column_prefix: str = "image",
) -> None:
    from maxframe.learn.contrib.llm import ImageContentType

    mode = resolved_media_mode(config)
    for idx in range(frame_count):
        if mode == "base64":
            parts.append(
                cp.image(
                    data=getattr(df, f"{column_prefix}_b64_{idx}"),
                    type=ImageContentType.BASE64,
                    mime_type="image/jpeg",
                )
            )
        else:
            storage = _require_storage(config)
            parts.append(
                cp.image(
                    data=getattr(df, f"{column_prefix}_url_{idx}"),
                    type=ImageContentType.URL,
                    mime_type="image/jpeg",
                    storage_options=storage,
                )
            )


def populate_media_columns(
    row: dict[str, Any],
    *,
    config: McBackendConfig,
    local_path: str,
    column_prefix: str,
    oss_object_key: str | None = None,
) -> None:
    """向 Driver DataFrame 行写入 base64 或 oss_url 列。"""
    path = Path(local_path)
    if resolved_media_mode(config) == "base64":
        row[f"{column_prefix}_b64"] = file_base64(path)
    else:
        key = oss_object_key or path.name
        row[f"{column_prefix}_url"] = oss_internal_object_url(config, key)


def build_omni_label_parts(
    *,
    cp: Any,
    df: Any,
    config: McBackendConfig,
    clip: Clip,
    user_prompt: str,
    use_native_media: bool,
    omni_model: str,
) -> list[Any]:
    """构造 Omni 打标 messages content（media → text；text 含 ASR + 事件 + Mel）。"""
    from .runtime import is_omni_model_name

    parts: list[Any] = []
    use_native = use_native_media and is_omni_model_name(omni_model)

    if use_native:
        video_path = pick_preview_video_path(clip)
        if video_path:
            add_video_part(
                parts,
                cp=cp,
                df=df,
                config=config,
                column_prefix="video",
                video_path=video_path,
            )
        elif clip.frames:
            # Driver DataFrame image columns are populated separately via omni_frame_paths.
            add_image_parts(
                parts,
                cp=cp,
                df=df,
                config=config,
                frame_count=min(len(omni_frame_paths(clip, limit=4)), 4),
            )

        if clip.audio and clip.audio.audio_path and Path(clip.audio.audio_path).is_file():
            add_audio_part(
                parts,
                cp=cp,
                df=df,
                config=config,
                column_prefix="audio",
                wav_path=clip.audio.audio_path,
                fmt=clip.audio.format,
            )
        parts.append(cp.text(user_prompt))
        return parts

    # VL fallback / 非 Omni：text 在前 + image 抽帧（最多 4 张，保持旧行为）
    parts.append(cp.text(user_prompt))
    n_frames = len(omni_frame_paths(clip, limit=4))
    if n_frames:
        add_image_parts(
            parts,
            cp=cp,
            df=df,
            config=config,
            frame_count=n_frames,
        )
    return parts


def resolve_omni_mc_mode(
    *,
    omni_model: str,
    effective_model: str,
    clip: Clip,
    use_native_media: bool,
) -> str:
    from .runtime import is_omni_model_name

    if effective_model != omni_model:
        return "vl_fallback"
    if not use_native_media or not is_omni_model_name(effective_model):
        return "omni_images"
    if pick_preview_video_path(clip):
        return "omni_native"
    if clip.audio and clip.audio.audio_path and Path(clip.audio.audio_path).is_file():
        return "omni_native"
    return "omni_images"


def build_asr_audio_parts(
    *,
    cp: Any,
    df: Any,
    config: McBackendConfig,
) -> list[Any]:
    parts: list[Any] = []
    add_audio_part(
        parts,
        cp=cp,
        df=df,
        config=config,
        column_prefix="audio",
        wav_path="",
    )
    return parts
