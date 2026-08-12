# =============================================================================
# Driver-side bare MaxFrame AI ASR（不经 OMS SDK McAsrClient）
# 用于：DPE apply_chunk 只做 extract 后，在 Driver session 里跑 qwen3-asr-flash
#
# 注意：DataWorks o.account STS 通常无权直接 List/Get 业务桶；
# WAV 由 DPE 挂载侧列出/读出（base64）或传 OSS URL + 长期 AK。
# asr.jsonl 写回走 DPE 挂载（与 Job2 一致）。
# =============================================================================

from __future__ import annotations

import json
import re
from typing import Any


DEFAULT_ASR_MODEL = "qwen3-asr-flash"
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


def clip_id_from_audio_key(object_key: str) -> str:
    """SDK subclip id from a wav object key.

    Prefer the *innermost* ``.../clips/<id>/audio.wav`` (e.g. ``output_0000`` under
    ``_sdk_work``). Do **not** take the outer OSS prefix ``clips/{sha256}/runs/...``,
    which is the bag-level clip_id, not the SDK subclip directory name.
    """
    norm = object_key.replace("\\", "/").strip("/")
    rooted = "/" + norm
    m_work = re.search(r"/_sdk_work/.*/clips/([^/]+)/audio\.wav$", rooted)
    if m_work:
        return m_work.group(1)
    m_tail = re.search(r"/clips/([^/]+)/audio\.wav$", rooted)
    if m_tail:
        return m_tail.group(1)
    matches = re.findall(r"/clips/([^/]+)/", rooted)
    if matches:
        return matches[-1]
    return "clip_0"


def select_canonical_asr_audio_keys(wav_keys: list[str]) -> list[str]:
    """Pick one canonical wav per SDK subclip for ASR.

    Prefer ``_sdk_work/.../clips/*/audio.wav`` over ``preview/audio.wav`` (and any
    other duplicates). Never ASR both work-clip and preview for the same bag/clip.
    """
    keys = sorted(
        {str(k).replace("\\", "/").lstrip("/") for k in wav_keys if str(k).strip()}
    )
    if not keys:
        return []

    def _is_work_clip_wav(key: str) -> bool:
        rooted = "/" + key
        return bool(
            "/_sdk_work/" in rooted
            and re.search(r"/clips/[^/]+/audio\.wav$", rooted)
        )

    def _is_preview_wav(key: str) -> bool:
        rooted = "/" + key
        return "/preview/" in rooted or key.endswith("preview/audio.wav")

    preferred = [k for k in keys if _is_work_clip_wav(k)]
    pool = preferred or [k for k in keys if not _is_preview_wav(k)] or keys

    chosen: dict[str, str] = {}
    for key in pool:
        sdk_id = clip_id_from_audio_key(key)
        prev = chosen.get(sdk_id)
        if prev is None:
            chosen[sdk_id] = key
            continue
        # Prefer work-clip path if a weaker key was stored first.
        if _is_work_clip_wav(key) and not _is_work_clip_wav(prev):
            chosen[sdk_id] = key
        elif (not _is_preview_wav(key)) and _is_preview_wav(prev):
            chosen[sdk_id] = key
    return [chosen[sid] for sid in sorted(chosen)]


def parse_audio_keys_json(raw: Any) -> list[str]:
    if raw is None:
        return []
    text = str(raw).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return [text] if text.endswith("audio.wav") else []
    if isinstance(data, list):
        keys = [str(x).replace("\\", "/").lstrip("/") for x in data if str(x).strip()]
        return select_canonical_asr_audio_keys(keys)
    return []


