from __future__ import annotations

# job3_label_node.py — paste this single file into DataWorks PyODPS3

# === BEGIN mf_ai_function.py (auto-bundled) ===
"""MaxFrame AI Function helpers for DataWorks Job2/3/4 nodes.

Paste into PyODPS nodes via:
  python scripts/bundle_dataworks_node.py dataworks/job2_asr_node.py

Do not import business modules from DPE UDF; call these from Driver only.
"""


import json
import re
from typing import Any

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options

# Models loaded via read_odps_model (Token Quota / 百炼公共模型集)
_DASHSCOPE_MODEL_HINTS = (
    "qwen3.",
    "qwen3-",
    "qwen3-vl",
    "qwen-vl",  # qwen-vl-max-latest 等百炼 VL（Token Quota，不用 CU/GU）
    "text-embedding",
    "deepseek-v4",
    "deepseek-v3",
    "embedding",
    "paraformer",
    "sensevoice",
)

DEFAULT_ASR_MODEL = "qwen3-asr-flash"
DEFAULT_MODELSET_PROJECT = "bigdata_public_modelset"


def is_asr_capable_model(model_name: str) -> bool:
    lower = model_name.lower()
    return any(hint in lower for hint in ("asr", "paraformer", "sensevoice", "fun-asr"))


def resolve_asr_model(model_name: str) -> str:
    """Return ASR model name as configured; no silent remap to unregistered models."""
    return (model_name or "").strip()


def _normalize_llm_output(raw: Any) -> str:
    """Extract plain text from MaxFrame simple_output or raw chat.completion JSON."""
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
    if not text:
        return ""
    if text.startswith("{") and "choices" in text:
        try:
            return _normalize_llm_output(json.loads(text))
        except json.JSONDecodeError:
            pass
    return text


_ASR_FAILURE_PHRASES = (
    "无法转写",
    "无法访问",
    "无法处理",
    "cannot transcribe",
    "cannot access",
)


def _is_asr_failure_message(text: str) -> bool:
    cleaned = (text or "").strip()
    if not cleaned:
        return True
    lower = cleaned.lower()
    return any(phrase in cleaned for phrase in _ASR_FAILURE_PHRASES) or any(
        phrase in lower for phrase in _ASR_FAILURE_PHRASES
    )


def extract_asr_plain_text(raw: Any) -> str:
    """Plain transcript from asr_text (plain string or chat.completion JSON)."""
    text = _normalize_llm_output(raw)
    if _is_asr_failure_message(text):
        return ""
    return text


def normalize_oss_object_key(relpath: str) -> str:
    """Normalize manifest/image paths to OSS object keys under the bucket."""
    raw = str(relpath or "").strip().lstrip("/")
    if raw.startswith("output/clips/"):
        return raw[len("output/") :]
    parsed_marker = "/parsed/"
    if parsed_marker in raw:
        clips_idx = raw.find("clips/")
        if clips_idx >= 0:
            return raw[clips_idx:]
    return raw


def oss_key_for_frame_image(
    image_relpath: str,
    *,
    parsed_relpath: str | None = None,
) -> str:
    """Build OSS object key for a sampled frame image."""
    key = normalize_oss_object_key(image_relpath)
    if key.startswith("clips/"):
        return key
    prefix = str(parsed_relpath or "").strip("/")
    rel = key.lstrip("/")
    if prefix and rel:
        return f"{prefix}/{rel}"
    return rel or key


def _account_security_token(account: Any) -> str:
    for attr in ("sts_token", "security_token", "token"):
        value = getattr(account, attr, None)
        if value:
            return str(value)
    return ""


def ai_image_storage_options(account: Any) -> dict[str, str]:
    """Long-term AK/SK or STS triple for MaxFrame VL IMAGE_URL reads."""
    access_id = str(account.access_id)
    opts: dict[str, str] = {
        "access_key_id": access_id,
        "access_key_secret": str(account.secret_access_key),
    }
    token = _account_security_token(account)
    if token:
        opts["security_token"] = token
    return opts


def resolve_vl_storage_options(
    storage_options: dict[str, str] | None,
    odps_entry: Any,
    *,
    role_arn: str | None = None,
) -> dict[str, str]:
    """Resolve OSS AK/SK for ``cp.image(IMAGE_URL)``.

    MaxFrame VL **only** accepts ``access_key_id`` + ``access_key_secret`` here.
    ``role_arn`` is for DPE ``@with_fs_mount`` only and must not be passed to
    ``cp.image``. DataWorks ``o.account`` is often STS (``STS.*``) and needs
    explicit long-term OSS AK/SK via workflow params.
    """
    del role_arn  # mount-only; never forward to cp.image

    opts = dict(storage_options or {})
    ak = str(opts.get("access_key_id") or "").strip()
    sk = str(opts.get("access_key_secret") or "").strip()
    if ak and sk:
        if opts.get("security_token") or not ak.startswith("STS."):
            return {"access_key_id": ak, "access_key_secret": sk}

    account = getattr(odps_entry, "account", None)
    if account is not None:
        resolved = ai_image_storage_options(account)
        if resolved.get("security_token") or not resolved["access_key_id"].startswith("STS."):
            return resolved

    raise ValueError(
        "VL IMAGE_URL requires long-term OSS access_key_id/access_key_secret "
        "(workflow: oss_vl_access_key_id + oss_vl_access_key_secret). "
        "oss_ram_role_arn is for DPE mount only, not MaxFrame cp.image."
    )


def _infer_label_status(values: dict[str, Any]) -> str:
    if not values:
        return "empty"
    raw = values.get("raw")
    if len(values) == 1 and isinstance(raw, str) and raw.strip():
        lower = raw.lower()
        if any(
            phrase in lower
            for phrase in (
                "storage_options",
                "access_key",
                "invalidaccesskeyid",
                "must include",
                "error",
                "exception",
                "cannot access",
                "'status': 403",
            )
        ):
            return "error"
    return "ok"


def _frames_have_base64(frames: list[dict[str, Any]]) -> bool:
    return any(str(frame.get("image_base64") or "").strip() for frame in frames)


def build_vl_oss_storage_options(
    *,
    role_arn: str | None = None,
    oss_access_key_id: str | None = None,
    oss_access_key_secret: str | None = None,
) -> dict[str, str] | None:
    """Build ``storage_options`` for ``cp.image(IMAGE_URL)`` (AK/SK only)."""
    del role_arn  # mount-only
    ak = (oss_access_key_id or "").strip()
    sk = (oss_access_key_secret or "").strip()
    if ak and sk:
        return {"access_key_id": ak, "access_key_secret": sk}
    return None


def vl_oss_auth_available(
    *,
    role_arn: str | None = None,
    oss_access_key_id: str | None = None,
    oss_access_key_secret: str | None = None,
) -> bool:
    del role_arn
    ak = (oss_access_key_id or "").strip()
    sk = (oss_access_key_secret or "").strip()
    return bool(ak and sk and not ak.startswith("STS."))


def resolve_label_image_mode(
    mode: str,
    role_arn: str | None = None,
    *,
    oss_access_key_id: str | None = None,
    oss_access_key_secret: str | None = None,
) -> str:
    """auto: oss_url when RAM role or long-term OSS AK/SK is configured, else base64."""
    resolved = (mode or "auto").strip().lower()
    if resolved == "auto":
        if vl_oss_auth_available(
            role_arn=role_arn,
            oss_access_key_id=oss_access_key_id,
            oss_access_key_secret=oss_access_key_secret,
        ):
            return "oss_url"
        return "base64"
    if resolved not in ("base64", "oss_url"):
        raise ValueError(f"label_image_mode must be auto|base64|oss_url, got {mode!r}")
    return resolved


def resolve_ai_parallel_partitions(frame_count: int, requested: int) -> int:
    """Scale MCSQL row-parallelism up to frame count (cap 32)."""
    count = max(int(frame_count or 0), 1)
    req = max(int(requested or 1), 1)
    return min(count, max(req, min(8, count)), 32)


def build_label_prompt(taxonomy: dict[str, Any], *, compact: bool = True) -> str:
    labels = taxonomy.get("labels") or []
    if compact:
        parts = []
        for item in labels:
            label_id = str(item.get("id") or "").strip()
            if not label_id:
                continue
            value_schema = item.get("value_schema") or {}
            schema_type = str(value_schema.get("type") or "string")
            parts.append(f"{label_id}:{schema_type}")
        label_block = ", ".join(parts)
        return (
            "根据 OMS taxonomy 为座舱图像打标，严格输出 JSON 对象，key 为 label id，value 符合 schema 类型。\n"
            f"Labels: {label_block}"
        )
    label_lines = []
    for item in labels:
        label_lines.append(f"- {item.get('id')}: {item.get('name')} ({item.get('definition')})")
    return (
        "根据 OMS taxonomy 为座舱图像打标，严格输出 JSON 对象，key 为 label id，value 符合 schema。\n"
        + "\n".join(label_lines)
    )


def ensure_odps_catalog_endpoint(odps_entry: Any) -> None:
    """DataWorks internal ODPS may resolve catalog host without http(s) scheme."""
    if odps_entry is None:
        return
    try:
        catalog = odps_entry.catalog_endpoint
    except Exception:
        catalog = getattr(odps_entry, "_catalog_endpoint", None)
    if not catalog:
        return
    catalog_str = str(catalog).strip()
    if catalog_str.startswith(("http://", "https://")):
        return
    odps_entry._catalog_endpoint = f"https://{catalog_str.lstrip('/')}"
    odps_entry._catalog_rest = None


def configure_mf_ai_engine(*, dpe_image: str | None = None) -> None:
    """Switch session to DPE + MCSQL for MaxFrame AI Function."""
    mf_options.dag.settings = {
        "engine_order": ["DPE", "MCSQL"],
        "unavailable_engines": ["SPE"],
    }
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings


def apply_ai_quota(
    *,
    cu_quota_name: str | None = None,
    gu_quota_name: str | None = None,
    model_name: str | None = None,
) -> None:
    """CU/GU quota for ManagedTextLLM; skip for 百炼公共模型集 Token Quota models."""
    if model_name and is_public_modelset_model(model_name):
        return
    if gu_quota_name:
        mf_options.session.gu_quota_name = gu_quota_name
    if cu_quota_name:
        mf_options.session.quota_name = cu_quota_name


def prepare_mf_ai_runtime(
    *,
    model_name: str,
    dpe_image: str | None = None,
    cu_quota_name: str | None = None,
    gu_quota_name: str | None = None,
) -> None:
    """Configure AI engine + quota before new_session(); do not call after session exists."""
    configure_mf_ai_engine(dpe_image=dpe_image)
    apply_ai_quota(
        cu_quota_name=cu_quota_name,
        gu_quota_name=gu_quota_name,
        model_name=model_name,
    )


def is_public_modelset_model(model_name: str) -> bool:
    if is_asr_capable_model(model_name):
        return False
    lower = model_name.lower()
    return any(hint in lower for hint in _DASHSCOPE_MODEL_HINTS)


def create_ai_model(
    model_name: str,
    odps_entry: Any,
    *,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    api_key_resource: str = "",
):
    """Create ManagedTextLLM (CU/GU) or read_odps_model (Token Quota)."""
    if is_public_modelset_model(model_name):
        from maxframe.learn.utils import read_odps_model

        ensure_odps_catalog_endpoint(odps_entry)
        return read_odps_model(model_name, project=modelset_project, odps_entry=odps_entry)
    from maxframe.learn.contrib.llm.models.managed import ManagedTextLLM

    return ManagedTextLLM(name=model_name)


def _rebalance_df(df: md.DataFrame, parallel_partitions: int) -> md.DataFrame:
    if parallel_partitions <= 1:
        return df
    return df.mf.rebalance(num_partitions=parallel_partitions)


def _output_column(columns: list[str], preferred: tuple[str, ...]) -> str:
    for name in preferred:
        if name in columns:
            return name
    for name in columns:
        if name not in {"success", "index"}:
            return name
    if columns:
        return columns[0]
    raise ValueError("AI Function result has no output columns")


def _fetch_series(result_df: md.DataFrame, preferred: tuple[str, ...]) -> list[Any]:
    pdf = result_df.execute().fetch()
    columns = list(pdf.columns)
    col = _output_column(columns, preferred)
    if col not in columns:
        raise ValueError(f"AI output column {col!r} not in {columns}")
    return pdf[col].tolist()


