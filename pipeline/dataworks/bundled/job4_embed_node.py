from __future__ import annotations

# job4_embed_node.py — paste this single file into DataWorks PyODPS3

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

# =============================================================================
# DataWorks PyODPS 3 节点：Job4-向量化（MaxFrame + DPE）
#
# ★★★ DataWorks 必须粘贴 bundled 整文件，勿粘贴本文件 ★★★
#   python scripts/bundle_dataworks_node.py dataworks/job4_embed_node.py
#   → 粘贴 dataworks/bundled/job4_embed_node.py（约 1500+ 行，含 mf_ai_function 内联）
#
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
#
# 读 Job3：clips/{clip_id}/runs/{run_id}/job3/job3_mc_payload.json（抽样帧）
# 读 Job2：clips/{clip_id}/runs/{run_id}/job2/job2_asr_payload.json（ASR 分段）
# 写 Job4：clips/{clip_id}/runs/{run_id}/job4/embeddings.jsonl
#          clips/{clip_id}/runs/{run_id}/job4/job4_mc_payload.json
#
# storage_mode：separate | unified | both（见 config.yaml cloud.job4_embed）
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
#   job4_config_json=
#   oss_vl_access_key_id=           # VL 图像 embedding（qwen3-vl-embedding）读 OSS
#   oss_vl_access_key_secret=
#   ※ oss_ram_role_arn 仅 DPE 挂载；IMAGE_URL 须 AK/SK
#
# 节点参数
#   clip_id=sha256:...
#   run_id=<Job1 相同>
#   storage_mode=separate          # separate|unified|both，留空=配置默认
#   embed_batch_size=64
#   image_embed_model=
#   text_embed_model=
#   unified_embed_model=
#   total_rpm_limit=12000          # AI Function running_options；0=不传
#   request_timeout=300            # 单次请求超时（秒）；0=不传
#   ai_memory=8G                   # AI Function Worker 内存；留空=不传
# =============================================================================


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

DEFAULT_JOB4_CONFIG: dict[str, Any] = {
    "provider": "maxframe_ai_function",
    "storage_mode": "separate",
    "models": {
        "image": {"model": "", "model_version": "", "dim": 768},
        "text": {"model": "", "model_version": "", "dim": 768},
        "unified": {"model": "", "model_version": "", "dim": 768},
    },
    "batch_size": 64,
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
        "ai_embed_texts",
        "ai_embed_oss_image_urls",
        "is_vl_embedding_model",
        "build_vl_oss_storage_options",
        "oss_key_for_frame_image",
        "extract_asr_plain_text",
    ):
        if hasattr(module, name):
            globals()[name] = getattr(module, name)


_load_mf_ai_function()


def _asr_text_for_embed(segment: dict[str, Any]) -> str:
    raw = segment.get("asr_text")
    if "extract_asr_plain_text" in globals():
        return extract_asr_plain_text(raw)
    return str(raw or "").strip()


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
    ak = get_arg("oss_vl_access_key_id") or get_arg("oss_access_key_id") or ""
    sk = get_arg("oss_vl_access_key_secret") or get_arg("oss_access_key_secret") or ""
    return ak, sk


def load_job4_config() -> dict[str, Any]:
    raw = get_arg("job4_config_json")
    if not raw:
        return DEFAULT_JOB4_CONFIG
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError("job4_config_json must be a JSON object")
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stub_vector(dim: int) -> list[float]:
    return [0.0] * dim


def _resolve_model_version(model_cfg: dict[str, Any]) -> str:
    model = str(model_cfg.get("model") or "")
    version = str(model_cfg.get("model_version") or "")
    if version:
        return version
    return "none" if not model else model


def _resolve_frame_image_path(parsed_root: Path, frame: dict[str, Any]) -> Path:
    raw = str(frame.get("image_relpath") or frame.get("image_path") or "").strip().lstrip("/")
    candidates = [parsed_root / raw]
    parsed_marker = "/parsed/"
    if parsed_marker in raw:
        candidates.append(parsed_root / raw.rsplit(parsed_marker, 1)[-1].lstrip("/"))
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0]