def attach_asr_text_to_pack_rows(
    pack_rows: list[dict[str, Any]],
    asr_rows: list[dict[str, Any]],
    *,
    bag_clip_id: str = "",
) -> list[dict[str, Any]]:
    """Join ASR transcripts onto label/embed pack rows (by sdk_clip_id / clip_id)."""
    if not pack_rows or not asr_rows:
        return pack_rows
    asr_by: dict[str, dict[str, Any]] = {}
    for rec in asr_rows:
        if not isinstance(rec, dict):
            continue
        for key_name in ("sdk_clip_id", "clip_id"):
            key = str(rec.get(key_name) or "").strip()
            if key:
                asr_by[key] = rec
    bag = str(bag_clip_id or "").strip()
    for pack in pack_rows:
        if str(pack.get("asr_text") or "").strip():
            continue
        candidates = [
            str(pack.get("sdk_clip_id") or "").strip(),
            str(pack.get("clip_id") or "").strip(),
            bag,
        ]
        matched: dict[str, Any] | None = None
        for cand in candidates:
            if cand and cand in asr_by:
                matched = asr_by[cand]
                break
        if matched is None and len(asr_rows) == 1 and isinstance(asr_rows[0], dict):
            matched = asr_rows[0]
        if not matched:
            continue
        text = str(matched.get("text") or "").strip()
        if not text:
            continue
        pack["asr_text"] = text
        if matched.get("model"):
            pack["asr_model"] = str(matched.get("model"))
    return pack_rows


def oss_internal_audio_url(*, cloud_region: str, bucket: str, object_key: str) -> str:
    """Build MaxFrame-compatible internal OSS URL (audio / image / any object)."""
    region_id = cloud_region.replace("_", "-")
    key = str(object_key).replace("\\", "/").lstrip("/")
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/{key}"


# Alias used by label/embed URL builders (same format as ASR).
oss_internal_object_url = oss_internal_audio_url


def image_mime_from_key(object_key: str) -> str:
    lower = str(object_key or "").lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".webp"):
        return "image/webp"
    if lower.endswith(".gif"):
        return "image/gif"
    return "image/jpeg"


def resolve_driver_oss_ak_sk(get_arg: Any) -> dict[str, str] | None:
    """Long-term OSS AK/SK for MaxFrame audio OSS URL (Job2 oss_vl_* pattern)."""
    ak = (
        (get_arg("oss_vl_access_key_id") or get_arg("oss_access_key_id") or "")
        or ""
    ).strip()
    sk = (
        (get_arg("oss_vl_access_key_secret") or get_arg("oss_access_key_secret") or "")
        or ""
    ).strip()
    if ak and sk and not ak.startswith("STS."):
        return {"access_key_id": ak, "access_key_secret": sk}
    return None


def resolve_ai_media_mode(
    get_arg: Any,
    *,
    oss_ak: dict[str, str] | None = None,
) -> str:
    """Choose Driver AI media transport: ``oss_url`` or ``dpe_base64``.

    Param precedence (first non-empty):
    ``ai_media_mode`` → ``label_image_mode`` → ``label_media_mode`` → ``embed_media_mode``.

    ``auto`` (default): ``oss_url`` when long-term OSS AK is present, else ``dpe_base64``.
    """
    raw = (
        get_arg("ai_media_mode")
        or get_arg("label_image_mode")
        or get_arg("label_media_mode")
        or get_arg("embed_media_mode")
        or "auto"
    )
    resolved = str(raw or "auto").strip().lower()
    ak = oss_ak if oss_ak is not None else resolve_driver_oss_ak_sk(get_arg)
    if resolved in ("auto", ""):
        return "oss_url" if ak else "dpe_base64"
    if resolved in ("oss_url", "url"):
        if not ak:
            raise ValueError(
                "ai_media_mode=oss_url requires long-term OSS AK/SK "
                "(oss_vl_access_key_id + oss_vl_access_key_secret, or oss_access_key_*)"
            )
        return "oss_url"
    if resolved in ("base64", "dpe_base64", "b64"):
        return "dpe_base64"
    raise ValueError(
        f"ai_media_mode must be auto|oss_url|base64, got {raw!r}"
    )