def build_ai_running_options(
    *,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> dict[str, Any] | None:
    running_options: dict[str, Any] = {}
    if total_rpm_limit and total_rpm_limit > 0:
        running_options["total_rpm_limit"] = total_rpm_limit
    if request_timeout and request_timeout > 0:
        running_options["request_timeout"] = request_timeout
    if ai_memory and str(ai_memory).strip():
        running_options["memory"] = str(ai_memory).strip()
    return running_options or None


def ai_embed_texts(
    texts: list[str],
    model_name: str,
    odps_entry: Any,
    *,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    parallel_partitions: int = 1,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[list[float]]:
    if not texts:
        return []
    if not model_name:
        raise ValueError("ai_embed_texts requires model_name")

    llm = create_ai_model(model_name, odps_entry, modelset_project=modelset_project)
    df = _rebalance_df(
        md.DataFrame(pd.DataFrame({"text": texts})),
        parallel_partitions,
    )
    embed_kwargs: dict[str, Any] = {"simple": True}
    running_options = build_ai_running_options(
        total_rpm_limit=total_rpm_limit,
        request_timeout=request_timeout,
        ai_memory=ai_memory,
    )
    if running_options:
        embed_kwargs["running_options"] = running_options
    result = llm.embed(df["text"], **embed_kwargs)
    outputs = _fetch_series(result, ("output", "embedding", "embeddings", "vector"))

    vectors: list[list[float]] = []
    for item in outputs:
        if item is None:
            vectors.append([])
            continue
        if isinstance(item, list):
            vectors.append([float(x) for x in item])
            continue
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
                if isinstance(parsed, list):
                    vectors.append([float(x) for x in parsed])
                    continue
            except json.JSONDecodeError:
                pass
        vectors.append([])
    return vectors


def is_vl_embedding_model(model_name: str) -> bool:
    lower = (model_name or "").lower()
    return "vl" in lower and "embed" in lower


def ai_embed_oss_image_urls(
    image_urls: list[str],
    model_name: str,
    odps_entry: Any,
    *,
    storage_options: dict[str, str] | None = None,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    parallel_partitions: int = 1,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[list[float]]:
    """Embed OSS images via VL embedding model + IMAGE_URL."""
    if not image_urls:
        return []
    if not model_name:
        raise ValueError("ai_embed_oss_image_urls requires model_name")

    vl_storage_options = resolve_vl_storage_options(storage_options, odps_entry)
    llm = create_ai_model(model_name, odps_entry, modelset_project=modelset_project)
    df = _rebalance_df(
        md.DataFrame(pd.DataFrame({"image_url": image_urls})),
        parallel_partitions,
    )
    embed_kwargs: dict[str, Any] = {}
    running_options = build_ai_running_options(
        total_rpm_limit=total_rpm_limit,
        request_timeout=request_timeout,
        ai_memory=ai_memory,
    )
    if running_options:
        embed_kwargs["running_options"] = running_options

    if hasattr(llm, "content_part"):
        from maxframe.learn.contrib.llm import ImageContentType

        cp = llm.content_part
        image_input = [
            cp.image(
                data=df.image_url,
                type=ImageContentType.IMAGE_URL,
                storage_options=vl_storage_options,
            ),
        ]
        result = llm.embed(df, input=image_input, simple_output=True, **embed_kwargs)
    else:
        text_embed_kwargs: dict[str, Any] = {"simple": True, **embed_kwargs}
        try:
            result = llm.embed(
                df.image_url,
                storage_options=vl_storage_options,
                **text_embed_kwargs,
            )
        except TypeError:
            result = llm.embed(df.image_url, **text_embed_kwargs)

    outputs = _fetch_series(result, ("output", "embedding", "embeddings", "vector"))
    vectors: list[list[float]] = []
    for item in outputs:
        if item is None:
            vectors.append([])
            continue
        if isinstance(item, list):
            vectors.append([float(x) for x in item])
            continue
        if isinstance(item, str):
            try:
                parsed = json.loads(item)
                if isinstance(parsed, list):
                    vectors.append([float(x) for x in parsed])
                    continue
            except json.JSONDecodeError:
                pass
        vectors.append([])
    return vectors


def ai_generate_texts(
    rows: list[dict[str, Any]],
    model_name: str,
    odps_entry: Any,
    *,
    prompt_template: list[dict[str, Any]],
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    parallel_partitions: int = 1,
    params: dict[str, Any] | None = None,
) -> list[str]:
    if not rows:
        return []
    if not model_name:
        raise ValueError("ai_generate_texts requires model_name")

    llm = create_ai_model(model_name, odps_entry, modelset_project=modelset_project)
    df = _rebalance_df(md.DataFrame(pd.DataFrame(rows)), parallel_partitions)
    if hasattr(llm, "generate"):
        try:
            result = llm.generate(df, messages=prompt_template, params=params or {})
        except TypeError:
            result = llm.generate(df, prompt_template=prompt_template, params=params or {})
    else:
        raise ValueError(f"Model {model_name} has no generate()")
    outputs = _fetch_series(result, ("output", "generated_text", "text", "content", "response"))
    return [_normalize_llm_output(item) for item in outputs]


def ai_extract_texts(
    texts: list[str],
    model_name: str,
    odps_entry: Any,
    *,
    schema: dict[str, Any],
    description: str,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    parallel_partitions: int = 1,
    examples: list[tuple[str, str]] | None = None,
) -> list[dict[str, Any]]:
    if not texts:
        return []
    if not model_name:
        raise ValueError("ai_extract_texts requires model_name")

    llm = create_ai_model(model_name, odps_entry, modelset_project=modelset_project)
    series = md.Series(texts)
    if parallel_partitions > 1:
        series = _rebalance_df(series.to_frame("text"), parallel_partitions)["text"]
    result = llm.extract(
        series,
        description=description,
        schema=schema,
        examples=examples or [],
    )
    outputs = _fetch_series(result, ("output",))
    parsed: list[dict[str, Any]] = []
    for item in outputs:
        if isinstance(item, dict):
            parsed.append(item)
        elif isinstance(item, str) and item.strip():
            try:
                loaded = json.loads(item)
                parsed.append(loaded if isinstance(loaded, dict) else {"raw": item})
            except json.JSONDecodeError:
                parsed.append({"raw": item})
        else:
            parsed.append({})
    return parsed


def ai_transcribe_segments(
    segments: list[dict[str, Any]],
    model_name: str,
    odps_entry: Any,
    *,
    language: str,
    cloud_region: str,
    oss_bucket: str,
    storage_options: dict[str, str] | None = None,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    parallel_partitions: int = 1,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    """ASR via Qwen-ASR + input_audio (OSS wav URL). Not text LLM + URL in prompt."""
    if not model_name:
        return [
            {
                **segment,
                "asr_text": "",
                "confidence": 0.0,
            }
            for segment in segments
        ]

    asr_model = resolve_asr_model(model_name)
    if not is_asr_capable_model(asr_model):
        print(
            f"WARN: asr_model={asr_model!r} is not an ASR model; "
            f"input_audio may fail or return errors. "
            f"Register qwen3-asr-flash in {DEFAULT_MODELSET_PROJECT} or set asr_model empty for stub."
        )

    region_id = cloud_region.replace("_", "-")
    rows: list[dict[str, Any]] = []
    for segment in segments:
        audio_relpath = str(segment.get("audio_relpath") or "").strip("/")
        if not segment.get("wav_available") or not audio_relpath:
            rows.append(
                {
                    "segment_id": int(segment["segment_id"]),
                    "audio_url": "",
                }
            )
            continue
        rows.append(
            {
                "segment_id": int(segment["segment_id"]),
                "audio_url": f"oss://oss-{region_id}-internal.aliyuncs.com/{oss_bucket}/{audio_relpath}",
            }
        )

    llm = create_ai_model(asr_model, odps_entry, modelset_project=modelset_project)
    df = _rebalance_df(md.DataFrame(pd.DataFrame(rows)), parallel_partitions)

    asr_options: dict[str, Any] = {"enable_itn": True}
    lang = (language or "").strip()
    if lang:
        asr_options["language"] = lang.split("-")[0].lower()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_audio",
                    "input_audio": {"data": "{audio_url}"},
                }
            ],
        }
    ]
    params: dict[str, Any] = {"asr_options": asr_options}
    oss_opts: dict[str, str] | None = None
    if storage_options:
        oss_opts = resolve_vl_storage_options(storage_options, odps_entry)

    def _run_asr_generate(**extra: Any) -> md.DataFrame:
        gen_kwargs: dict[str, Any] = {"simple_output": True, "params": params, **extra}
        running_options = build_ai_running_options(
            total_rpm_limit=total_rpm_limit,
            request_timeout=request_timeout,
            ai_memory=ai_memory,
        )
        if running_options:
            gen_kwargs["running_options"] = running_options
        try:
            return llm.generate(df, messages=messages, **gen_kwargs)
        except TypeError:
            return llm.generate(df, prompt_template=messages, **gen_kwargs)

    if hasattr(llm, "generate"):
        if oss_opts:
            try:
                result = _run_asr_generate(storage_options=oss_opts)
            except TypeError:
                result = _run_asr_generate()
        else:
            result = _run_asr_generate()
    else:
        raise ValueError(f"ASR model {asr_model} has no generate()")

    outputs = _fetch_series(result, ("output", "generated_text", "text", "content", "response"))
    texts = [_normalize_llm_output(item) for item in outputs]

    results: list[dict[str, Any]] = []
    for segment, text in zip(segments, texts):
        has_audio = bool(segment.get("wav_available")) and bool(segment.get("audio_relpath"))
        cleaned = extract_asr_plain_text(text) if has_audio else ""
        failed = not cleaned
        results.append(
            {
                **segment,
                "asr_text": cleaned,
                "confidence": 0.0 if failed else 1.0,
            }
        )
    return results


def _taxonomy_to_extract_schema(taxonomy: dict[str, Any]) -> dict[str, str]:
    schema: dict[str, str] = {}
    for item in taxonomy.get("labels") or []:
        label_id = str(item.get("id") or "").strip()
        if not label_id:
            continue
        value_schema = item.get("value_schema") or {}
        schema[label_id] = str(value_schema.get("type") or "string")
    return schema


def build_sync_label_prompt(taxonomy: dict[str, Any], *, compact: bool = True) -> str:
    base = build_label_prompt(taxonomy, compact=compact)
    return (
        f"{base}\n"
        "本次输入为同一时刻四路相机（camera0~camera3）时间对齐帧，请综合四路视角输出一组 OMS 标签。"
        "严格输出单个 JSON 对象，不要按相机拆分。"
    )


def _sync_group_camera_columns(group: dict[str, Any]) -> list[dict[str, Any]]:
    frames = group.get("frames") or []
    return sorted(frames, key=lambda item: str(item.get("camera") or ""))


