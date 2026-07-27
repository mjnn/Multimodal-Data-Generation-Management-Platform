"""MaxFrame AI Function helpers for DataWorks Job2/3/4 nodes.

Paste into PyODPS nodes via:
  python scripts/bundle_dataworks_node.py dataworks/job2_asr_node.py

Do not import business modules from DPE UDF; call these from Driver only.
"""

from __future__ import annotations

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