def _embed_frame_stub(
    *,
    frame: dict[str, Any],
    parsed_root: Path,
    model_cfg: dict[str, Any],
    storage_mode: str,
) -> dict[str, Any]:
    dim = int(model_cfg.get("dim") or 768)
    image_path = _resolve_frame_image_path(parsed_root, frame)
    image_bytes = image_path.read_bytes() if image_path.is_file() else b""
    vector = _stub_vector(dim)
    model = str(model_cfg.get("model") or "")
    if model:
        # MC AI 接入点：当前版本输出零向量占位，保留 dim/model_version。
        pass
    return {
        "object_type": "frame",
        "object_id": str(frame["frame_id"]),
        "timestamp_ns": int(frame["timestamp_ns"]),
        "start_ns": None,
        "end_ns": None,
        "vector_json": vector,
        "model_version": _resolve_model_version(model_cfg),
        "dim": dim,
        "storage_mode": storage_mode,
        "source_bytes": len(image_bytes),
    }


def _embed_audio_segment_stub(
    *,
    segment: dict[str, Any],
    model_cfg: dict[str, Any],
    storage_mode: str,
) -> dict[str, Any]:
    dim = int(model_cfg.get("dim") or 768)
    asr_text = _asr_text_for_embed(segment)
    vector = _stub_vector(dim)
    model = str(model_cfg.get("model") or "")
    if model:
        pass
    return {
        "object_type": "audio_segment",
        "object_id": str(int(segment["segment_id"])),
        "timestamp_ns": int(segment["start_ns"]),
        "start_ns": int(segment["start_ns"]),
        "end_ns": int(segment["end_ns"]),
        "vector_json": vector,
        "model_version": _resolve_model_version(model_cfg),
        "dim": dim,
        "storage_mode": storage_mode,
        "source_text_len": len(asr_text),
    }


def _merge_model_cfg(
    base: dict[str, Any],
    *,
    model_override: str,
    version_override: str,
) -> dict[str, Any]:
    merged = dict(base)
    if model_override:
        merged["model"] = model_override
    if version_override:
        merged["model_version"] = version_override
    return merged