def ai_label_sync_groups_with_model(
    sync_groups: list[dict[str, Any]],
    model_name: str,
    odps_entry: Any,
    *,
    taxonomy: dict[str, Any],
    cloud_region: str,
    oss_bucket: str,
    storage_options: dict[str, str] | None = None,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    parallel_partitions: int = 1,
    parsed_relpath: str | None = None,
    role_arn: str | None = None,
    compact_prompt: bool = True,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    """One VL call per sync group with up to four aligned camera images."""
    if not model_name:
        return []
    if not sync_groups:
        return []

    region_id = cloud_region.replace("_", "-")
    llm = create_ai_model(model_name, odps_entry, modelset_project=modelset_project)
    partitions = resolve_ai_parallel_partitions(len(sync_groups), parallel_partitions)

    if is_public_modelset_model(model_name) and hasattr(llm, "content_part"):
        from maxframe.learn.contrib.llm import ImageContentType

        cp = llm.content_part
        prompt = build_sync_label_prompt(taxonomy, compact=compact_prompt)

        use_base64 = any(
            str(frame.get("image_base64") or "").strip()
            for group in sync_groups
            for frame in (group.get("frames") or [])
        )
        rows: list[dict[str, Any]] = []
        for group in sync_groups:
            ordered = _sync_group_camera_columns(group)
            row: dict[str, Any] = {"sync_group_id": group.get("sync_group_id")}
            for idx, frame in enumerate(ordered):
                if use_base64:
                    row[f"image_b64_{idx}"] = str(frame.get("image_base64") or "")
                else:
                    image_relpath = str(frame.get("image_relpath") or frame.get("image_path") or "")
                    frame_parsed_relpath = (
                        parsed_relpath or str(frame.get("parsed_relpath") or "").strip() or None
                    )
                    oss_key = oss_key_for_frame_image(
                        image_relpath,
                        parsed_relpath=frame_parsed_relpath,
                    )
                    row[f"image_url_{idx}"] = (
                        f"oss://oss-{region_id}-internal.aliyuncs.com/{oss_bucket}/{oss_key}"
                    )
            rows.append(row)

        df = _rebalance_df(md.DataFrame(pd.DataFrame(rows)), partitions)
        content_parts: list[Any] = [cp.text(prompt)]
        camera_count = max(len(_sync_group_camera_columns(group)) for group in sync_groups)
        if use_base64:
            for idx in range(camera_count):
                content_parts.append(
                    cp.image(
                        data=getattr(df, f"image_b64_{idx}"),
                        type=ImageContentType.BASE64,
                        mime_type="image/jpeg",
                    )
                )
        else:
            vl_storage_options = resolve_vl_storage_options(
                storage_options,
                odps_entry,
                role_arn=role_arn,
            )
            for idx in range(camera_count):
                content_parts.append(
                    cp.image(
                        data=getattr(df, f"image_url_{idx}"),
                        type=ImageContentType.IMAGE_URL,
                        storage_options=vl_storage_options,
                    )
                )

        generate_kwargs: dict[str, Any] = {
            "simple_output": True,
            "params": {"temperature": 0.2, "max_tokens": 2048},
        }
        running_options = build_ai_running_options(
            total_rpm_limit=total_rpm_limit,
            request_timeout=request_timeout,
            ai_memory=ai_memory,
        )
        if running_options:
            generate_kwargs["running_options"] = running_options
        result = llm.generate(
            df,
            messages=[{"role": "user", "content": content_parts}],
            **generate_kwargs,
        )
        outputs = _fetch_series(result, ("output", "generated_text", "text"))
        labeled: list[dict[str, Any]] = []
        for group, raw in zip(sync_groups, outputs):
            values: dict[str, Any] = {}
            text = str(raw or "").strip()
            if text:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    try:
                        loaded = json.loads(match.group(0))
                        if isinstance(loaded, dict):
                            values = loaded
                    except json.JSONDecodeError:
                        values = {"raw": text}
                else:
                    values = {"raw": text}
            labeled.append(
                {
                    "sync_group_id": group.get("sync_group_id"),
                    "values": values,
                    "status": _infer_label_status(values),
                }
            )
        return labeled

    schema = _taxonomy_to_extract_schema(taxonomy)
    description = "从四路相机对齐帧描述中提取 OMS 标签，输出 JSON object"
    prompts = []
    for group in sync_groups:
        ordered = _sync_group_camera_columns(group)
        parts = [
            f"{frame.get('camera')}:{frame.get('timestamp_ns')}"
            for frame in ordered
        ]
        prompts.append(
            f"sync_group_id={group.get('sync_group_id')} anchor={group.get('anchor_timestamp_ns')} "
            + " ".join(parts)
        )
    extracted = ai_extract_texts(
        prompts,
        model_name,
        odps_entry,
        schema=schema,
        description=description,
        modelset_project=modelset_project,
        parallel_partitions=parallel_partitions,
    )
    labeled = []
    for group, values in zip(sync_groups, extracted):
        labeled.append(
            {
                "sync_group_id": group.get("sync_group_id"),
                "values": values,
                "status": "ok",
            }
        )
    return labeled


def ai_label_frames_with_model(
    frames: list[dict[str, Any]],
    model_name: str,
    odps_entry: Any,
    *,
    taxonomy: dict[str, Any],
    cloud_region: str,
    oss_bucket: str,
    storage_options: dict[str, str] | None = None,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
    parallel_partitions: int = 1,
    parsed_relpath: str | None = None,
    role_arn: str | None = None,
    compact_prompt: bool = True,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    if not model_name:
        return []
    if not frames:
        return []

    region_id = cloud_region.replace("_", "-")
    llm = create_ai_model(model_name, odps_entry, modelset_project=modelset_project)
    partitions = resolve_ai_parallel_partitions(len(frames), parallel_partitions)

    # Prefer multimodal generate for vision models (qwen3.6-plus / VL).
    if is_public_modelset_model(model_name) and hasattr(llm, "content_part"):
        from maxframe.learn.contrib.llm import ImageContentType

        cp = llm.content_part
        prompt = build_label_prompt(taxonomy, compact=compact_prompt)

        use_base64 = _frames_have_base64(frames)
        if use_base64:
            rows = [
                {
                    "frame_id": frame.get("frame_id"),
                    "image_b64": str(frame.get("image_base64") or ""),
                }
                for frame in frames
            ]
            df = _rebalance_df(md.DataFrame(pd.DataFrame(rows)), partitions)
            image_part = cp.image(
                data=df.image_b64,
                type=ImageContentType.BASE64,
                mime_type="image/jpeg",
            )
        else:
            vl_storage_options = resolve_vl_storage_options(
                storage_options,
                odps_entry,
                role_arn=role_arn,
            )
            frame_parsed_relpath = (
                parsed_relpath or str(frames[0].get("parsed_relpath") or "").strip() or None
            )
            rows = []
            for frame in frames:
                image_relpath = str(frame.get("image_relpath") or frame.get("image_path") or "")
                oss_key = oss_key_for_frame_image(
                    image_relpath,
                    parsed_relpath=frame_parsed_relpath,
                )
                rows.append(
                    {
                        "frame_id": frame.get("frame_id"),
                        "image_url": f"oss://oss-{region_id}-internal.aliyuncs.com/{oss_bucket}/{oss_key}",
                    }
                )
            df = _rebalance_df(md.DataFrame(pd.DataFrame(rows)), partitions)
            image_part = cp.image(
                data=df.image_url,
                type=ImageContentType.IMAGE_URL,
                storage_options=vl_storage_options,
            )

        generate_kwargs: dict[str, Any] = {
            "simple_output": True,
            "params": {"temperature": 0.2, "max_tokens": 2048},
        }
        running_options = build_ai_running_options(
            total_rpm_limit=total_rpm_limit,
            request_timeout=request_timeout,
            ai_memory=ai_memory,
        )
        if running_options:
            generate_kwargs["running_options"] = running_options
        result = llm.generate(
            df,
            messages=[
                {
                    "role": "user",
                    "content": [
                        cp.text(prompt),
                        image_part,
                    ],
                }
            ],
            **generate_kwargs,
        )
        outputs = _fetch_series(result, ("output", "generated_text", "text"))
        labeled: list[dict[str, Any]] = []
        for frame, raw in zip(frames, outputs):
            values: dict[str, Any] = {}
            text = str(raw or "").strip()
            if text:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                if match:
                    try:
                        loaded = json.loads(match.group(0))
                        if isinstance(loaded, dict):
                            values = loaded
                    except json.JSONDecodeError:
                        values = {"raw": text}
                else:
                    values = {"raw": text}
            labeled.append(
                {
                    "frame_id": frame.get("frame_id"),
                    "values": values,
                    "status": _infer_label_status(values),
                }
            )
        return labeled

    # Text LLM: extract on placeholder prompts (no image bytes in series).
    schema = _taxonomy_to_extract_schema(taxonomy)
    description = "从座舱场景描述中提取 OMS 标签，输出 JSON object"
    prompts = [
        f"frame_id={frame.get('frame_id')} camera={frame.get('camera')} ts={frame.get('timestamp_ns')}"
        for frame in frames
    ]
    extracted = ai_extract_texts(
        prompts,
        model_name,
        odps_entry,
        schema=schema,
        description=description,
        modelset_project=modelset_project,
        parallel_partitions=parallel_partitions,
    )
    labeled = []
    for frame, values in zip(frames, extracted):
        labeled.append({"frame_id": frame.get("frame_id"), "values": values, "status": "ok"})
    return labeled
# === END mf_ai_function.py ===

# === BEGIN pipeline_dispatch.py (auto-bundled) ===
"""Pipeline dispatch: pick clip/run for scheduled DataWorks workflow.

**Primary (all DW editions):** ``job0_dispatch`` writes ``pipeline/dispatch/latest.json``
on OSS; downstream PyODPS nodes call ``resolve_pipeline_context()`` to read it.
No assignment node or node-context output params required.

Optional: hand-set ``clip_id``/``run_id`` in a node's parameter panel for single-clip debug.
Optional (DataWorks Standard+): assignment node + ``dispatch_json`` in args.
"""


import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import oss2
except ImportError:  # pragma: no cover - DataWorks driver often lacks oss2
    oss2 = None  # type: ignore[assignment]

try:
    import alibabacloud_oss_v2 as oss_v2
except ImportError:  # pragma: no cover
    oss_v2 = None  # type: ignore[assignment]

REQUIRED_PIPELINE_STEPS: tuple[str, ...] = (
    "job1_parse",
    "job2_sample",
    "job2_asr",
    "job3_label",
    "job4_embed",
)

DEFAULT_DISPATCH_OSS_KEY = "pipeline/dispatch/latest.json"

DISPATCH_OUTPUT_KEYS: tuple[str, ...] = (
    "action",
    "reason",
    "clip_id",
    "run_id",
    "clip_dir_name",
    "bag_oss_key",
)


_UNRESOLVED_DW_PLACEHOLDER = re.compile(r"^\$\{[^}]+\}$")


def is_unresolved_dw_placeholder(value: str | None) -> bool:
    if value is None:
        return False
    return bool(_UNRESOLVED_DW_PLACEHOLDER.match(str(value).strip()))


def read_skynet_task_input() -> dict[str, str]:
    """Read DataWorks node-context inputs from SKYNET_TASK_INPUT."""
    raw = (os.environ.get("SKYNET_TASK_INPUT") or "").strip()
    if not raw or raw == "{}":
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    resolved: dict[str, str] = {}
    for key, value in loaded.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text or is_unresolved_dw_placeholder(text):
            continue
        resolved[str(key)] = text
    return resolved


def read_pyodps_args() -> dict[str, str]:
    """Read resolved scheduling / node-context values injected into global ``args``."""
    try:
        node_args = args  # type: ignore[name-defined]
    except NameError:
        return {}
    if not isinstance(node_args, dict):
        return {}
    resolved: dict[str, str] = {}
    for key, value in node_args.items():
        if value is None:
            continue
        text = str(value).strip()
        if not text or is_unresolved_dw_placeholder(text):
            continue
        resolved[str(key)] = text
    return resolved


def resolve_node_param(
    name: str,
    get_arg: Callable[[str, str | None], str | None],
    default: str | None = None,
) -> str | None:
    """Resolve one param from args, SKYNET_TASK_INPUT, then get_arg (skip unresolved ${...})."""
    for candidate in (
        read_pyodps_args().get(name),
        read_skynet_task_input().get(name),
        get_arg(name, default),
    ):
        if candidate is None:
            continue
        text = str(candidate).strip()
        if not text or is_unresolved_dw_placeholder(text):
            continue
        return text
    return default if default is not None else None


def _sql_string_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_valid_ds(value: str) -> bool:
    return len(value) == 8 and value.isdigit()


def resolve_dispatch_ds(
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> str | None:
    ds = ""
    if get_arg is not None:
        ds = (resolve_node_param("ds", get_arg, "") or "").strip()
    if not ds or is_unresolved_dw_placeholder(ds) or ds.lower() == "bizdate":
        ds = (os.environ.get("SKYNET_BIZDATE") or "").strip()
    return ds if ds and _is_valid_ds(ds) else None


def _partition_ds_value(part_name: str) -> str:
    part_name = part_name.strip()
    if part_name.startswith("ds="):
        return part_name.split("=", 1)[1].strip().strip("'").strip('"')
    return part_name


def _list_ds_partitions_client(client: Any, table_name: str) -> list[str]:
    if not client.exist_table(table_name):
        return []
    table = client.get_table(table_name)
    if not table.table_schema.partitions:
        return []
    values = {_partition_ds_value(str(part.name)) for part in table.partitions}
    return sorted((v for v in values if _is_valid_ds(v)), reverse=True)


def _pipeline_step_ds_predicate(
    client: Any,
    table_name: str,
    get_arg: Callable[[str, str | None], str | None] | None,
) -> str:
    parts = _list_ds_partitions_client(client, table_name)
    if parts:
        recent = parts[:32]
        if len(recent) == 1:
            return f"ds = {_sql_string_literal(recent[0])}"
        in_list = ", ".join(_sql_string_literal(p) for p in recent)
        return f"ds IN ({in_list})"
    ds = resolve_dispatch_ds(get_arg)
    if not ds:
        raise ValueError(
            "pipeline_step query requires ds partition; set workflow ds=${bizdate} "
            "or rely on SKYNET_BIZDATE"
        )
    return f"ds = {_sql_string_literal(ds)}"


def is_pipeline_run_complete(
    client: Any,
    table_prefix: str,
    run_id: str,
    *,
    required_steps: tuple[str, ...] = REQUIRED_PIPELINE_STEPS,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> bool:
    if not run_id:
        return False
    table_name = f"{table_prefix}pipeline_step"
    ds_pred = _pipeline_step_ds_predicate(client, table_name, get_arg)
    sql = (
        f"SELECT step_id, MAX(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS ok "
        f"FROM {table_name} WHERE run_id = {_sql_string_literal(run_id)} "
        f"AND {ds_pred} "
        f"GROUP BY step_id"
    )
    completed: set[str] = set()
    with client.execute_sql(sql).open_reader() as reader:
        for row in reader:
            step_id = str(row[0])
            if int(row[1]) == 1:
                completed.add(step_id)
    return all(step in completed for step in required_steps)


def list_dim_clips(client: Any, table_prefix: str) -> list[dict[str, Any]]:
    table_name = f"{table_prefix}dim_clip"
    sql = (
        f"SELECT clip_id, clip_dir_name, content_hash, bag_oss_key, active_run_id, created_at "
        f"FROM {table_name} ORDER BY created_at ASC"
    )
    rows: list[dict[str, Any]] = []
    with client.execute_sql(sql).open_reader() as reader:
        for record in reader:
            rows.append(
                {
                    "clip_id": str(record[0]),
                    "clip_dir_name": str(record[1] or ""),
                    "content_hash": str(record[2] or ""),
                    "bag_oss_key": str(record[3] or ""),
                    "active_run_id": str(record[4] or "") or None,
                    "created_at": str(record[5] or ""),
                }
            )
    return rows


def pick_dispatch_target(
    client: Any,
    table_prefix: str,
    *,
    required_steps: tuple[str, ...] = REQUIRED_PIPELINE_STEPS,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any]:
    """Return dispatch payload with action=run|idle."""
    for clip in list_dim_clips(client, table_prefix):
        clip_id = clip["clip_id"]
        active_run_id = clip.get("active_run_id")
        if active_run_id and is_pipeline_run_complete(
            client,
            table_prefix,
            active_run_id,
            required_steps=required_steps,
            get_arg=get_arg,
        ):
            continue
        if active_run_id:
            run_id = active_run_id
            reason = "resume_incomplete"
        else:
            run_id = str(uuid.uuid4())
            reason = "new_run"
        return {
            "action": "run",
            "reason": reason,
            "clip_id": clip_id,
            "run_id": run_id,
            "clip_dir_name": clip.get("clip_dir_name") or "",
            "bag_oss_key": clip.get("bag_oss_key") or "",
            "content_hash": clip.get("content_hash") or "",
            "active_run_id_before": active_run_id,
            "dispatched_at": utc_now_iso(),
        }
    return {
        "action": "idle",
        "reason": "no_pending_clip",
        "clip_id": "",
        "run_id": "",
        "clip_dir_name": "",
        "bag_oss_key": "",
        "dispatched_at": utc_now_iso(),
    }


def _normalize_oss_region(region: str) -> str:
    return region.replace("_", "-")


def default_oss_http_endpoint(region: str, *, use_internal: bool = True) -> str:
    """Regional OSS HTTP endpoint; DataWorks/MaxCompute should use internal by default."""
    region_id = _normalize_oss_region(region)
    internal_suffix = "-internal" if use_internal else ""
    return f"https://oss-{region_id}{internal_suffix}.aliyuncs.com"


def resolve_oss_http_endpoint(
    region: str,
    get_arg: Callable[[str, str | None], str | None] | None = None,
    *,
    explicit_endpoint: str | None = None,
) -> str:
    endpoint = (explicit_endpoint or "").strip()
    if not endpoint and get_arg is not None:
        endpoint = (resolve_node_param("oss_endpoint", get_arg, "") or "").strip()
    if endpoint:
        return endpoint
    use_internal = True
    if get_arg is not None:
        raw = resolve_node_param("oss_use_internal", get_arg, "true") or "true"
        use_internal = str(raw).lower() not in {"0", "false", "no"}
    return default_oss_http_endpoint(region, use_internal=use_internal)


def _oss_credentials(account: Any) -> tuple[str, str]:
    access_id = getattr(account, "access_id", None) or getattr(account, "access_key_id", None)
    secret = getattr(account, "secret_access_key", None) or getattr(account, "access_key_secret", None)
    if not access_id or not secret:
        raise RuntimeError("OSS credentials missing on ODPS account")
    return str(access_id), str(secret)


def _account_security_token(account: Any) -> str:
    for attr in ("sts_token", "security_token", "token"):
        value = getattr(account, attr, None)
        if value:
            return str(value)
    return ""


def resolve_dispatch_oss_credentials(
    account: Any,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> tuple[str, str, str]:
    """Return (access_key_id, access_key_secret, security_token). Token may be empty."""
    if get_arg is not None:
        ak = (
            resolve_node_param("oss_vl_access_key_id", get_arg, "")
            or resolve_node_param("oss_access_key_id", get_arg, "")
            or ""
        ).strip()
        sk = (
            resolve_node_param("oss_vl_access_key_secret", get_arg, "")
            or resolve_node_param("oss_access_key_secret", get_arg, "")
            or ""
        ).strip()
        if ak and sk and not ak.startswith("STS."):
            return ak, sk, ""
    access_id, secret = _oss_credentials(account)
    token = _account_security_token(account)
    if access_id.startswith("STS.") and not token:
        raise RuntimeError(
            "OSS STS credentials from o.account require security_token; "
            "set oss_vl_access_key_id + oss_vl_access_key_secret in workflow params"
        )
    return access_id, secret, token


def _make_oss_v2_client(
    access_key_id: str,
    access_key_secret: str,
    *,
    region: str,
    endpoint: str | None = None,
    security_token: str | None = None,
) -> Any:
    if oss_v2 is None:
        raise RuntimeError("alibabacloud_oss_v2 is required for OSS dispatch I/O")
    cfg = oss_v2.config.load_default()
    if security_token:
        cfg.credentials_provider = oss_v2.credentials.StaticCredentialsProvider(
            access_key_id,
            access_key_secret,
            security_token,
        )
    else:
        cfg.credentials_provider = oss_v2.credentials.StaticCredentialsProvider(
            access_key_id,
            access_key_secret,
        )
    cfg.region = _normalize_oss_region(region)
    if endpoint:
        cfg.endpoint = endpoint
    return oss_v2.Client(cfg)


def _is_oss_object_missing(exc: BaseException) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 404:
        return True
    code = str(getattr(exc, "code", "") or "")
    if code in {"NoSuchKey", "NotFound"}:
        return True
    text = str(exc)
    return any(token in text for token in ("NoSuchKey", "404", "Not Found", "not found"))


def write_oss_object_bytes(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    body: bytes,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> None:
    """Write one OSS object from the DataWorks driver (no MaxFrame STRING tunnel limit)."""
    access_id, secret, token = resolve_dispatch_oss_credentials(account, get_arg=get_arg)
    if oss2 is not None:
        auth = (
            oss2.StsAuth(access_id, secret, token)
            if token
            else oss2.Auth(access_id, secret)
        )
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        bucket.put_object(object_key, body)
        return
    if oss_v2 is None:
        raise RuntimeError("oss2 or alibabacloud_oss_v2 is required to write OSS objects")
    client = _make_oss_v2_client(
        access_id,
        secret,
        region=region or "cn-shanghai",
        endpoint=endpoint,
        security_token=token or None,
    )
    client.put_object(
        oss_v2.PutObjectRequest(
            bucket=bucket_name,
            key=object_key,
            body=body,
        )
    )


def write_oss_object_text(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    text: str,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> None:
    write_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        body=text.encode("utf-8"),
        region=region,
        get_arg=get_arg,
    )


def write_dispatch_to_oss(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    payload: dict[str, Any],
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    write_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        body=body,
        region=region,
        get_arg=get_arg,
    )


def read_oss_object_bytes(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> bytes | None:
    """Read one OSS object on the DataWorks driver (no MaxFrame 8MB STRING tunnel limit)."""
    access_id, secret, token = resolve_dispatch_oss_credentials(account, get_arg=get_arg)
    if oss2 is not None:
        auth = (
            oss2.StsAuth(access_id, secret, token)
            if token
            else oss2.Auth(access_id, secret)
        )
        bucket = oss2.Bucket(auth, endpoint, bucket_name)
        try:
            return bucket.get_object(object_key).read()
        except oss2.exceptions.NoSuchKey:
            return None
        except oss2.exceptions.NotFound:
            return None
    if oss_v2 is not None:
        client = _make_oss_v2_client(
            access_id,
            secret,
            region=region or "cn-shanghai",
            endpoint=endpoint,
            security_token=token or None,
        )
        try:
            result = client.get_object(
                oss_v2.GetObjectRequest(bucket=bucket_name, key=object_key)
            )
            with result.body as stream:
                return stream.read()
        except Exception as exc:
            if _is_oss_object_missing(exc):
                return None
            raise
    raise RuntimeError("oss2 or alibabacloud_oss_v2 is required to read OSS objects")


def read_oss_object_text(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> str | None:
    raw = read_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        region=region,
        get_arg=get_arg,
    )
    if raw is None:
        return None
    return raw.decode("utf-8")


def read_oss_json_object(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any] | None:
    text = read_oss_object_text(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        region=region,
        get_arg=get_arg,
    )
    if text is None:
        return None
    loaded = json.loads(text)
    return loaded if isinstance(loaded, dict) else None


def read_dispatch_from_oss(
    *,
    bucket_name: str,
    object_key: str,
    endpoint: str,
    account: Any,
    region: str | None = None,
    get_arg: Callable[[str, str | None], str | None] | None = None,
) -> dict[str, Any] | None:
    raw = read_oss_object_bytes(
        bucket_name=bucket_name,
        object_key=object_key,
        endpoint=endpoint,
        account=account,
        region=region,
        get_arg=get_arg,
    )
    if raw is None:
        return None
    loaded = json.loads(raw.decode("utf-8"))
    return loaded if isinstance(loaded, dict) else None


def write_dispatch_to_mc(
    client: Any,
    table_prefix: str,
    *,
    ds: str,
    payload: dict[str, Any],
) -> None:
    """Persist dispatch payload for the ODPS SQL assignment node (``job0_dispatch_out``)."""
    table_name = f"{table_prefix}dispatch_staging"
    row = {
        "action": str(payload.get("action") or ""),
        "reason": str(payload.get("reason") or ""),
        "clip_id": str(payload.get("clip_id") or ""),
        "run_id": str(payload.get("run_id") or ""),
        "clip_dir_name": str(payload.get("clip_dir_name") or ""),
        "bag_oss_key": str(payload.get("bag_oss_key") or ""),
        "dispatched_at": str(payload.get("dispatched_at") or utc_now_iso()),
    }
    sql = (
        f"INSERT OVERWRITE TABLE {table_name} PARTITION (ds={_sql_string_literal(ds)}) "
        f"SELECT "
        f"{_sql_string_literal(row['action'])}, "
        f"{_sql_string_literal(row['reason'])}, "
        f"{_sql_string_literal(row['clip_id'])}, "
        f"{_sql_string_literal(row['run_id'])}, "
        f"{_sql_string_literal(row['clip_dir_name'])}, "
        f"{_sql_string_literal(row['bag_oss_key'])}, "
        f"{_sql_string_literal(row['dispatched_at'])}"
    )
    client.execute_sql(sql).wait_for_success()


def dispatch_payload_from_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text or is_unresolved_dw_placeholder(text):
        return None
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None


def log_dataworks_args(*, label: str = "resolve_pipeline_context") -> None:
    """Print how DataWorks injected scheduler / node-context params (diagnostic)."""
    try:
        node_args = args  # type: ignore[name-defined]
    except NameError:
        node_args = {}
    keys = sorted(node_args.keys()) if isinstance(node_args, dict) else []
    print(
        f"{label}: args_keys={keys} "
        f"SKYNET_TASK_INPUT={os.environ.get('SKYNET_TASK_INPUT', '')}"
    )


def _idle_context(*, action: str, reason: str, source: str) -> dict[str, Any]:
    return {
        "should_run": False,
        "action": action or "idle",
        "reason": reason,
        "clip_id": "",
        "run_id": "",
        "clip_dir_name": "",
        "bag_oss_key": "",
        "source": source,
    }


def _run_context(payload: dict[str, Any], *, source: str) -> dict[str, Any]:
    clip_id = str(payload.get("clip_id") or "").strip()
    run_id = str(payload.get("run_id") or "").strip()
    if not clip_id or not run_id:
        raise ValueError(f"Invalid dispatch payload (missing clip_id/run_id): {payload!r}")
    return {
        "should_run": True,
        "action": "run",
        "clip_id": clip_id,
        "run_id": run_id,
        "clip_dir_name": str(payload.get("clip_dir_name") or "").strip(),
        "bag_oss_key": str(payload.get("bag_oss_key") or "").strip(),
        "reason": str(payload.get("reason") or ""),
        "source": source,
    }


def _load_dispatch_from_oss(
    get_arg: Callable[[str, str | None], str | None],
    *,
    oss_account: Any,
    oss_bucket: str | None,
    oss_endpoint: str | None,
) -> dict[str, Any] | None:
    dispatch_key = (
        resolve_node_param("dispatch_oss_key", get_arg, DEFAULT_DISPATCH_OSS_KEY)
        or DEFAULT_DISPATCH_OSS_KEY
    ).strip()
    bucket = (oss_bucket or resolve_node_param("oss_bucket", get_arg, "") or "").strip()
    if not bucket:
        return None
    region = resolve_node_param("cloud_region", get_arg, "cn_shanghai") or "cn_shanghai"
    endpoint = (oss_endpoint or resolve_node_param("oss_endpoint", get_arg, "") or "").strip()
    if not endpoint:
        endpoint = resolve_oss_http_endpoint(region, get_arg=get_arg)
    return read_dispatch_from_oss(
        bucket_name=bucket,
        object_key=dispatch_key,
        endpoint=endpoint,
        account=oss_account,
        region=region,
        get_arg=get_arg,
    )


def resolve_pipeline_context(
    get_arg: Callable[[str, str | None], str | None],
    *,
    odps_client: Any | None = None,
    oss_account: Any | None = None,
    oss_endpoint: str | None = None,
    oss_bucket: str | None = None,
) -> dict[str, Any]:
    """Resolve clip_id/run_id from node args (debug) or OSS dispatch manifest (primary)."""
    log_dataworks_args()

    action = (resolve_node_param("action", get_arg, "") or "").strip().lower()
    clip_id = (resolve_node_param("clip_id", get_arg, "") or "").strip()
    run_id = (resolve_node_param("run_id", get_arg, "") or "").strip()
    clip_dir_name = (resolve_node_param("clip_dir_name", get_arg, "") or "").strip()
    bag_oss_key = (resolve_node_param("bag_oss_key", get_arg, "") or "").strip()

    if action == "idle":
        return _idle_context(
            action="idle",
            reason=(resolve_node_param("reason", get_arg, "idle") or "idle").strip(),
            source="node_params",
        )

    if clip_id and not run_id:
        run_id = str(uuid.uuid4())
    if clip_id and run_id:
        return {
            "should_run": True,
            "action": "run",
            "clip_id": clip_id,
            "run_id": run_id,
            "clip_dir_name": clip_dir_name,
            "bag_oss_key": bag_oss_key,
            "source": "node_params",
        }

    dispatch_key = (
        resolve_node_param("dispatch_oss_key", get_arg, DEFAULT_DISPATCH_OSS_KEY)
        or DEFAULT_DISPATCH_OSS_KEY
    ).strip()
    bucket = (oss_bucket or resolve_node_param("oss_bucket", get_arg, "") or "").strip()

    if oss_account and bucket:
        region = resolve_node_param("cloud_region", get_arg, "cn_shanghai") or "cn_shanghai"
        endpoint_for_log = resolve_oss_http_endpoint(
            region,
            get_arg=get_arg,
            explicit_endpoint=oss_endpoint,
        )
        print(
            f"resolve_pipeline_context: no clip_id in args; reading OSS "
            f"oss://{bucket}/{dispatch_key} via {endpoint_for_log}"
        )
        payload = _load_dispatch_from_oss(
            get_arg,
            oss_account=oss_account,
            oss_bucket=bucket,
            oss_endpoint=oss_endpoint,
        )
        if payload:
            print(f"resolve_pipeline_context: loaded dispatch from OSS (action={payload.get('action')})")
            oss_action = str(payload.get("action") or "").strip().lower()
            if oss_action != "run":
                return _idle_context(
                    action=oss_action or "idle",
                    reason=str(payload.get("reason") or "idle"),
                    source="dispatch_oss",
                )
            return _run_context(payload, source="dispatch_oss")

    dispatch_json = (
        resolve_node_param("dispatch_json", get_arg, "")
        or resolve_node_param("outputs", get_arg, "")
        or ""
    ).strip()
    json_payload = dispatch_payload_from_json(dispatch_json)
    if json_payload:
        oss_action = str(json_payload.get("action") or "").strip().lower()
        if oss_action != "run":
            return _idle_context(
                action=oss_action or "idle",
                reason=str(json_payload.get("reason") or "idle"),
                source="dispatch_json",
            )
        return _run_context(json_payload, source="dispatch_json")

    raw_task_input = (os.environ.get("SKYNET_TASK_INPUT") or "").strip()
    pyodps_args = read_pyodps_args()
    if not bucket or not oss_account:
        raise ValueError(
            "clip_id/run_id empty: set node params for manual run, or ensure "
            "oss_bucket is configured and job0_dispatch ran first"
        )
    if raw_task_input and "${" in raw_task_input:
        raise ValueError(
            "Dispatch OSS manifest missing and node context unresolved "
            f"(SKYNET_TASK_INPUT={raw_task_input}, args_keys={sorted(pyodps_args.keys())}). "
            "Run job0_dispatch_node first (writes "
            f"oss://{bucket}/{dispatch_key}), then job1_parse in the same workflow. "
            "Do not rely on PyODPS node output params for clip_id; remove write_dispatch_oss=false."
        )
    raise ValueError(
        f"Dispatch OSS manifest missing: oss://{bucket}/{dispatch_key}. "
        "Run job0_dispatch_node in the same workflow before downstream nodes."
    )


def exit_if_pipeline_idle(ctx: dict[str, Any], *, node_name: str = "") -> bool:
    """Print idle marker and return True if caller should exit main() successfully."""
    if ctx.get("should_run"):
        return False
    label = f" {node_name}" if node_name else ""
    print(
        f"PIPELINE_IDLE{label}: action={ctx.get('action')} reason={ctx.get('reason')} "
        f"(skip downstream work until next schedule)"
    )
    return True
# === END pipeline_dispatch.py ===

# === BEGIN oms_time_labels.py (auto-bundled) ===
"""Deterministic OMS L1.1 time labels from rosbag record_time_ns (Job3 post-process)."""


from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_LABEL_TIMEZONE = "Asia/Shanghai"

L1_TIME_LABEL_IDS: tuple[str, ...] = (
    "L1.1.timestamp",
    "L1.1.day_period",
    "L1.1.commute_flag",
    "L1.1.is_holiday",
)


def _local_dt(timestamp_ns: int, timezone: str) -> datetime:
    return datetime.fromtimestamp(int(timestamp_ns) / 1e9, tz=ZoneInfo(timezone))


def day_period_from_hour(hour: int) -> str:
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 11:
        return "morning"
    if 11 <= hour < 13:
        return "noon"
    if 13 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 19:
        return "dusk"
    if 19 <= hour < 22:
        return "evening"
    return "night"


def commute_flag_from_local_dt(local_dt: datetime) -> str:
    if local_dt.weekday() >= 5:
        return "non_commute"
    hour_fraction = local_dt.hour + local_dt.minute / 60.0 + local_dt.second / 3600.0
    if 7 <= hour_fraction < 9:
        return "morning_commute"
    if 17 <= hour_fraction < 19:
        return "evening_commute"
    return "non_commute"


def is_weekend_holiday(local_dt: datetime) -> str:
    """Weekend-only; statutory holidays need a separate calendar source."""
    return "true" if local_dt.weekday() >= 5 else "false"


def derive_l1_time_labels(
    timestamp_ns: int,
    *,
    timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> dict[str, Any]:
    local_dt = _local_dt(timestamp_ns, timezone)
    return {
        "L1.1.timestamp": {
            "timestamp_ms": int(timestamp_ns) // 1_000_000,
            "timezone": timezone,
        },
        "L1.1.day_period": day_period_from_hour(local_dt.hour),
        "L1.1.commute_flag": commute_flag_from_local_dt(local_dt),
        "L1.1.is_holiday": is_weekend_holiday(local_dt),
    }


def apply_l1_time_label_overrides(
    values: dict[str, Any],
    timestamp_ns: int,
    *,
    timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> dict[str, Any]:
    """Override VL/stub values with record_time_ns-derived L1.1 labels."""
    merged = dict(values) if isinstance(values, dict) else {}
    merged.update(derive_l1_time_labels(timestamp_ns, timezone=timezone))
    return merged
# === END oms_time_labels.py ===

# === BEGIN sample_sync.py (auto-bundled) ===
"""Four-camera time-aligned sampling and sync-group helpers (Job2/Job3)."""


from typing import Any

DEFAULT_ALIGN_WINDOW_MS = 200


def align_window_ns_from_ms(window_ms: float | int) -> int:
    return int(float(window_ms) * 1_000_000)


def resolve_required_cameras(
    frames: list[dict[str, Any]],
    cameras: Any,
) -> list[str]:
    if cameras not in (None, "all", "*"):
        if isinstance(cameras, str):
            return sorted(item.strip() for item in cameras.split(",") if item.strip())
        return sorted(str(item) for item in cameras)
    return sorted({str(frame["camera"]) for frame in frames})


def _nearest_frame_in_window(
    camera_frames: list[dict[str, Any]],
    anchor_ns: int,
    window_ns: int,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_dist: int | None = None
    for frame in camera_frames:
        ts = int(frame["timestamp_ns"])
        dist = abs(ts - anchor_ns)
        if dist > window_ns:
            continue
        if best_dist is None or dist < best_dist:
            best = frame
            best_dist = dist
    return best


def sample_uniform_sync(
    frames: list[dict[str, Any]],
    *,
    interval_sec: float,
    align_window_ms: float | int = DEFAULT_ALIGN_WINDOW_MS,
    cameras: Any = "all",
    start_time_ns: int | None = None,
    end_time_ns: int | None = None,
    min_cameras: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (flat sampled_frames with sync_group_id, sample_groups metadata).

    Each sync group only emitted when all required cameras have a frame within
    ±align_window_ms of the anchor timestamp.
    """
    if not frames:
        return [], []

    interval_ns = int(float(interval_sec) * 1_000_000_000)
    window_ns = align_window_ns_from_ms(align_window_ms)
    required = resolve_required_cameras(frames, cameras)
    if not required:
        return [], []

    need = min_cameras if min_cameras is not None else len(required)
    need = max(1, min(need, len(required)))

    by_camera: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        if str(frame["camera"]) not in required:
            continue
        by_camera.setdefault(str(frame["camera"]), []).append(frame)
    for camera_frames in by_camera.values():
        camera_frames.sort(key=lambda item: int(item["timestamp_ns"]))

    all_ts = [int(frame["timestamp_ns"]) for frame in frames]
    range_start = int(start_time_ns if start_time_ns is not None else min(all_ts))
    range_end = int(end_time_ns if end_time_ns is not None else max(all_ts))
    if interval_ns <= 0:
        raise ValueError("interval_sec must be positive")

    flat: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    group_idx = 0
    anchor = range_start
    while anchor <= range_end:
        picked: list[dict[str, Any]] = []
        for camera in required:
            match = _nearest_frame_in_window(by_camera.get(camera, []), anchor, window_ns)
            if match is not None:
                picked.append(match)
        if len(picked) >= need and len(picked) == len(required):
            group_idx += 1
            sync_group_id = f"sg{group_idx:06d}"
            group_frames: list[dict[str, Any]] = []
            for frame in sorted(picked, key=lambda item: str(item["camera"])):
                row = dict(frame)
                row["sync_group_id"] = sync_group_id
                row["anchor_timestamp_ns"] = anchor
                group_frames.append(row)
                flat.append(row)
            groups.append(
                {
                    "sync_group_id": sync_group_id,
                    "anchor_timestamp_ns": anchor,
                    "cameras": [str(item["camera"]) for item in group_frames],
                    "frames": group_frames,
                }
            )
        anchor += interval_ns
    return flat, groups


def is_sync_sample_policy(policy: dict[str, Any] | None) -> bool:
    if not policy:
        return False
    return str(policy.get("type") or "") == "uniform_sync"


def group_manifest_by_sync(manifest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(str(row.get("sync_group_id") or "").strip() for row in manifest_rows):
        return []
    grouped: dict[str, dict[str, Any]] = {}
    for row in manifest_rows:
        sync_group_id = str(row.get("sync_group_id") or "").strip()
        if not sync_group_id:
            continue
        bucket = grouped.setdefault(
            sync_group_id,
            {
                "sync_group_id": sync_group_id,
                "anchor_timestamp_ns": int(row.get("anchor_timestamp_ns") or row["timestamp_ns"]),
                "frames": [],
            },
        )
        bucket["frames"].append(row)
    return sorted(grouped.values(), key=lambda item: int(item["anchor_timestamp_ns"]))
# === END sample_sync.py ===

# =============================================================================
# DataWorks PyODPS 3 节点：Job3-抽样帧打标（MaxFrame + DPE）
#
# ★★★ DataWorks 必须粘贴 bundled 整文件，勿粘贴本文件 ★★★
#   python scripts/bundle_dataworks_node.py dataworks/job3_label_node.py
#   → 粘贴 dataworks/bundled/job3_label_node.py（约 1700+ 行，含 mf_ai_function 内联）
#
# 粘贴整文件到 PyODPS3 节点；Driver 需 maxframe、pyodps、pandas。
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
# DPE worker：推荐 dpe_image=<MC 镜像名>（docker/dpe-deps 含 pyyaml）。
#
# 读 Job2 产物：clips/{clip_id}/runs/{run_id}/job2/sample_manifest.jsonl
# 读 Job1 帧图：clips/{clip_id}/runs/{run_id}/parsed/{image_relpath}
# 写 Job3 产物：clips/{clip_id}/runs/{run_id}/job3/frame_labels.jsonl
#              clips/{clip_id}/runs/{run_id}/job3/job3_mc_payload.json
#
# ---------------------------------------------------------------------------
# 工作流参数（与 Job1 共用）
#   oss_bucket=rosbag-labels-pipline-bucket
#   cloud_region=cn_shanghai
#   oss_ram_role_arn=
#   oss_mount_prefix=
#   oss_prefix_template=clips/{clip_id}/
#   dpe_cpu=2
#   dpe_memory_gb=8
#   dpe_mount_path=/mnt/oss
#   dpe_image=rosbag_dpe_deps
#   job3_config_json=
#   label_taxonomy_json=             # 可选，整份 taxonomy JSON
#   label_taxonomy_oss_key=config/oms_label_taxonomy.yaml
#
# 节点参数
#   clip_id=sha256:...
#   run_id=<Job1 相同>
#   label_model=                     # 留空=stub（labels_json 中 values 为空）
#   label_model_version=
#   label_batch_size=32
#   label_timezone=Asia/Shanghai     # L1.1 时间标签由 record_time_ns 后处理写入
#   exclude_labels=L1.1.timestamp,L1.1.day_period,L1.1.commute_flag,L1.1.is_holiday
#   label_image_mode=auto          # auto|oss_url|base64；有 role_arn 或 oss_vl AK/SK 时 auto→oss_url
#   oss_vl_access_key_id=           # 长期 OSS AK（VL IMAGE_URL；非 STS.*；别名 oss_access_key_id）
#   oss_vl_access_key_secret=     # 长期 OSS SK（与上成对；别名 oss_access_key_secret）
#   ※ oss_ram_role_arn 仅 DPE 挂载用；cp.image(IMAGE_URL) 必须 AK/SK，不能靠 role_arn
#   label_prompt_compact=true      # 压缩 taxonomy prompt，减少 VL token
#   ai_parallel_partitions=16      # MCSQL 行级并发（默认自动放大到 min(帧数,32)）
#   total_rpm_limit=12000          # VL generate running_options；0=不传
#   request_timeout=300            # VL generate 单次请求超时（秒）；0=不传
#   ai_memory=8G                   # VL generate Worker 内存；留空=不传
# =============================================================================


import base64
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import importlib.util
import sys

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_running_options




_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_rosbag__",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
}

DEFAULT_JOB3_CONFIG: dict[str, Any] = {
    "provider": "maxframe_ai_function",
    "model": "",
    "model_version": "",
    "label_taxonomy_oss_key": "config/oms_label_taxonomy.yaml",
    "exclude_labels": [],
    "batch_size": 32,
}


def _load_mf_ai_function() -> None:
    """Local dev only; bundled DataWorks paste already inlines mf_ai_function.py."""
    if "configure_mf_ai_engine" in globals():
        return
    file_path = globals().get("__file__")
    if not file_path:
        return
    helper = Path(file_path).resolve().parent / "mf_ai_function.py"
    if not helper.is_file():
        return
    spec = importlib.util.spec_from_file_location("mf_ai_function", helper)
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules["mf_ai_function"] = module
    spec.loader.exec_module(module)
    for name in (
        "configure_mf_ai_engine",
        "apply_ai_quota",
        "prepare_mf_ai_runtime",
        "ai_label_frames_with_model",
        "ai_label_sync_groups_with_model",
        "build_vl_oss_storage_options",
        "resolve_label_image_mode",
        "resolve_ai_parallel_partitions",
    ):
        if hasattr(module, name):
            globals()[name] = getattr(module, name)


_load_mf_ai_function()


def _parse_skynet_args(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{"):
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return {str(k): str(v) for k, v in loaded.items()}
    parsed: dict[str, str] = {}
    for token in re.split(r"[;\s]+", text):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _all_arg_sources() -> dict[str, str]:
    merged: dict[str, str] = {}
    merged.update(_parse_skynet_args(os.environ.get("SKYNET_ARGS", "")))
    for env_name, arg_name in (
        ("OSS_BUCKET", "oss_bucket"),
        ("CLOUD_REGION", "cloud_region"),
        ("OSS_VL_ACCESS_KEY_ID", "oss_vl_access_key_id"),
        ("OSS_VL_ACCESS_KEY_SECRET", "oss_vl_access_key_secret"),
        ("OSS_ACCESS_KEY_ID", "oss_access_key_id"),
        ("OSS_ACCESS_KEY_SECRET", "oss_access_key_secret"),
    ):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            merged[arg_name] = env_value
    try:
        node_args = args  # type: ignore[name-defined]
        if isinstance(node_args, dict):
            for key, value in node_args.items():
                if value is not None and str(value).strip():
                    merged[str(key)] = str(value).strip()
    except NameError:
        pass
    return merged


def get_arg(name: str, default: str | None = None) -> str | None:
    if default is None:
        default = _PROJECT_DEFAULTS.get(name)
    value = _all_arg_sources().get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def require_arg(name: str) -> str:
    value = get_arg(name)
    if not value:
        resolved = _all_arg_sources()
        raise ValueError(
            f"Missing required parameter: {name}. "
            f"Resolved keys: {sorted(resolved.keys()) or '(empty)'}"
        )
    return value


def get_int_arg(name: str, default: int) -> int:
    value = get_arg(name)
    return default if value is None else int(value)


def _resolve_oss_vl_ak_sk() -> tuple[str, str]:
    ak = (
        get_arg("oss_vl_access_key_id")
        or get_arg("oss_access_key_id")
        or ""
    )
    sk = (
        get_arg("oss_vl_access_key_secret")
        or get_arg("oss_access_key_secret")
        or ""
    )
    return ak, sk


def load_job3_config() -> dict[str, Any]:
    raw = get_arg("job3_config_json")
    if not raw:
        return DEFAULT_JOB3_CONFIG
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("job3_config_json must be a JSON object")
    return loaded


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _oss_internal_url(region: str, bucket: str, prefix: str) -> str:
    region_id = region.replace("_", "-")
    normalized = prefix.strip("/")
    if not normalized:
        return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/"
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/{normalized}/"


def _storage_options(role_arn: str | None, account: Any) -> dict[str, str]:
    if role_arn:
        return {"role_arn": role_arn}
    return {
        "oss_access_key_id": account.access_id,
        "oss_access_key_secret": account.secret_access_key,
    }


def _apply_dpe_runtime_settings(dpe_image: str | None) -> None:
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            rows.append(json.loads(text))
    return rows


def _load_taxonomy_from_mount(
    mount_path: str,
    *,
    label_taxonomy_json: str,
    label_taxonomy_oss_key: str,
) -> dict[str, Any]:
    if label_taxonomy_json:
        loaded = json.loads(label_taxonomy_json)
        if not isinstance(loaded, dict):
            raise ValueError("label_taxonomy_json must be a JSON object")
        return loaded

    if label_taxonomy_oss_key:
        taxonomy_path = Path(mount_path) / label_taxonomy_oss_key
        if taxonomy_path.is_file():
            text = taxonomy_path.read_text(encoding="utf-8")
            if taxonomy_path.suffix.lower() in {".yaml", ".yml"}:
                import yaml

                loaded = yaml.safe_load(text)
            else:
                loaded = json.loads(text)
            if isinstance(loaded, dict):
                return loaded

    return {
        "version": "stub",
        "label_count": 0,
        "labels": [],
        "source": "embedded-stub",
    }


def _filter_taxonomy(taxonomy: dict[str, Any], exclude_labels: list[str]) -> dict[str, Any]:
    if not exclude_labels:
        return taxonomy
    excluded = set(exclude_labels)
    labels = taxonomy.get("labels") or []
    filtered = [item for item in labels if str(item.get("id")) not in excluded]
    return {
        **taxonomy,
        "labels": filtered,
        "label_count": len(filtered),
        "excluded_labels": list(excluded),
    }


def _frame_id(camera: str, frame_idx: int) -> str:
    return f"{camera}:{frame_idx}"


def _build_label_prompt(taxonomy: dict[str, Any]) -> str:
    lines = [
        "You are an OMS in-cabin vision labeler.",
        "Return JSON object mapping label id to value, following each label value_schema.",
        f"Taxonomy version: {taxonomy.get('version', 'unknown')}",
        "Labels:",
    ]
    for item in taxonomy.get("labels") or []:
        label_id = item.get("id")
        name = item.get("name")
        definition = item.get("definition")
        schema = item.get("value_schema") or {}
        lines.append(f"- {label_id} ({name}): {definition}; schema={json.dumps(schema, ensure_ascii=False)}")
    return "\n".join(lines)


def _stub_labels_payload(
    *,
    taxonomy: dict[str, Any],
    model_version: str,
) -> dict[str, Any]:
    return {
        "taxonomy_version": str(taxonomy.get("version") or "unknown"),
        "provider": "maxcompute_ai",
        "model_version": model_version,
        "status": "stub",
        "values": {},
    }


def _label_single_frame_stub(
    *,
    frame: dict[str, Any],
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    image_bytes: bytes | None,
) -> dict[str, Any]:
    resolved_version = model_version or ("none" if not model else model)
    labels_payload = _stub_labels_payload(taxonomy=taxonomy, model_version=resolved_version)
    if model:
        # MC AI 接入点：当前版本保留 OMS 结构，values 留空供后续 vision 模型填充。
        labels_payload["status"] = "pending_model_integration"
    labels_payload["image_size_bytes"] = len(image_bytes) if image_bytes else 0
    return labels_payload


def _resolve_frame_image_path(parsed_root: Path, frame: dict[str, Any]) -> Path:
    """Resolve sampled frame image under parsed/ (handles legacy duplicated paths)."""
    raw = str(frame.get("image_relpath") or frame.get("image_path") or "").strip().lstrip("/")
    candidates = [parsed_root / raw]
    parsed_marker = "/parsed/"
    if parsed_marker in raw:
        candidates.append(parsed_root / raw.rsplit(parsed_marker, 1)[-1].lstrip("/"))
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _manifest_is_sync(manifest_rows: list[dict[str, Any]]) -> bool:
    return any(str(row.get("sync_group_id") or "").strip() for row in manifest_rows)


def _build_sync_groups(manifest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = group_manifest_by_sync(manifest_rows)
    if not groups:
        return []
    for group in groups:
        group["frames"] = sorted(
            group.get("frames") or [],
            key=lambda item: str(item.get("camera") or ""),
        )
    return groups


def _run_label_sync_batches(
    sync_groups: list[dict[str, Any]],
    *,
    parsed_root: Path,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    prompt = _build_label_prompt(taxonomy) if model else ""

    for group in sync_groups:
        anchor_ns = int(group.get("anchor_timestamp_ns") or 0)
        sync_group_id = str(group.get("sync_group_id") or "")
        group_frames = group.get("frames") or []
        if not group_frames:
            continue

        labels_payload = _label_single_frame_stub(
            frame=group_frames[0],
            taxonomy=taxonomy,
            model=model,
            model_version=model_version,
            image_bytes=None,
        )
        if model and prompt:
            labels_payload["_prompt_chars"] = len(prompt)
        labels_payload["values"] = apply_l1_time_label_overrides(
            labels_payload.get("values") or {},
            anchor_ns,
            timezone=label_timezone,
        )
        labels_payload["label_scope"] = "sync_group"
        labels_payload["sync_group_id"] = sync_group_id

        for frame in group_frames:
            camera = str(frame["camera"])
            frame_idx = int(frame["frame_idx"])
            results.append(
                {
                    "frame_id": _frame_id(camera, frame_idx),
                    "camera": camera,
                    "frame_idx": frame_idx,
                    "timestamp_ns": int(frame["timestamp_ns"]),
                    "anchor_timestamp_ns": anchor_ns,
                    "sync_group_id": sync_group_id,
                    "label_scope": "sync_group",
                    "image_relpath": str(frame.get("image_relpath") or ""),
                    "sample_policy": frame.get("sample_policy"),
                    "labels_json": dict(labels_payload),
                }
            )
    return results


def _run_label_batches(
    manifest_rows: list[dict[str, Any]],
    *,
    parsed_root: Path,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    batch_size: int,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    prompt = _build_label_prompt(taxonomy) if model else ""

    for start in range(0, len(manifest_rows), batch_size):
        batch = manifest_rows[start : start + batch_size]
        for frame in batch:
            image_path = _resolve_frame_image_path(parsed_root, frame)
            image_bytes = image_path.read_bytes() if image_path.is_file() else None
            if image_bytes is None:
                raise FileNotFoundError(f"Sampled frame image not found: {image_path}")

            labels_payload = _label_single_frame_stub(
                frame=frame,
                taxonomy=taxonomy,
                model=model,
                model_version=model_version,
                image_bytes=image_bytes,
            )
            if model and prompt:
                labels_payload["_prompt_chars"] = len(prompt)
            labels_payload["values"] = apply_l1_time_label_overrides(
                labels_payload.get("values") or {},
                int(frame["timestamp_ns"]),
                timezone=label_timezone,
            )

            camera = str(frame["camera"])
            frame_idx = int(frame["frame_idx"])
            results.append(
                {
                    "frame_id": _frame_id(camera, frame_idx),
                    "camera": camera,
                    "frame_idx": frame_idx,
                    "timestamp_ns": int(frame["timestamp_ns"]),
                    "image_relpath": str(frame["image_relpath"]),
                    "sample_policy": frame.get("sample_policy"),
                    "labels_json": labels_payload,
                }
            )
    return results


def _build_job3_label_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    job3_config: dict[str, Any],
    label_taxonomy_json: str,
    label_taxonomy_oss_key: str,
    exclude_labels: list[str],
    label_model: str,
    label_model_version: str,
    label_batch_size: int,
    label_timezone: str,
):
    def _job3_label_row(row):
        manifest_path = Path(mount_path) / row["manifest_relpath"]
        if not manifest_path.is_file():
            job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
            if not job2_payload_path.is_file():
                raise FileNotFoundError(
                    f"Job2 manifest not found: {manifest_path}; payload: {job2_payload_path}"
                )
            job2_payload = json.loads(job2_payload_path.read_text(encoding="utf-8"))
            manifest_rows = job2_payload.get("sampled_frames") or []
        else:
            manifest_rows = _read_jsonl(manifest_path)

        if not manifest_rows:
            raise ValueError("Job2 sample manifest is empty; run Job2 sampling first")

        taxonomy = _load_taxonomy_from_mount(
            mount_path,
            label_taxonomy_json=label_taxonomy_json,
            label_taxonomy_oss_key=label_taxonomy_oss_key,
        )
        taxonomy = _filter_taxonomy(taxonomy, exclude_labels)

        parsed_root = Path(mount_path) / row["parsed_relpath"]
        if _manifest_is_sync(manifest_rows):
            sync_groups = _build_sync_groups(manifest_rows)
            labeled_frames = _run_label_sync_batches(
                sync_groups,
                parsed_root=parsed_root,
                taxonomy=taxonomy,
                model=label_model,
                model_version=label_model_version,
                label_timezone=label_timezone,
            )
        else:
            labeled_frames = _run_label_batches(
                manifest_rows,
                parsed_root=parsed_root,
                taxonomy=taxonomy,
                model=label_model,
                model_version=label_model_version,
                batch_size=label_batch_size,
                label_timezone=label_timezone,
            )

        job3_root = Path(mount_path) / row["job3_relpath"]
        job3_root.mkdir(parents=True, exist_ok=True)

        frame_labels_path = job3_root / "frame_labels.jsonl"
        with frame_labels_path.open("w", encoding="utf-8") as labels_file:
            for item in labeled_frames:
                row_out = {
                    "frame_id": item["frame_id"],
                    "camera": item["camera"],
                    "frame_idx": item["frame_idx"],
                    "timestamp_ns": item["timestamp_ns"],
                    "image_relpath": item["image_relpath"],
                    "labels_json": item["labels_json"],
                }
                if item.get("sync_group_id"):
                    row_out["sync_group_id"] = item["sync_group_id"]
                    row_out["anchor_timestamp_ns"] = item.get("anchor_timestamp_ns")
                    row_out["label_scope"] = item.get("label_scope") or "sync_group"
                labels_file.write(json.dumps(row_out, ensure_ascii=False) + "\n")

        resolved_model_version = label_model_version or (
            "none" if not label_model else label_model
        )
        payload = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
            "taxonomy_label_count": int(taxonomy.get("label_count") or len(taxonomy.get("labels") or [])),
            "label_model_version": resolved_model_version,
            "sample_sync_mode": _manifest_is_sync(manifest_rows),
            "labeled_frames": [
                {
                    "frame_id": item["frame_id"],
                    "camera": item["camera"],
                    "frame_idx": item["frame_idx"],
                    "timestamp_ns": item["timestamp_ns"],
                    "image_relpath": item["image_relpath"],
                    "labels_json": item["labels_json"],
                }
                for item in labeled_frames
            ],
            "processed_at": _utc_now_iso(),
        }
        payload_path = job3_root / "job3_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "labeled_frame_count": len(labeled_frames),
            "taxonomy_version": payload["taxonomy_version"],
            "label_model_version": resolved_model_version,
            "payload_relpath": f"{row['job3_relpath']}/job3_mc_payload.json",
            "frame_labels_relpath": f"{row['job3_relpath']}/frame_labels.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_label_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job3_prepare_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    label_taxonomy_json: str,
    label_taxonomy_oss_key: str,
    exclude_labels: list[str],
):
    def _job3_prepare_row(row):
        manifest_path = Path(mount_path) / row["manifest_relpath"]
        if not manifest_path.is_file():
            job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
            if not job2_payload_path.is_file():
                raise FileNotFoundError(
                    f"Job2 manifest not found: {manifest_path}; payload: {job2_payload_path}"
                )
            job2_payload = json.loads(job2_payload_path.read_text(encoding="utf-8"))
            manifest_rows = job2_payload.get("sampled_frames") or []
        else:
            manifest_rows = _read_jsonl(manifest_path)

        if not manifest_rows:
            raise ValueError("Job2 sample manifest is empty; run Job2 sampling first")

        taxonomy = _load_taxonomy_from_mount(
            mount_path,
            label_taxonomy_json=label_taxonomy_json,
            label_taxonomy_oss_key=label_taxonomy_oss_key,
        )
        taxonomy = _filter_taxonomy(taxonomy, exclude_labels)

        enriched: list[dict[str, Any]] = []
        parsed_root = Path(mount_path) / row["parsed_relpath"]
        for frame in manifest_rows:
            camera = str(frame["camera"])
            frame_idx = int(frame["frame_idx"])
            image_path = _resolve_frame_image_path(parsed_root, frame)
            enriched.append(
                {
                    **frame,
                    "frame_id": _frame_id(camera, frame_idx),
                    "image_relpath": str(frame.get("image_relpath") or frame.get("image_path") or ""),
                    "image_exists": image_path.is_file(),
                }
            )

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "job3_relpath": row["job3_relpath"],
            "manifest_json": json.dumps(enriched, ensure_ascii=False),
            "taxonomy_json": json.dumps(taxonomy, ensure_ascii=False),
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_prepare_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job3_encode_frame_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
):
    def _job3_encode_frame_row(row):
        parsed_root = Path(mount_path) / row["parsed_relpath"]
        frame = {
            "camera": row["camera"],
            "frame_idx": int(row["frame_idx"]),
            "image_relpath": row["image_relpath"],
            "image_path": row.get("image_path") or row["image_relpath"],
        }
        image_path = _resolve_frame_image_path(parsed_root, frame)
        if not image_path.is_file():
            raise FileNotFoundError(f"Sampled frame image not found: {image_path}")
        return {
            "frame_id": row["frame_id"],
            "image_base64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_encode_frame_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _parallel_encode_frame_images(
    manifest_rows: list[dict[str, Any]],
    *,
    parsed_relpath: str,
    encode_partitions: int,
    encode_udf,
) -> list[dict[str, Any]]:
    if not manifest_rows:
        return manifest_rows
    rows = [
        {
            "frame_id": frame["frame_id"],
            "camera": frame["camera"],
            "frame_idx": int(frame["frame_idx"]),
            "image_relpath": frame["image_relpath"],
            "image_path": frame.get("image_path") or frame["image_relpath"],
            "parsed_relpath": parsed_relpath,
        }
        for frame in manifest_rows
    ]
    frame_df = md.DataFrame(pd.DataFrame(rows))
    if encode_partitions > 1 and len(rows) > 1:
        frame_df = frame_df.mf.rebalance(num_partitions=min(encode_partitions, len(rows)))
    encoded = frame_df.apply(
        encode_udf,
        axis=1,
        output_type="dataframe",
        result_type="expand",
        dtypes={"frame_id": "string", "image_base64": "string"},
        skip_infer=True,
    ).execute().fetch()
    b64_by_id = {
        str(row["frame_id"]): str(row["image_base64"])
        for _, row in encoded.iterrows()
    }
    merged: list[dict[str, Any]] = []
    for frame in manifest_rows:
        frame_id = str(frame["frame_id"])
        image_b64 = b64_by_id.get(frame_id, "")
        if not image_b64:
            raise ValueError(f"Missing base64 for frame_id={frame_id}")
        merged.append({**frame, "image_base64": image_b64})
    return merged


def _build_job3_write_payload_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
):
    def _job3_write_payload_row(row):
        labeled_frames = json.loads(str(row["labeled_frames_json"]))
        job3_root = Path(mount_path) / row["job3_relpath"]
        job3_root.mkdir(parents=True, exist_ok=True)

        frame_labels_path = job3_root / "frame_labels.jsonl"
        with frame_labels_path.open("w", encoding="utf-8") as labels_file:
            for item in labeled_frames:
                row_out = {
                    "frame_id": item["frame_id"],
                    "camera": item["camera"],
                    "frame_idx": item["frame_idx"],
                    "timestamp_ns": item["timestamp_ns"],
                    "image_relpath": item["image_relpath"],
                    "labels_json": item["labels_json"],
                }
                if item.get("sync_group_id"):
                    row_out["sync_group_id"] = item["sync_group_id"]
                    row_out["anchor_timestamp_ns"] = item.get("anchor_timestamp_ns")
                    row_out["label_scope"] = item.get("label_scope") or "sync_group"
                labels_file.write(json.dumps(row_out, ensure_ascii=False) + "\n")

        payload = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "taxonomy_version": row["taxonomy_version"],
            "taxonomy_label_count": int(row["taxonomy_label_count"]),
            "label_model_version": row["label_model_version"],
            "sample_sync_mode": str(row.get("sample_sync_mode") or "").strip().lower() in ("1", "true", "yes"),
            "labeled_frames": labeled_frames,
            "processed_at": _utc_now_iso(),
        }
        payload_path = job3_root / "job3_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "labeled_frame_count": len(labeled_frames),
            "taxonomy_version": row["taxonomy_version"],
            "label_model_version": row["label_model_version"],
            "payload_relpath": f"{row['job3_relpath']}/job3_mc_payload.json",
            "frame_labels_relpath": f"{row['job3_relpath']}/frame_labels.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job3_write_payload_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _labeled_frames_from_sync_ai(
    sync_groups: list[dict[str, Any]],
    ai_results: list[dict[str, Any]],
    *,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    resolved_version = model_version or ("none" if not model else model)
    labeled: list[dict[str, Any]] = []
    for group, ai_result in zip(sync_groups, ai_results):
        values = ai_result.get("values") if isinstance(ai_result, dict) else {}
        if not isinstance(values, dict):
            values = {}
        anchor_ns = int(group.get("anchor_timestamp_ns") or 0)
        values = apply_l1_time_label_overrides(
            values,
            anchor_ns,
            timezone=label_timezone,
        )
        sync_group_id = str(group.get("sync_group_id") or "")
        labels_payload = {
            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
            "provider": "maxframe_ai_function",
            "model_version": resolved_version,
            "status": str(ai_result.get("status") or "ok"),
            "label_scope": "sync_group",
            "sync_group_id": sync_group_id,
            "values": values,
        }
        for frame in group.get("frames") or []:
            labeled.append(
                {
                    "frame_id": frame["frame_id"],
                    "camera": frame["camera"],
                    "frame_idx": frame["frame_idx"],
                    "timestamp_ns": frame["timestamp_ns"],
                    "anchor_timestamp_ns": anchor_ns,
                    "sync_group_id": sync_group_id,
                    "label_scope": "sync_group",
                    "image_relpath": frame["image_relpath"],
                    "labels_json": dict(labels_payload),
                }
            )
    return labeled


def _labeled_frames_from_ai(
    manifest_rows: list[dict[str, Any]],
    ai_results: list[dict[str, Any]],
    *,
    taxonomy: dict[str, Any],
    model: str,
    model_version: str,
    label_timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> list[dict[str, Any]]:
    resolved_version = model_version or ("none" if not model else model)
    labeled: list[dict[str, Any]] = []
    for frame, ai_result in zip(manifest_rows, ai_results):
        values = ai_result.get("values") if isinstance(ai_result, dict) else {}
        if not isinstance(values, dict):
            values = {}
        values = apply_l1_time_label_overrides(
            values,
            int(frame["timestamp_ns"]),
            timezone=label_timezone,
        )
        labels_payload = {
            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
            "provider": "maxframe_ai_function",
            "model_version": resolved_version,
            "status": str(ai_result.get("status") or "ok"),
            "values": values,
        }
        labeled.append(
            {
                "frame_id": frame["frame_id"],
                "camera": frame["camera"],
                "frame_idx": frame["frame_idx"],
                "timestamp_ns": frame["timestamp_ns"],
                "image_relpath": frame["image_relpath"],
                "labels_json": labels_payload,
            }
        )
    return labeled


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job3_label"):
        return
    clip_id = pipeline_ctx["clip_id"]
    run_id = pipeline_ctx["run_id"]

    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    role_arn = get_arg("oss_ram_role_arn")
    oss_mount_prefix = get_arg("oss_mount_prefix", "") or ""
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/")
    mount_path = get_arg("dpe_mount_path", "/mnt/oss")
    dpe_cpu = get_int_arg("dpe_cpu", 2)
    dpe_memory = get_int_arg("dpe_memory_gb", 8)
    dpe_image = get_arg("dpe_image")

    job3_config = load_job3_config()
    label_model = get_arg("label_model") or str(job3_config.get("model") or "")
    label_model_version = get_arg("label_model_version") or str(job3_config.get("model_version") or "")
    label_batch_size = get_int_arg("label_batch_size", int(job3_config.get("batch_size", 32)))
    label_timezone = (
        get_arg("label_timezone")
        or str(job3_config.get("label_timezone") or DEFAULT_LABEL_TIMEZONE)
    ).strip()
    label_taxonomy_json = get_arg("label_taxonomy_json") or ""
    label_taxonomy_oss_key = (
        get_arg("label_taxonomy_oss_key")
        or str(job3_config.get("label_taxonomy_oss_key") or DEFAULT_JOB3_CONFIG["label_taxonomy_oss_key"])
    )
    exclude_raw = get_arg("exclude_labels")
    if exclude_raw:
        exclude_labels = [item.strip() for item in exclude_raw.split(",") if item.strip()]
    else:
        exclude_labels = list(job3_config.get("exclude_labels") or [])

    ai_modelset_project = get_arg("ai_modelset_project") or "bigdata_public_modelset"
    ai_parallel_partitions = get_int_arg("ai_parallel_partitions", 8)
    total_rpm_limit = get_int_arg("total_rpm_limit", 12000)
    request_timeout = get_int_arg("request_timeout", 300)
    ai_memory = get_arg("ai_memory", "8G") or ""
    ai_cu_quota_name = get_arg("ai_cu_quota_name")
    ai_gu_quota_name = get_arg("ai_gu_quota_name")
    label_image_mode = get_arg("label_image_mode", "auto") or "auto"
    oss_vl_access_key_id, oss_vl_access_key_secret = _resolve_oss_vl_ak_sk()
    label_prompt_compact_raw = get_arg("label_prompt_compact", "true") or "true"
    label_prompt_compact = label_prompt_compact_raw.strip().lower() not in ("0", "false", "no")
    vl_storage_options = (
        build_vl_oss_storage_options(
            role_arn=role_arn,
            oss_access_key_id=oss_vl_access_key_id,
            oss_access_key_secret=oss_vl_access_key_secret,
        )
        if "build_vl_oss_storage_options" in globals()
        else None
    )
    resolved_image_mode = (
        resolve_label_image_mode(
            label_image_mode,
            role_arn,
            oss_access_key_id=oss_vl_access_key_id,
            oss_access_key_secret=oss_vl_access_key_secret,
        )
        if "resolve_label_image_mode" in globals()
        else (
            "oss_url"
            if (oss_vl_access_key_id and oss_vl_access_key_secret)
            else "base64"
        )
    )

    clip_prefix = prefix_template.format(clip_id=clip_id).strip("/")
    parsed_relpath = f"{clip_prefix}/runs/{run_id}/parsed"
    job2_relpath = f"{clip_prefix}/runs/{run_id}/job2"
    job3_relpath = f"{clip_prefix}/runs/{run_id}/job3"

    _apply_dpe_runtime_settings(dpe_image)
    mf_options.local_execution.enabled = False

    if label_model and "prepare_mf_ai_runtime" in globals():
        prepare_mf_ai_runtime(
            model_name=label_model,
            dpe_image=dpe_image,
            cu_quota_name=ai_cu_quota_name,
            gu_quota_name=ai_gu_quota_name,
        )
    else:
        mf_options.dag.settings = {
            "engine_order": ["DPE"],
            "unavailable_engines": ["MCSQL", "SPE"],
        }

    account = o.account  # type: ignore[name-defined]
    oss_mount_url = _oss_internal_url(cloud_region, oss_bucket, oss_mount_prefix)
    session = new_session(o)  # type: ignore[name-defined]

    job_row = {
        "clip_id": clip_id,
        "run_id": run_id,
        "parsed_relpath": parsed_relpath,
        "manifest_relpath": f"{job2_relpath}/sample_manifest.jsonl",
        "job2_payload_relpath": f"{job2_relpath}/job2_sample_payload.json",
        "job3_relpath": job3_relpath,
    }
    input_df = md.DataFrame(pd.DataFrame([job_row]))

    try:
        print(f"Logview: {session.get_logview_address()}")
        if not label_taxonomy_json and label_taxonomy_oss_key:
            print(f"Job3 taxonomy OSS key: {label_taxonomy_oss_key} (upload yaml to bucket or pass label_taxonomy_json)")

        if label_model:
            if "ai_label_frames_with_model" not in globals():
                raise RuntimeError(
                    "mf_ai_function not loaded. DataWorks 请粘贴 "
                    "dataworks/bundled/job3_label_node.py（非 job3_label_node.py）。"
                    "本地生成: python scripts/bundle_dataworks_node.py dataworks/job3_label_node.py"
                )
            print(f"Job3 MaxFrame AI Function model={label_model}")

            _job3_prepare_row = _build_job3_prepare_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
                label_taxonomy_json=label_taxonomy_json,
                label_taxonomy_oss_key=label_taxonomy_oss_key,
                exclude_labels=exclude_labels,
            )
            prep = input_df.apply(
                _job3_prepare_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "job3_relpath": "string",
                    "manifest_json": "string",
                    "taxonomy_json": "string",
                },
                skip_infer=True,
            ).execute().fetch().iloc[0]

            manifest_rows = json.loads(str(prep["manifest_json"]))
            taxonomy = json.loads(str(prep["taxonomy_json"]))
            missing = [f for f in manifest_rows if not f.get("image_exists")]
            if missing:
                raise FileNotFoundError(
                    f"{len(missing)} sampled frame image(s) missing under parsed/ (first frame_id={missing[0].get('frame_id')})"
                )

            sync_mode = _manifest_is_sync(manifest_rows)
            sync_groups = _build_sync_groups(manifest_rows) if sync_mode else []

            if resolved_image_mode == "base64":
                encode_partitions = (
                    resolve_ai_parallel_partitions(len(manifest_rows), ai_parallel_partitions)
                    if "resolve_ai_parallel_partitions" in globals()
                    else min(len(manifest_rows), max(ai_parallel_partitions, 8))
                )
                print(
                    f"Job3 parallel base64 encode: frames={len(manifest_rows)} "
                    f"partitions={encode_partitions}"
                )
                _job3_encode_frame_row = _build_job3_encode_frame_udf(
                    dpe_cpu=dpe_cpu,
                    dpe_memory=dpe_memory,
                    oss_mount_url=oss_mount_url,
                    mount_path=mount_path,
                    storage_options=_storage_options(role_arn, account),
                )
                manifest_rows = _parallel_encode_frame_images(
                    manifest_rows,
                    parsed_relpath=parsed_relpath,
                    encode_partitions=encode_partitions,
                    encode_udf=_job3_encode_frame_row,
                )
                if sync_mode:
                    sync_groups = _build_sync_groups(manifest_rows)

            label_count = len(sync_groups) if sync_mode else len(manifest_rows)
            effective_partitions = (
                resolve_ai_parallel_partitions(label_count, ai_parallel_partitions)
                if "resolve_ai_parallel_partitions" in globals()
                else min(label_count, max(ai_parallel_partitions, 8))
            )
            vl_auth = "oss_ak_sk" if (oss_vl_access_key_id and oss_vl_access_key_secret) else "none"
            ak_hint = (
                f"{oss_vl_access_key_id[:4]}...{oss_vl_access_key_id[-4:]}"
                if len(oss_vl_access_key_id) >= 8
                else "(empty)"
            )
            print(
                f"Job3 AI label: sync_mode={sync_mode} image_mode={resolved_image_mode} vl_auth={vl_auth} "
                f"ak_hint={ak_hint} frames={len(manifest_rows)} groups={len(sync_groups)} "
                f"parallel_partitions={effective_partitions} compact_prompt={label_prompt_compact} "
                f"running_options={{total_rpm_limit={total_rpm_limit if total_rpm_limit > 0 else 'off'}, "
                f"request_timeout={request_timeout if request_timeout > 0 else 'off'}, "
                f"memory={ai_memory or 'off'}}}"
            )
            if resolved_image_mode == "oss_url" and not vl_storage_options:
                raise ValueError(
                    "label_image_mode=oss_url but OSS VL AK/SK missing. "
                    "Set oss_vl_access_key_id + oss_vl_access_key_secret "
                    f"(aliases oss_access_key_id/secret). "
                    f"Resolved arg keys: {sorted(_all_arg_sources().keys())}"
                )

            if sync_mode:
                if "ai_label_sync_groups_with_model" not in globals():
                    raise RuntimeError(
                        "sync sample policy requires ai_label_sync_groups_with_model in mf_ai_function"
                    )
                ai_results = ai_label_sync_groups_with_model(
                    sync_groups,
                    label_model,
                    o,  # type: ignore[name-defined]
                    taxonomy=taxonomy,
                    cloud_region=cloud_region,
                    oss_bucket=oss_bucket,
                    storage_options=vl_storage_options,
                    role_arn=role_arn,
                    modelset_project=ai_modelset_project,
                    parallel_partitions=effective_partitions,
                    parsed_relpath=parsed_relpath,
                    compact_prompt=label_prompt_compact,
                    total_rpm_limit=total_rpm_limit if total_rpm_limit > 0 else None,
                    request_timeout=request_timeout if request_timeout > 0 else None,
                    ai_memory=ai_memory.strip() if ai_memory.strip() else None,
                )
                labeled_frames = _labeled_frames_from_sync_ai(
                    sync_groups,
                    ai_results,
                    taxonomy=taxonomy,
                    model=label_model,
                    model_version=label_model_version,
                    label_timezone=label_timezone,
                )
            else:
                ai_results = ai_label_frames_with_model(
                    manifest_rows,
                    label_model,
                    o,  # type: ignore[name-defined]
                    taxonomy=taxonomy,
                    cloud_region=cloud_region,
                    oss_bucket=oss_bucket,
                    storage_options=vl_storage_options,
                    role_arn=role_arn,
                    modelset_project=ai_modelset_project,
                    parallel_partitions=effective_partitions,
                    parsed_relpath=parsed_relpath,
                    compact_prompt=label_prompt_compact,
                    total_rpm_limit=total_rpm_limit if total_rpm_limit > 0 else None,
                    request_timeout=request_timeout if request_timeout > 0 else None,
                    ai_memory=ai_memory.strip() if ai_memory.strip() else None,
                )
                labeled_frames = _labeled_frames_from_ai(
                    manifest_rows,
                    ai_results,
                    taxonomy=taxonomy,
                    model=label_model,
                    model_version=label_model_version,
                    label_timezone=label_timezone,
                )
            resolved_model_version = label_model_version or label_model

            _job3_write_payload_row = _build_job3_write_payload_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
            )
            write_df = md.DataFrame(
                pd.DataFrame(
                    [
                        {
                            "clip_id": clip_id,
                            "run_id": run_id,
                            "job3_relpath": job3_relpath,
                            "taxonomy_version": str(taxonomy.get("version") or "unknown"),
                            "taxonomy_label_count": int(
                                taxonomy.get("label_count") or len(taxonomy.get("labels") or [])
                            ),
                            "label_model_version": resolved_model_version,
                            "sample_sync_mode": sync_mode,
                            "labeled_frames_json": json.dumps(labeled_frames, ensure_ascii=False),
                        }
                    ]
                )
            )
            row = write_df.apply(
                _job3_write_payload_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "labeled_frame_count": "int64",
                    "taxonomy_version": "string",
                    "label_model_version": "string",
                    "payload_relpath": "string",
                    "frame_labels_relpath": "string",
                },
                skip_infer=True,
            ).execute().fetch().iloc[0]
        else:
            print("WARN: label_model empty; writing OMS-shaped labels_json with empty values (stub mode)")
            _job3_label_row = _build_job3_label_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
                job3_config=job3_config,
                label_taxonomy_json=label_taxonomy_json,
                label_taxonomy_oss_key=label_taxonomy_oss_key,
                exclude_labels=exclude_labels,
                label_model=label_model,
                label_model_version=label_model_version,
                label_batch_size=label_batch_size,
                label_timezone=label_timezone,
            )
            result = input_df.apply(
                _job3_label_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "labeled_frame_count": "int64",
                    "taxonomy_version": "string",
                    "label_model_version": "string",
                    "payload_relpath": "string",
                    "frame_labels_relpath": "string",
                },
                skip_infer=True,
            ).execute().fetch()
            if result.empty:
                raise RuntimeError("Job3 label returned no rows")
            row = result.iloc[0]

        print(
            f"Job3 label done: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"labeled_frames={row['labeled_frame_count']} "
            f"taxonomy={row['taxonomy_version']} model={row['label_model_version']} "
            f"payload={row['payload_relpath']}"
        )
        print(f"NEXT_NODE_PARAM run_id={row['run_id']}")
        print(f"NEXT_NODE_PARAM clip_id={row['clip_id']}")
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


main()