def configure_driver_mc_ai_session(
    *,
    inference_quota_name: str | None = None,
    dpe_image_for_ai: str | None = None,
) -> None:
    """Driver 裸调 AI：与官方 demo / Job2 一致（DPE+MCSQL，勿沿用 extract 的「仅 DPE」）。"""
    from maxframe.config import options as mf_options

    mf_options.local_execution.enabled = False
    mf_options.dag.settings = {
        "engine_order": ["DPE", "MCSQL"],
        "unavailable_engines": ["SPE"],
    }
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    sql_settings["odps.sql.using.public.model"] = "true"
    if dpe_image_for_ai and str(dpe_image_for_ai).strip():
        sql_settings["odps.session.image"] = str(dpe_image_for_ai).strip()
    else:
        sql_settings.pop("odps.session.image", None)
    mf_options.sql.settings = sql_settings
    if inference_quota_name and str(inference_quota_name).strip():
        mf_options.session.inference_quota_name = str(inference_quota_name).strip()


def ensure_odps_catalog_for_driver(odps_entry: Any, catalog_endpoint: str | None) -> None:
    if odps_entry is None or not catalog_endpoint:
        return
    cat = str(catalog_endpoint).strip()
    if not cat.startswith(("http://", "https://")):
        cat = f"http://{cat.lstrip('/')}"
    odps_entry._catalog_endpoint = cat.rstrip("/")
    odps_entry._catalog_rest = None


def build_asr_input_rows_from_b64(
    items: list[dict[str, str]],
) -> list[dict[str, str]]:
    """items: {clip_id?, sdk_clip_id?, audio_oss_key, audio_b64}."""
    rows: list[dict[str, str]] = []
    for item in items:
        b64 = str(item.get("audio_b64") or "")
        key = str(item.get("audio_oss_key") or "")
        sdk_clip_id = str(
            item.get("sdk_clip_id") or clip_id_from_audio_key(key)
        ).strip()
        clip_id = str(item.get("clip_id") or sdk_clip_id).strip()
        rows.append(
            {
                "clip_id": clip_id,
                "sdk_clip_id": sdk_clip_id,
                "audio_url": f"data:audio/wav;base64,{b64}",
                "audio_oss_key": key,
            }
        )
    return rows