def build_embeddings(
    *,
    labeled_frames: list[dict[str, Any]],
    audio_segments: list[dict[str, Any]],
    parsed_root: Path,
    job4_config: dict[str, Any],
    storage_mode: str,
    model_overrides: dict[str, str],
    version_overrides: dict[str, str],
    batch_size: int,
) -> list[dict[str, Any]]:
    models = job4_config.get("models") or DEFAULT_JOB4_CONFIG["models"]
    image_cfg = _merge_model_cfg(
        models.get("image") or {},
        model_override=model_overrides.get("image", ""),
        version_override=version_overrides.get("image", ""),
    )
    text_cfg = _merge_model_cfg(
        models.get("text") or {},
        model_override=model_overrides.get("text", ""),
        version_override=version_overrides.get("text", ""),
    )
    unified_cfg = _merge_model_cfg(
        models.get("unified") or {},
        model_override=model_overrides.get("unified", ""),
        version_override=version_overrides.get("unified", ""),
    )

    embeddings: list[dict[str, Any]] = []

    def process_frames(cfg: dict[str, Any], mode: str) -> None:
        for start in range(0, len(labeled_frames), batch_size):
            batch = labeled_frames[start : start + batch_size]
            for frame in batch:
                embeddings.append(
                    _embed_frame_stub(
                        frame=frame,
                        parsed_root=parsed_root,
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )

    def process_segments(cfg: dict[str, Any], mode: str) -> None:
        for start in range(0, len(audio_segments), batch_size):
            batch = audio_segments[start : start + batch_size]
            for segment in batch:
                embeddings.append(
                    _embed_audio_segment_stub(
                        segment=segment,
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )

    if storage_mode in {"separate", "both"}:
        process_frames(image_cfg, "separate")
        process_segments(text_cfg, "separate")

    if storage_mode in {"unified", "both"}:
        process_frames(unified_cfg, "unified")
        process_segments(unified_cfg, "unified")

    if storage_mode not in {"separate", "unified", "both"}:
        raise ValueError(f"Unsupported storage_mode: {storage_mode}")

    return embeddings


def _embed_texts_with_ai(
    texts: list[str],
    model_cfg: dict[str, Any],
    odps_entry: Any,
    *,
    modelset_project: str,
    parallel_partitions: int,
    storage_mode: str,
    object_type: str,
    object_ids: list[str],
    timestamps: list[int],
    starts: list[int | None],
    ends: list[int | None],
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    model = str(model_cfg.get("model") or "")
    if not model:
        return []
    if "ai_embed_texts" not in globals():
        raise RuntimeError(
            "mf_ai_function not loaded. DataWorks 请粘贴 "
            "dataworks/bundled/job4_embed_node.py（非 job4_embed_node.py）。"
            "本地生成: python scripts/bundle_dataworks_node.py dataworks/job4_embed_node.py"
        )

    vectors = ai_embed_texts(
        texts,
        model,
        odps_entry,
        modelset_project=modelset_project,
        parallel_partitions=parallel_partitions,
        total_rpm_limit=total_rpm_limit,
        request_timeout=request_timeout,
        ai_memory=ai_memory,
    )
    dim = int(model_cfg.get("dim") or (len(vectors[0]) if vectors and vectors[0] else 768))
    model_version = _resolve_model_version(model_cfg)
    results: list[dict[str, Any]] = []
    for idx, vector in enumerate(vectors):
        vec = vector if vector else _stub_vector(dim)
        results.append(
            {
                "object_type": object_type,
                "object_id": object_ids[idx],
                "timestamp_ns": timestamps[idx],
                "start_ns": starts[idx],
                "end_ns": ends[idx],
                "vector_json": vec,
                "model_version": model_version,
                "dim": len(vec),
                "storage_mode": storage_mode,
            }
        )
    return results


def build_embeddings_with_ai(
    *,
    labeled_frames: list[dict[str, Any]],
    audio_segments: list[dict[str, Any]],
    job4_config: dict[str, Any],
    storage_mode: str,
    model_overrides: dict[str, str],
    version_overrides: dict[str, str],
    odps_entry: Any,
    modelset_project: str,
    parallel_partitions: int,
    cloud_region: str,
    oss_bucket: str,
    parsed_relpath: str | None = None,
    vl_storage_options: dict[str, str] | None = None,
    total_rpm_limit: int | None = None,
    request_timeout: int | None = None,
    ai_memory: str | None = None,
) -> list[dict[str, Any]]:
    models = job4_config.get("models") or DEFAULT_JOB4_CONFIG["models"]
    image_cfg = _merge_model_cfg(
        models.get("image") or {},
        model_override=model_overrides.get("image", ""),
        version_override=version_overrides.get("image", ""),
    )
    text_cfg = _merge_model_cfg(
        models.get("text") or {},
        model_override=model_overrides.get("text", ""),
        version_override=version_overrides.get("text", ""),
    )
    unified_cfg = _merge_model_cfg(
        models.get("unified") or {},
        model_override=model_overrides.get("unified", ""),
        version_override=version_overrides.get("unified", ""),
    )

    embeddings: list[dict[str, Any]] = []
    region_id = cloud_region.replace("_", "-")

    def add_frame_embeddings(cfg: dict[str, Any], mode: str) -> None:
        if not str(cfg.get("model") or ""):
            for frame in labeled_frames:
                embeddings.append(
                    _embed_frame_stub(
                        frame=frame,
                        parsed_root=Path("."),
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )
            return
        model = str(cfg.get("model") or "")
        use_vl_image = (
            "is_vl_embedding_model" in globals()
            and is_vl_embedding_model(model)
            and "ai_embed_oss_image_urls" in globals()
        )
        if use_vl_image:
            if not vl_storage_options:
                raise ValueError(
                    "image_embed_model is VL embedding but OSS VL AK/SK missing. "
                    "Set oss_vl_access_key_id + oss_vl_access_key_secret"
                )
            frame_parsed_relpath = (parsed_relpath or "").strip() or None
            image_urls: list[str] = []
            for frame in labeled_frames:
                image_relpath = str(frame.get("image_relpath") or frame.get("image_path") or "")
                if "oss_key_for_frame_image" in globals():
                    oss_key = oss_key_for_frame_image(
                        image_relpath,
                        parsed_relpath=frame_parsed_relpath,
                    )
                else:
                    oss_key = image_relpath.strip("/")
                image_urls.append(
                    f"oss://oss-{region_id}-internal.aliyuncs.com/{oss_bucket}/{oss_key}"
                )
            vectors = ai_embed_oss_image_urls(
                image_urls,
                model,
                odps_entry,
                storage_options=vl_storage_options,
                modelset_project=modelset_project,
                parallel_partitions=parallel_partitions,
                total_rpm_limit=total_rpm_limit,
                request_timeout=request_timeout,
                ai_memory=ai_memory,
            )
            dim = int(cfg.get("dim") or (len(vectors[0]) if vectors and vectors[0] else 768))
            model_version = _resolve_model_version(cfg)
            for frame, vector in zip(labeled_frames, vectors):
                vec = vector if vector else _stub_vector(dim)
                embeddings.append(
                    {
                        "object_type": "frame",
                        "object_id": str(frame["frame_id"]),
                        "timestamp_ns": int(frame["timestamp_ns"]),
                        "start_ns": None,
                        "end_ns": None,
                        "vector_json": vec,
                        "model_version": model_version,
                        "dim": len(vec),
                        "storage_mode": mode,
                    }
                )
            return
        texts = []
        for frame in labeled_frames:
            image_relpath = str(frame.get("image_relpath") or frame.get("image_path") or "").strip("/")
            texts.append(
                f"oss://oss-{region_id}-internal.aliyuncs.com/{oss_bucket}/{image_relpath}"
            )
        embeddings.extend(
            _embed_texts_with_ai(
                texts,
                cfg,
                odps_entry,
                modelset_project=modelset_project,
                parallel_partitions=parallel_partitions,
                storage_mode=mode,
                object_type="frame",
                object_ids=[str(f["frame_id"]) for f in labeled_frames],
                timestamps=[int(f["timestamp_ns"]) for f in labeled_frames],
                starts=[None] * len(labeled_frames),
                ends=[None] * len(labeled_frames),
                total_rpm_limit=total_rpm_limit,
                request_timeout=request_timeout,
                ai_memory=ai_memory,
            )
        )

    def add_segment_embeddings(cfg: dict[str, Any], mode: str) -> None:
        if not str(cfg.get("model") or ""):
            for segment in audio_segments:
                embeddings.append(
                    _embed_audio_segment_stub(
                        segment=segment,
                        model_cfg=cfg,
                        storage_mode=mode,
                    )
                )
            return
        texts = [_asr_text_for_embed(segment) for segment in audio_segments]
        embeddings.extend(
            _embed_texts_with_ai(
                texts,
                cfg,
                odps_entry,
                modelset_project=modelset_project,
                parallel_partitions=parallel_partitions,
                storage_mode=mode,
                object_type="audio_segment",
                object_ids=[str(int(s["segment_id"])) for s in audio_segments],
                timestamps=[int(s["start_ns"]) for s in audio_segments],
                starts=[int(s["start_ns"]) for s in audio_segments],
                ends=[int(s["end_ns"]) for s in audio_segments],
                total_rpm_limit=total_rpm_limit,
                request_timeout=request_timeout,
                ai_memory=ai_memory,
            )
        )

    if storage_mode in {"separate", "both"}:
        add_frame_embeddings(image_cfg, "separate")
        add_segment_embeddings(text_cfg, "separate")
    if storage_mode in {"unified", "both"}:
        add_frame_embeddings(unified_cfg, "unified")
        add_segment_embeddings(unified_cfg, "unified")
    if storage_mode not in {"separate", "unified", "both"}:
        raise ValueError(f"Unsupported storage_mode: {storage_mode}")
    return embeddings


def _build_job4_prepare_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
):
    def _job4_prepare_row(row):
        job3_payload_path = Path(mount_path) / row["job3_payload_relpath"]
        job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
        if not job3_payload_path.is_file():
            raise FileNotFoundError(f"Job3 payload not found: {job3_payload_path}")
        if not job2_payload_path.is_file():
            raise FileNotFoundError(f"Job2 payload not found: {job2_payload_path}")

        job3_payload = _read_json(job3_payload_path)
        job2_payload = _read_json(job2_payload_path)
        labeled_frames = job3_payload.get("labeled_frames") or []
        audio_segments = job2_payload.get("audio_segments") or []
        if not labeled_frames and not audio_segments:
            raise ValueError("Job4 has no frames or audio segments to embed")

        return {
            "clip_id": str(job3_payload.get("clip_id") or row["clip_id"]),
            "run_id": str(job3_payload.get("run_id") or row["run_id"]),
            "parsed_relpath": row["parsed_relpath"],
            "job4_relpath": row["job4_relpath"],
            "labeled_frames_json": json.dumps(labeled_frames, ensure_ascii=False),
            "audio_segments_json": json.dumps(audio_segments, ensure_ascii=False),
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job4_prepare_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job4_write_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    storage_mode: str,
):
    def _job4_write_row(row):
        embeddings = json.loads(str(row["embeddings_json"]))
        labeled_frames = json.loads(str(row["labeled_frames_json"]))
        audio_segments = json.loads(str(row["audio_segments_json"]))

        job4_root = Path(mount_path) / row["job4_relpath"]
        job4_root.mkdir(parents=True, exist_ok=True)
        embeddings_path = job4_root / "embeddings.jsonl"
        with embeddings_path.open("w", encoding="utf-8") as embed_file:
            for item in embeddings:
                embed_file.write(json.dumps(item, ensure_ascii=False) + "\n")

        payload = {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "storage_mode": storage_mode,
            "embeddings": embeddings,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "processed_at": _utc_now_iso(),
        }
        payload_path = job4_root / "job4_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": row["clip_id"],
            "run_id": row["run_id"],
            "storage_mode": storage_mode,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "payload_relpath": f"{row['job4_relpath']}/job4_mc_payload.json",
            "embeddings_relpath": f"{row['job4_relpath']}/embeddings.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job4_write_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _build_job4_embed_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options: dict[str, str],
    job4_config: dict[str, Any],
    storage_mode: str,
    model_overrides: dict[str, str],
    version_overrides: dict[str, str],
    batch_size: int,
):
    def _job4_embed_row(row):
        job3_payload_path = Path(mount_path) / row["job3_payload_relpath"]
        job2_payload_path = Path(mount_path) / row["job2_payload_relpath"]
        if not job3_payload_path.is_file():
            raise FileNotFoundError(f"Job3 payload not found: {job3_payload_path}")
        if not job2_payload_path.is_file():
            raise FileNotFoundError(f"Job2 payload not found: {job2_payload_path}")

        job3_payload = _read_json(job3_payload_path)
        job2_payload = _read_json(job2_payload_path)
        labeled_frames = job3_payload.get("labeled_frames") or []
        audio_segments = job2_payload.get("audio_segments") or []

        if not labeled_frames and not audio_segments:
            raise ValueError("Job4 has no frames or audio segments to embed")

        parsed_root = Path(mount_path) / row["parsed_relpath"]
        embeddings = build_embeddings(
            labeled_frames=labeled_frames,
            audio_segments=audio_segments,
            parsed_root=parsed_root,
            job4_config=job4_config,
            storage_mode=storage_mode,
            model_overrides=model_overrides,
            version_overrides=version_overrides,
            batch_size=batch_size,
        )

        job4_root = Path(mount_path) / row["job4_relpath"]
        job4_root.mkdir(parents=True, exist_ok=True)

        embeddings_path = job4_root / "embeddings.jsonl"
        with embeddings_path.open("w", encoding="utf-8") as embed_file:
            for item in embeddings:
                embed_file.write(json.dumps(item, ensure_ascii=False) + "\n")

        payload = {
            "clip_id": str(job3_payload.get("clip_id") or row["clip_id"]),
            "run_id": str(job3_payload.get("run_id") or row["run_id"]),
            "storage_mode": storage_mode,
            "embeddings": embeddings,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "processed_at": _utc_now_iso(),
        }
        payload_path = job4_root / "job4_mc_payload.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "clip_id": payload["clip_id"],
            "run_id": payload["run_id"],
            "storage_mode": storage_mode,
            "frame_count": len(labeled_frames),
            "audio_segment_count": len(audio_segments),
            "embedding_count": len(embeddings),
            "payload_relpath": f"{row['job4_relpath']}/job4_mc_payload.json",
            "embeddings_relpath": f"{row['job4_relpath']}/embeddings.jsonl",
        }

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(_job4_embed_row)
    wrapped = with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)(wrapped)
    return wrapped


