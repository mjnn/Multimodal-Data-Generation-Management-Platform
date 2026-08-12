# =============================================================================
# Driver-side bare MaxFrame Omni label（不经 OMS SDK McOmniLabelClient）
# DPE 挂载打包 frames/audio/taxonomy_prompt → Driver generate → DPE 写 labels.jsonl
# =============================================================================

from __future__ import annotations

import json
from typing import Any

from sdk_driver_bare_asr import (
    configure_driver_mc_ai_session,
    ensure_odps_catalog_for_driver,
    image_mime_from_key,
    oss_internal_object_url,
)

DEFAULT_OMNI_MODEL = "qwen3.5-omni-plus"
DEFAULT_MODELSET_PROJECT = "bigdata_public_modelset"


def _normalize_llm_output(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, dict):
        choices = raw.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}
            content = message.get("content")
            if content is not None:
                return str(content).strip()
        content = raw.get("content") or raw.get("text") or raw.get("output")
        if content is not None:
            return str(content).strip()
        return ""
    text = str(raw).strip()
    if text.startswith("{") and "choices" in text:
        try:
            return _normalize_llm_output(json.loads(text))
        except json.JSONDecodeError:
            pass
    return text


def parse_label_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {"scene_summary": "", "labels": {}, "raw": raw_text}
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"scene_summary": "", "labels": {}, "raw": raw_text}
    return parsed if isinstance(parsed, dict) else {"scene_summary": "", "labels": {}, "raw": raw_text}


def escape_mf_template_text(text: str) -> str:
    # MaxFrame prompt templates treat { } specially.
    return text.replace("{", "{{").replace("}", "}}")


def build_label_user_prompt(
    *,
    duration_sec: float,
    asr_text: str,
    taxonomy_prompt: str,
) -> str:
    speech = ""
    if asr_text.strip():
        speech = f"[ASR transcript]\n{asr_text.strip()}"
    intro = (
        f"请分析这段完整车内 rosbag clip（时长 {duration_sec:.1f} 秒）。"
        " 图像为多相机抽帧，音频覆盖整段。"
        " 请为整段场景填写 taxonomy 标签。"
        " 若提供了 ASR 文本，请以其为语音内容的依据，并与音视频交叉验证。"
    )
    parts = [intro]
    if speech:
        parts.append(f"\n\nMultimodal text context:\n{speech}")
    if taxonomy_prompt.strip():
        parts.append(f"\n\n{taxonomy_prompt.strip()}")
    return "".join(parts)


def _pack_oss_key(pack: dict[str, Any], *names: str) -> str:
    for name in names:
        val = str(pack.get(name) or "").strip()
        if val:
            return val.replace("\\", "/").lstrip("/")
    return ""