def build_asr_input_rows_from_oss_keys(
    wav_keys: list[str],
    *,
    bucket: str,
    cloud_region: str,
    bag_clip_id: str = "",
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    bag = str(bag_clip_id or "").strip()
    for key in select_canonical_asr_audio_keys(wav_keys):
        sdk_clip_id = clip_id_from_audio_key(key)
        rows.append(
            {
                "clip_id": bag or sdk_clip_id,
                "sdk_clip_id": sdk_clip_id,
                "audio_url": oss_internal_audio_url(
                    cloud_region=cloud_region, bucket=bucket, object_key=key
                ),
                "audio_oss_key": key,
            }
        )
    return rows


def driver_bare_asr_generate(
    odps_entry: Any,
    *,
    rows_in: list[dict[str, str]],
    asr_model: str = DEFAULT_ASR_MODEL,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    catalog_endpoint: str | None = None,
    inference_quota_name: str | None = None,
    parallel_partitions: int = 1,
    audio_storage_options: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run MaxFrame AI ASR on prebuilt audio_url rows; return asr_rows (no OSS write)."""
    import pandas as pd
    import maxframe.dataframe as md
    from maxframe.learn.utils import read_odps_model
    from maxframe.session import new_session

    if not rows_in:
        raise FileNotFoundError("no ASR audio rows (extract must leave audio.wav)")

    configure_driver_mc_ai_session(inference_quota_name=inference_quota_name)
    ensure_odps_catalog_for_driver(odps_entry, catalog_endpoint)

    try:
        model_obj = odps_entry.get_model(asr_model, modelset_project, None)
        model_obj.reload()
        fmt = getattr(getattr(model_obj, "type", None), "value", None) or getattr(
            model_obj, "type", "?"
        )
        tasks = list(getattr(model_obj, "tasks", None) or [])
        print(f"DRIVER_ASR_MODEL_META format={fmt} tasks={tasks}")
    except Exception as meta_exc:  # noqa: BLE001
        print(f"DRIVER_ASR_MODEL_META_WARN {type(meta_exc).__name__}: {meta_exc}")

    llm = read_odps_model(asr_model, project=modelset_project, odps_entry=odps_entry)
    clip_ids = [str(r["clip_id"]) for r in rows_in]
    sdk_clip_ids = [
        str(r.get("sdk_clip_id") or r.get("clip_id") or "") for r in rows_in
    ]
    for r in rows_in:
        url = str(r.get("audio_url") or "")
        mode = "b64" if url.startswith("data:") else "oss_url"
        print(
            f"DRIVER_ASR_WAV clip_id={r.get('clip_id')} "
            f"sdk_clip_id={r.get('sdk_clip_id') or r.get('clip_id')} "
            f"key={r.get('audio_oss_key')} mode={mode}"
        )

    # new_session BEFORE md.DataFrame so tunnel upload uses ODPS session (not local).
    session = new_session(odps_entry)
    try:
        print(f"DRIVER_ASR_LOGVIEW={session.get_logview_address()}")
        df = md.DataFrame(pd.DataFrame(rows_in))
        if parallel_partitions > 1:
            df = df.mf.rebalance(num_partitions=min(parallel_partitions, len(rows_in)))

        params: dict[str, Any] = {"asr_options": {"enable_itn": True, "language": "zh"}}
        gen_kwargs: dict[str, Any] = {"simple_output": True, "params": params}

        if hasattr(llm, "content_part"):
            from maxframe.learn.contrib.llm import AudioContentType

            cp = llm.content_part
            audio_part: dict[str, Any] = {
                "data": getattr(df, "audio_url"),
                "type": AudioContentType.URL,
                "mime_type": "audio/wav",
            }
            if audio_storage_options:
                audio_part["storage_options"] = {
                    "access_key_id": audio_storage_options["access_key_id"],
                    "access_key_secret": audio_storage_options["access_key_secret"],
                }
            messages = [{"role": "user", "content": [cp.audio(**audio_part)]}]
            mc_mode = "content_part_audio"
        else:
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_audio", "input_audio": {"data": "{audio_url}"}}
                    ],
                }
            ]
            mc_mode = "legacy_input_audio"

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
        raise RuntimeError(f"ASR result has no text column: {out_cols}")

    asr_rows: list[dict[str, Any]] = []
    for i, clip_id in enumerate(clip_ids):
        raw = pdf.iloc[i][text_col] if i < len(pdf) else ""
        text = _normalize_llm_output(raw)
        sdk_clip_id = sdk_clip_ids[i] if i < len(sdk_clip_ids) else clip_id
        asr_rows.append(
            {
                "clip_id": clip_id,
                "sdk_clip_id": sdk_clip_id,
                "model": asr_model,
                "text": text,
                "sentences": None,
                "request_id": "",
                "usage": None,
                "backend": "maxframe_mc",
                "mc_mode": mc_mode,
                "skipped": False,
                "submitter": "driver_bare",
            }
        )

    return {
        "row_count": len(asr_rows),
        "clip_ids": clip_ids,
        "sdk_clip_ids": sdk_clip_ids,
        "mc_mode": mc_mode,
        "texts": [r["text"] for r in asr_rows],
        "asr_rows": asr_rows,
    }



def asr_jsonl_body(asr_rows: list[dict[str, Any]]) -> str:
    return "\n".join(json.dumps(row, ensure_ascii=False) for row in asr_rows) + (
        "\n" if asr_rows else ""
    )


# Back-compat aliases used by older call sites / docs
def _clip_id_from_audio_key(object_key: str) -> str:
    return clip_id_from_audio_key(object_key)


def driver_bare_asr_for_run(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise RuntimeError(
        "driver_bare_asr_for_run(oss_client download) removed: "
        "DataWorks o.account STS cannot access the business OSS bucket. "
        "Use extract audio_keys_json + driver_bare_asr_generate + DPE write."
    )