def _write_job4_artifacts_to_oss(
    *,
    clip_id: str,
    run_id: str,
    job4_relpath: str,
    labeled_frames: list[dict[str, Any]],
    audio_segments: list[dict[str, Any]],
    embeddings: list[dict[str, Any]],
    storage_mode: str,
    oss_bucket: str,
    cloud_region: str,
    account: Any,
) -> dict[str, Any]:
    """Write embeddings.jsonl + job4_mc_payload.json on Driver (avoid MaxFrame 8MB tunnel)."""
    endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    embeddings_key = f"{job4_relpath}/embeddings.jsonl"
    payload_key = f"{job4_relpath}/job4_mc_payload.json"
    embeddings_text = "".join(
        json.dumps(item, ensure_ascii=False) + "\n" for item in embeddings
    )
    payload = {
        "clip_id": clip_id,
        "run_id": run_id,
        "storage_mode": storage_mode,
        "embeddings": embeddings,
        "frame_count": len(labeled_frames),
        "audio_segment_count": len(audio_segments),
        "embedding_count": len(embeddings),
        "processed_at": _utc_now_iso(),
    }
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(f"Job4 writing oss://{oss_bucket}/{embeddings_key} ({len(embeddings_text)} bytes)")
    write_oss_object_text(
        bucket_name=oss_bucket,
        object_key=embeddings_key,
        endpoint=endpoint,
        account=account,
        text=embeddings_text,
        region=cloud_region,
        get_arg=get_arg,
    )
    print(f"Job4 writing oss://{oss_bucket}/{payload_key} ({len(payload_text)} bytes)")
    write_oss_object_text(
        bucket_name=oss_bucket,
        object_key=payload_key,
        endpoint=endpoint,
        account=account,
        text=payload_text,
        region=cloud_region,
        get_arg=get_arg,
    )
    return {
        "clip_id": clip_id,
        "run_id": run_id,
        "storage_mode": storage_mode,
        "frame_count": len(labeled_frames),
        "audio_segment_count": len(audio_segments),
        "embedding_count": len(embeddings),
        "payload_relpath": payload_key,
        "embeddings_relpath": embeddings_key,
    }


