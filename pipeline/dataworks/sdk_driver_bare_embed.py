# =============================================================================
# Driver-side bare MaxFrame fusion embed（不经 OMS SDK McFusionEmbeddingClient）
# DPE 打包 embedding frames + acoustic_panel + text → Driver embed → DPE 写 fusion_embeddings.jsonl
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

DEFAULT_EMBED_MODEL = "qwen3-vl-embedding"
DEFAULT_EMBED_DIM = 1024
DEFAULT_MODELSET_PROJECT = "bigdata_public_modelset"


def _normalize_embedding_vector(vector_raw: Any) -> list[float]:
    if isinstance(vector_raw, str):
        try:
            vector_raw = json.loads(vector_raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(vector_raw, list) or not vector_raw:
        return []
    while (
        isinstance(vector_raw, list)
        and vector_raw
        and isinstance(vector_raw[0], (list, tuple))
    ):
        if len(vector_raw) == 1:
            vector_raw = list(vector_raw[0])
            continue
        dim = len(vector_raw[0])
        if dim <= 0 or any(
            not isinstance(v, (list, tuple)) or len(v) != dim for v in vector_raw
        ):
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


def build_embed_text(*, asr_text: str, scene_summary: str, duration_sec: float) -> str:
    parts: list[str] = []
    if asr_text.strip():
        parts.append(f"[ASR transcript]\n{asr_text.strip()}")
    if scene_summary.strip():
        parts.append(f"[scene_summary]\n{scene_summary.strip()}")
    parts.append(f"[audio_duration_sec={duration_sec:.2f}]")
    return "\n\n".join(parts)


def _pack_oss_key(pack: dict[str, Any], *names: str) -> str:
    for name in names:
        val = str(pack.get(name) or "").strip()
        if val:
            return val.replace("\\", "/").lstrip("/")
    return ""


def driver_bare_embed_generate(
    odps_entry: Any,
    *,
    pack_rows: list[dict[str, Any]],
    label_by_clip: dict[str, dict[str, Any]] | None = None,
    embedding_model: str = DEFAULT_EMBED_MODEL,
    embedding_dimension: int = DEFAULT_EMBED_DIM,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    catalog_endpoint: str | None = None,
    inference_quota_name: str | None = None,
    parallel_partitions: int = 1,
    media_mode: str = "dpe_base64",
    media_storage_options: dict[str, str] | None = None,
    cloud_region: str = "cn_shanghai",
    oss_bucket: str = "",
) -> dict[str, Any]:
    import pandas as pd
    import maxframe.dataframe as md
    from maxframe.learn.utils import read_odps_model
    from maxframe.session import new_session

    if not pack_rows:
        raise FileNotFoundError("no embed pack rows")

    mode = str(media_mode or "dpe_base64").strip().lower()
    if mode in ("base64", "b64"):
        mode = "dpe_base64"
    if mode not in ("oss_url", "dpe_base64"):
        raise ValueError(f"media_mode must be oss_url|dpe_base64, got {media_mode!r}")
    if mode == "oss_url":
        if not oss_bucket:
            raise ValueError("driver_bare_embed_generate oss_url mode requires oss_bucket")
        if not media_storage_options:
            raise ValueError(
                "driver_bare_embed_generate oss_url mode requires media_storage_options "
                "(oss_vl_* / oss_access_key_*)"
            )

    label_by_clip = label_by_clip or {}
    configure_driver_mc_ai_session(inference_quota_name=inference_quota_name)
    ensure_odps_catalog_for_driver(odps_entry, catalog_endpoint)
    llm = read_odps_model(
        embedding_model, project=modelset_project, odps_entry=odps_entry
    )

    rows_in: list[dict[str, Any]] = []
    for pack in pack_rows:
        clip_id = str(pack.get("clip_id") or "")
        label = label_by_clip.get(clip_id) or {}
        if not label and pack.get("sdk_clip_id"):
            label = label_by_clip.get(str(pack.get("sdk_clip_id"))) or {}
        text = build_embed_text(
            asr_text=str(pack.get("asr_text") or label.get("asr_text") or ""),
            scene_summary=str(label.get("scene_summary") or ""),
            duration_sec=float(pack.get("duration_sec") or 0.0),
        )
        row: dict[str, Any] = {
            "clip_id": clip_id,
            "sdk_clip_id": str(pack.get("sdk_clip_id") or ""),
            "text": text,
        }
        image_count = int(pack.get("embed_image_count") or pack.get("image_count") or 0)
        if mode == "oss_url":
            for i in range(min(image_count, 8)):
                key = _pack_oss_key(
                    pack,
                    f"embed_image_oss_key_{i}",
                    f"image_oss_key_{i}",
                    f"embed_image_key_{i}",
                )
                if not key:
                    # fallback: label pack keys if embed keys absent
                    key = _pack_oss_key(pack, f"image_oss_key_{i}")
                row[f"image_oss_key_{i}"] = key
                row[f"image_url_{i}"] = (
                    oss_internal_object_url(
                        cloud_region=cloud_region, bucket=oss_bucket, object_key=key
                    )
                    if key
                    else ""
                )
        else:
            for i in range(min(image_count, 8)):
                # prefer embed_image_b64_* then image_b64_*
                val = pack.get(f"embed_image_b64_{i}")
                if val is None or str(val) == "":
                    val = pack.get(f"image_b64_{i}")
                row[f"image_b64_{i}"] = str(val or "")
        rows_in.append(row)
        print(
            f"DRIVER_EMBED_PACK clip_id={clip_id} "
            f"sdk_clip_id={row['sdk_clip_id'] or '-'} "
            f"images={image_count} media_mode={mode} text_chars={len(text)}"
        )

    # new_session BEFORE md.DataFrame / embed so tunnel uses ODPS session.
    session = new_session(odps_entry)
    try:
        print(
            f"DRIVER_EMBED_LOGVIEW={session.get_logview_address()} "
            f"rows={len(rows_in)} parallel={max(1, int(parallel_partitions or 1))} "
            f"media_mode={mode}"
        )
        df = md.DataFrame(pd.DataFrame(rows_in))
        if parallel_partitions > 1:
            df = df.mf.rebalance(
                num_partitions=min(int(parallel_partitions), len(rows_in))
            )
        embed_kwargs: dict[str, Any] = {
            "params": {"enable_fusion": True, "dimension": int(embedding_dimension)},
        }

        max_images = 0
        url_col = "image_url_{}" if mode == "oss_url" else "image_b64_{}"
        for r in rows_in:
            for i in range(8):
                if r.get(url_col.format(i)):
                    max_images = max(max_images, i + 1)

        if hasattr(llm, "content_part") and max_images > 0:
            from maxframe.learn.contrib.llm import ImageContentType

            cp = llm.content_part
            parts: list[Any] = [cp.text(getattr(df, "text"))]
            for i in range(max_images):
                if mode == "oss_url":
                    col = f"image_url_{i}"
                    if col not in df.columns:
                        continue
                    sample_key = next(
                        (
                            str(r.get(f"image_oss_key_{i}") or "")
                            for r in rows_in
                            if r.get(f"image_oss_key_{i}")
                        ),
                        "",
                    )
                    parts.append(
                        cp.image(
                            data=getattr(df, col),
                            type=ImageContentType.URL,
                            mime_type=image_mime_from_key(sample_key),
                            storage_options={
                                "access_key_id": media_storage_options["access_key_id"],
                                "access_key_secret": media_storage_options[
                                    "access_key_secret"
                                ],
                            },
                        )
                    )
                else:
                    col = f"image_b64_{i}"
                    if col in df.columns:
                        parts.append(
                            cp.image(
                                data=getattr(df, col),
                                type=ImageContentType.BASE64,
                                mime_type="image/jpeg",
                            )
                        )
            try:
                result = llm.embed(df, input=parts, simple_output=True, **embed_kwargs)
            except TypeError:
                result = llm.embed(df, input=parts, **embed_kwargs)
        else:
            text_df = md.DataFrame(pd.DataFrame({"text": [r["text"] for r in rows_in]}))
            result = llm.embed(text_df["text"], simple=True, **embed_kwargs)

        pdf = result.execute().fetch()
    finally:
        session.destroy()

    out_cols = list(pdf.columns)
    vec_col = next(
        (c for c in ("output", "embedding", "embeddings", "vector") if c in out_cols),
        out_cols[0] if out_cols else None,
    )
    if vec_col is None:
        raise RuntimeError(f"embed result has no vector column: {out_cols}")

    image_mode_label = "oss_url" if mode == "oss_url" else "base64"
    embed_rows: list[dict[str, Any]] = []
    for i, pack in enumerate(pack_rows):
        raw = pdf.iloc[i][vec_col] if i < len(pdf) else []
        vector = _normalize_embedding_vector(raw)
        if embedding_dimension > 0 and len(vector) > embedding_dimension:
            vector = vector[:embedding_dimension]
        topics = pack.get("source_topics")
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except json.JSONDecodeError:
                topics = []
        clip_id = str(pack.get("clip_id") or "")
        label = label_by_clip.get(clip_id) or {}
        if not label and pack.get("sdk_clip_id"):
            label = label_by_clip.get(str(pack.get("sdk_clip_id"))) or {}
        embed_rows.append(
            {
                "clip_id": clip_id,
                "sdk_clip_id": str(pack.get("sdk_clip_id") or ""),
                "bag_name": str(pack.get("bag_name") or ""),
                "start_timestamp_ns": int(pack.get("start_timestamp_ns") or 0),
                "end_timestamp_ns": int(pack.get("end_timestamp_ns") or 0),
                "duration_sec": float(pack.get("duration_sec") or 0.0),
                "model": embedding_model,
                "dimension": embedding_dimension,
                "embedding_type": "fusion",
                "embedding": vector,
                "source_topics": topics or [],
                "inputs": {
                    "text": rows_in[i]["text"] if i < len(rows_in) else "",
                    "asr_text": str(pack.get("asr_text") or ""),
                    "scene_summary": str(label.get("scene_summary") or ""),
                    "backend": "maxframe_mc",
                    "image_mode": image_mode_label,
                    "media_mode": mode,
                    "submitter": "driver_bare",
                },
                "usage": {},
                "request_id": "",
            }
        )
        print(f"DRIVER_EMBED_OK clip_id={clip_id} dim={len(vector)}")

    return {
        "row_count": len(embed_rows),
        "clip_ids": [r["clip_id"] for r in embed_rows],
        "media_mode": mode,
        "embed_rows": embed_rows,
    }


def embeddings_jsonl_body(embed_rows: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in embed_rows) + (
        "\n" if embed_rows else ""
    )