def driver_bare_label_generate(
    odps_entry: Any,
    *,
    pack_rows: list[dict[str, Any]],
    omni_model: str = DEFAULT_OMNI_MODEL,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    catalog_endpoint: str | None = None,
    inference_quota_name: str | None = None,
    parallel_partitions: int = 1,
    media_mode: str = "dpe_base64",
    media_storage_options: dict[str, str] | None = None,
    cloud_region: str = "cn_shanghai",
    oss_bucket: str = "",
) -> dict[str, Any]:
    """pack_rows from DPE: clip meta + (image/audio b64 OR oss keys) + taxonomy_prompt."""
    import pandas as pd
    import maxframe.dataframe as md
    from maxframe.learn.utils import read_odps_model
    from maxframe.session import new_session

    if not pack_rows:
        raise FileNotFoundError("no label pack rows")

    mode = str(media_mode or "dpe_base64").strip().lower()
    if mode in ("base64", "b64"):
        mode = "dpe_base64"
    if mode not in ("oss_url", "dpe_base64"):
        raise ValueError(f"media_mode must be oss_url|dpe_base64, got {media_mode!r}")
    if mode == "oss_url":
        if not oss_bucket:
            raise ValueError("driver_bare_label_generate oss_url mode requires oss_bucket")
        if not media_storage_options:
            raise ValueError(
                "driver_bare_label_generate oss_url mode requires media_storage_options "
                "(oss_vl_* / oss_access_key_*)"
            )

    configure_driver_mc_ai_session(inference_quota_name=inference_quota_name)
    ensure_odps_catalog_for_driver(odps_entry, catalog_endpoint)
    llm = read_odps_model(omni_model, project=modelset_project, odps_entry=odps_entry)

    rows_in: list[dict[str, Any]] = []
    for pack in pack_rows:
        duration = float(pack.get("duration_sec") or 0.0)
        asr_text = str(pack.get("asr_text") or "")
        tax = str(pack.get("taxonomy_prompt") or "")
        prompt = escape_mf_template_text(
            build_label_user_prompt(
                duration_sec=duration, asr_text=asr_text, taxonomy_prompt=tax
            )
        )
        row: dict[str, Any] = {
            "clip_id": str(pack.get("clip_id") or ""),
            "sdk_clip_id": str(pack.get("sdk_clip_id") or ""),
            "prompt": prompt,
        }
        image_count = int(pack.get("image_count") or 0)
        if mode == "oss_url":
            audio_key = _pack_oss_key(pack, "audio_oss_key", "audio_key")
            row["audio_url"] = (
                oss_internal_object_url(
                    cloud_region=cloud_region, bucket=oss_bucket, object_key=audio_key
                )
                if audio_key
                else ""
            )
            row["audio_oss_key"] = audio_key
            for i in range(min(image_count, 4)):
                key = _pack_oss_key(pack, f"image_oss_key_{i}", f"image_key_{i}")
                row[f"image_url_{i}"] = (
                    oss_internal_object_url(
                        cloud_region=cloud_region, bucket=oss_bucket, object_key=key
                    )
                    if key
                    else ""
                )
                row[f"image_oss_key_{i}"] = key
            has_audio = bool(row["audio_url"])
        else:
            row["audio_b64"] = str(pack.get("audio_b64") or "")
            for i in range(min(image_count, 4)):
                row[f"image_b64_{i}"] = str(pack.get(f"image_b64_{i}") or "")
            has_audio = bool(row["audio_b64"])
        rows_in.append(row)
        print(
            f"DRIVER_LABEL_PACK clip_id={row['clip_id']} "
            f"sdk_clip_id={row['sdk_clip_id'] or '-'} images={image_count} "
            f"media_mode={mode} audio={has_audio} asr_chars={len(asr_text)}"
        )

    # new_session BEFORE md.DataFrame so tunnel upload uses ODPS session.
    session = new_session(odps_entry)
    try:
        print(
            f"DRIVER_LABEL_LOGVIEW={session.get_logview_address()} "
            f"rows={len(rows_in)} parallel={max(1, int(parallel_partitions or 1))} "
            f"media_mode={mode}"
        )
        df = md.DataFrame(pd.DataFrame(rows_in))
        if parallel_partitions > 1:
            df = df.mf.rebalance(
                num_partitions=min(int(parallel_partitions), len(rows_in))
            )
        gen_kwargs: dict[str, Any] = {
            "simple_output": True,
            "params": {"temperature": 0.2, "max_tokens": 4096},
        }

        if hasattr(llm, "content_part"):
            from maxframe.learn.contrib.llm import AudioContentType, ImageContentType

            cp = llm.content_part
            content: list[Any] = [cp.text(getattr(df, "prompt"))]
            max_images = max(int(r.get("image_count") or 0) for r in pack_rows)
            for i in range(min(max_images, 4)):
                if mode == "oss_url":
                    col = f"image_url_{i}"
                    if col not in df.columns:
                        continue
                    key_col = f"image_oss_key_{i}"
                    sample_key = next(
                        (str(r.get(key_col) or "") for r in rows_in if r.get(key_col)),
                        "",
                    )
                    img_kwargs: dict[str, Any] = {
                        "data": getattr(df, col),
                        "type": ImageContentType.URL,
                        "mime_type": image_mime_from_key(sample_key),
                        "storage_options": {
                            "access_key_id": media_storage_options["access_key_id"],
                            "access_key_secret": media_storage_options[
                                "access_key_secret"
                            ],
                        },
                    }
                    content.append(cp.image(**img_kwargs))
                else:
                    col = f"image_b64_{i}"
                    if col in df.columns:
                        content.append(
                            cp.image(
                                data=getattr(df, col),
                                type=ImageContentType.BASE64,
                                mime_type="image/jpeg",
                            )
                        )
            if mode == "oss_url":
                if "audio_url" in df.columns:
                    audio_part: dict[str, Any] = {
                        "data": getattr(df, "audio_url"),
                        "type": AudioContentType.URL,
                        "mime_type": "audio/wav",
                        "storage_options": {
                            "access_key_id": media_storage_options["access_key_id"],
                            "access_key_secret": media_storage_options[
                                "access_key_secret"
                            ],
                        },
                    }
                    content.append(cp.audio(**audio_part))
            elif "audio_b64" in df.columns:
                content.append(
                    cp.audio(
                        data=getattr(df, "audio_b64"),
                        type=AudioContentType.BASE64,
                        mime_type="audio/wav",
                    )
                )
            messages = [{"role": "user", "content": content}]
            mc_mode = "omni_images_audio_url" if mode == "oss_url" else "omni_images_audio"
        else:
            messages = [{"role": "user", "content": "{prompt}"}]
            mc_mode = "legacy_text"

        try:
            result_df = llm.generate(df, messages=messages, **gen_kwargs)
        except TypeError:
            result_df = llm.generate(df, prompt_template=messages, **gen_kwargs)
        pdf = result_df.execute().fetch()
    finally:
        session.destroy()

    out_cols = list(pdf.columns)
    text_col = next(
        (c for c in ("output", "generated_text", "text", "content", "response") if c in out_cols),
        out_cols[0] if out_cols else None,
    )
    if text_col is None:
        raise RuntimeError(f"label result has no text column: {out_cols}")

    label_rows: list[dict[str, Any]] = []
    for i, pack in enumerate(pack_rows):
        raw = pdf.iloc[i][text_col] if i < len(pdf) else ""
        text = _normalize_llm_output(raw)
        parsed = parse_label_json(text)
        labels = parsed.get("labels") if isinstance(parsed.get("labels"), dict) else {}
        topics = pack.get("source_topics")
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except json.JSONDecodeError:
                topics = []
        label_rows.append(
            {
                "clip_id": str(pack.get("clip_id") or ""),
                "sdk_clip_id": str(pack.get("sdk_clip_id") or ""),
                "bag_name": str(pack.get("bag_name") or ""),
                "start_timestamp_ns": int(pack.get("start_timestamp_ns") or 0),
                "end_timestamp_ns": int(pack.get("end_timestamp_ns") or 0),
                "duration_sec": float(pack.get("duration_sec") or 0.0),
                "model": omni_model,
                "source_topics": topics or [],
                "scene_summary": str(parsed.get("scene_summary") or ""),
                "labels": labels,
                "asr_text": str(pack.get("asr_text") or ""),
                "asr_model": str(pack.get("asr_model") or "qwen3-asr-flash"),
                "raw_response": text,
                "usage": None,
                "request_id": "",
                "backend": "maxframe_mc",
                "omni_model_requested": omni_model,
                "mc_mode": mc_mode,
                "media_mode": mode,
                "submitter": "driver_bare",
            }
        )

    return {
        "row_count": len(label_rows),
        "clip_ids": [r["clip_id"] for r in label_rows],
        "mc_mode": mc_mode,
        "media_mode": mode,
        "label_rows": label_rows,
    }


def labels_jsonl_body(label_rows: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in label_rows) + (
        "\n" if label_rows else ""
    )