def _load_job4_inputs_from_oss(
    *,
    oss_bucket: str,
    cloud_region: str,
    account: Any,
    job3_payload_key: str,
    job2_payload_key: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, str]:
    endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    job3_payload = read_oss_json_object(
        bucket_name=oss_bucket,
        object_key=job3_payload_key,
        endpoint=endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if job3_payload is None:
        raise FileNotFoundError(
            f"Job3 payload not found: oss://{oss_bucket}/{job3_payload_key}"
        )
    job2_payload = read_oss_json_object(
        bucket_name=oss_bucket,
        object_key=job2_payload_key,
        endpoint=endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if job2_payload is None:
        raise FileNotFoundError(
            f"Job2 payload not found: oss://{oss_bucket}/{job2_payload_key}"
        )
    labeled_frames = job3_payload.get("labeled_frames") or []
    audio_segments = job2_payload.get("audio_segments") or []
    if not labeled_frames and not audio_segments:
        raise ValueError("Job4 has no frames or audio segments to embed")
    clip_id = str(job3_payload.get("clip_id") or "")
    run_id = str(job3_payload.get("run_id") or "")
    return labeled_frames, audio_segments, clip_id, run_id


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job4_embed"):
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

    job4_config = load_job4_config()
    storage_mode = (
        get_arg("storage_mode") or str(job4_config.get("storage_mode") or "separate")
    ).strip().lower()
    batch_size = get_int_arg("embed_batch_size", int(job4_config.get("batch_size", 64)))

    model_overrides = {
        "image": get_arg("image_embed_model") or "",
        "text": get_arg("text_embed_model") or "",
        "unified": get_arg("unified_embed_model") or "",
    }
    version_overrides = {
        "image": get_arg("image_embed_model_version") or "",
        "text": get_arg("text_embed_model_version") or "",
        "unified": get_arg("unified_embed_model_version") or "",
    }
    ai_modelset_project = get_arg("ai_modelset_project") or "bigdata_public_modelset"
    ai_parallel_partitions = get_int_arg("ai_parallel_partitions", 4)
    total_rpm_limit = get_int_arg("total_rpm_limit", 12000)
    request_timeout = get_int_arg("request_timeout", 300)
    ai_memory = get_arg("ai_memory", "8G") or ""
    ai_cu_quota_name = get_arg("ai_cu_quota_name")
    ai_gu_quota_name = get_arg("ai_gu_quota_name")
    oss_vl_access_key_id, oss_vl_access_key_secret = _resolve_oss_vl_ak_sk()
    vl_storage_options = (
        build_vl_oss_storage_options(
            role_arn=role_arn,
            oss_access_key_id=oss_vl_access_key_id,
            oss_access_key_secret=oss_vl_access_key_secret,
        )
        if "build_vl_oss_storage_options" in globals()
        else None
    )

    clip_prefix = prefix_template.format(clip_id=clip_id).strip("/")
    parsed_relpath = f"{clip_prefix}/runs/{run_id}/parsed"
    job2_relpath = f"{clip_prefix}/runs/{run_id}/job2"
    job3_relpath = f"{clip_prefix}/runs/{run_id}/job3"
    job4_relpath = f"{clip_prefix}/runs/{run_id}/job4"

    models = job4_config.get("models") or {}
    embed_model_names = [
        model_overrides["image"] or str((models.get("image") or {}).get("model") or ""),
        model_overrides["text"] or str((models.get("text") or {}).get("model") or ""),
        model_overrides["unified"] or str((models.get("unified") or {}).get("model") or ""),
    ]
    primary_embed_model = next((name for name in embed_model_names if name), "")

    _apply_dpe_runtime_settings(dpe_image)
    mf_options.local_execution.enabled = False

    if primary_embed_model and "prepare_mf_ai_runtime" in globals():
        prepare_mf_ai_runtime(
            model_name=primary_embed_model,
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
        "job2_payload_relpath": f"{job2_relpath}/job2_asr_payload.json",
        "job3_payload_relpath": f"{job3_relpath}/job3_mc_payload.json",
        "job4_relpath": job4_relpath,
    }
    input_df = md.DataFrame(pd.DataFrame([job_row]))

    any_model = bool(primary_embed_model)

    try:
        print(f"Logview: {session.get_logview_address()}")
        print(f"Job4 storage_mode={storage_mode}")

        if any_model:
            ak_hint = (
                f"{oss_vl_access_key_id[:4]}...{oss_vl_access_key_id[-4:]}"
                if len(oss_vl_access_key_id) >= 8
                else "(empty)"
            )
            print(f"Job4 MaxFrame AI Function embed oss_ak_hint={ak_hint}")
            print(
                f"Job4 AI running_options={{total_rpm_limit={total_rpm_limit if total_rpm_limit > 0 else 'off'}, "
                f"request_timeout={request_timeout if request_timeout > 0 else 'off'}, "
                f"memory={ai_memory or 'off'}}}"
            )
            image_embed_model = embed_model_names[0]
            if (
                image_embed_model
                and "is_vl_embedding_model" in globals()
                and is_vl_embedding_model(image_embed_model)
                and not vl_storage_options
            ):
                raise ValueError(
                    "image_embed_model requires oss_vl_access_key_id/secret for OSS IMAGE_URL"
                )
            job3_payload_key = f"{job3_relpath}/job3_mc_payload.json"
            job2_payload_key = f"{job2_relpath}/job2_asr_payload.json"
            print(
                f"Job4 reading inputs from OSS: {job3_payload_key}, {job2_payload_key}"
            )
            labeled_frames, audio_segments, resolved_clip_id, resolved_run_id = (
                _load_job4_inputs_from_oss(
                    oss_bucket=oss_bucket,
                    cloud_region=cloud_region,
                    account=account,
                    job3_payload_key=job3_payload_key,
                    job2_payload_key=job2_payload_key,
                )
            )
            clip_id = resolved_clip_id or clip_id
            run_id = resolved_run_id or run_id

            embeddings = build_embeddings_with_ai(
                labeled_frames=labeled_frames,
                audio_segments=audio_segments,
                job4_config=job4_config,
                storage_mode=storage_mode,
                model_overrides=model_overrides,
                version_overrides=version_overrides,
                odps_entry=o,  # type: ignore[name-defined]
                modelset_project=ai_modelset_project,
                parallel_partitions=ai_parallel_partitions,
                cloud_region=cloud_region,
                oss_bucket=oss_bucket,
                parsed_relpath=parsed_relpath,
                vl_storage_options=vl_storage_options,
                total_rpm_limit=total_rpm_limit if total_rpm_limit > 0 else None,
                request_timeout=request_timeout if request_timeout > 0 else None,
                ai_memory=ai_memory.strip() if ai_memory.strip() else None,
            )

            row = _write_job4_artifacts_to_oss(
                clip_id=clip_id,
                run_id=run_id,
                job4_relpath=job4_relpath,
                labeled_frames=labeled_frames,
                audio_segments=audio_segments,
                embeddings=embeddings,
                storage_mode=storage_mode,
                oss_bucket=oss_bucket,
                cloud_region=cloud_region,
                account=account,
            )
        else:
            print("WARN: embed models empty; writing zero-vector stubs (model_version=none)")
            _job4_embed_row = _build_job4_embed_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=oss_mount_url,
                mount_path=mount_path,
                storage_options=_storage_options(role_arn, account),
                job4_config=job4_config,
                storage_mode=storage_mode,
                model_overrides=model_overrides,
                version_overrides=version_overrides,
                batch_size=batch_size,
            )
            result = input_df.apply(
                _job4_embed_row,
                axis=1,
                output_type="dataframe",
                result_type="expand",
                dtypes={
                    "clip_id": "string",
                    "run_id": "string",
                    "storage_mode": "string",
                    "frame_count": "int64",
                    "audio_segment_count": "int64",
                    "embedding_count": "int64",
                    "payload_relpath": "string",
                    "embeddings_relpath": "string",
                },
                skip_infer=True,
            ).execute().fetch()
            if result.empty:
                raise RuntimeError("Job4 embed returned no rows")
            row = result.iloc[0]

        print(
            f"Job4 embed done: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"mode={row['storage_mode']} frames={row['frame_count']} "
            f"audio_segments={row['audio_segment_count']} "
            f"embeddings={row['embedding_count']} payload={row['payload_relpath']}"
        )
        print(f"NEXT_NODE_PARAM run_id={row['run_id']}")
        print(f"NEXT_NODE_PARAM clip_id={row['clip_id']}")
        print("PIPELINE_DONE clip_id={clip_id} run_id={run_id}".format(
            clip_id=row["clip_id"], run_id=row["run_id"]
        ))
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


main()
