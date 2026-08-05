"""MaxFrame AI 运行时：session 生命周期与模型调用原语。"""
from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..exceptions import ConfigurationError
from .config import DEFAULT_MODELSET_PROJECT, McBackendConfig

_DASHSCOPE_MODEL_HINTS = (
    "qwen3.",
    "qwen3-",
    "qwen3-vl",
    "qwen-vl",
    "text-embedding",
    "deepseek-v4",
    "deepseek-v3",
    "embedding",
    "paraformer",
    "sensevoice",
)


def require_maxframe() -> Any:
    try:
        import maxframe  # noqa: F401
        import maxframe.dataframe as md  # noqa: F401
        import pandas as pd  # noqa: F401
    except ImportError as exc:
        raise ConfigurationError(
            "MODEL_BACKEND=mc requires optional deps: pip install 'oms-multimodal-sdk[mc]' "
            "(maxframe, pyodps, pandas)"
        ) from exc
    return md


def resolve_odps_entry(entry: Any | None) -> Any:
    if entry is not None:
        return entry
    access_id = os.getenv("ODPS_ACCESS_ID", os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID", "")).strip()
    secret = os.getenv("ODPS_ACCESS_KEY", os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", "")).strip()
    project = os.getenv("ODPS_PROJECT", "").strip()
    endpoint = os.getenv("ODPS_ENDPOINT", "").strip()
    if not all([access_id, secret, project, endpoint]):
        raise ConfigurationError(
            "MODEL_BACKEND=mc requires odps_entry or ODPS_ACCESS_ID/ODPS_ACCESS_KEY/"
            "ODPS_PROJECT/ODPS_ENDPOINT env vars"
        )
    try:
        from odps import ODPS
    except ImportError as exc:
        raise ConfigurationError(
            "MODEL_BACKEND=mc requires pyodps: pip install 'oms-multimodal-sdk[mc]'"
        ) from exc
    return ODPS(access_id, secret, project=project, endpoint=endpoint)


def is_asr_capable_model(model_name: str) -> bool:
    lower = model_name.lower()
    return any(hint in lower for hint in ("asr", "paraformer", "sensevoice", "fun-asr"))


def is_public_modelset_model(model_name: str) -> bool:
    # qwen3-asr-flash 等已在 bigdata_public_modelset；须 read_odps_model，
    # 勿走 ManagedTextLLM（本地/Driver 会报 engine 不接受或缺 prompt_template）。
    if is_asr_capable_model(model_name):
        return True
    lower = model_name.lower()
    return any(hint in lower for hint in _DASHSCOPE_MODEL_HINTS)


def escape_mf_template_text(text: str) -> str:
    """Escape ``{``/``}`` so MaxFrame prompt formatting does not treat JSON as fields."""
    return (text or "").replace("{", "{{").replace("}", "}}")


def is_omni_model_name(model_name: str) -> bool:
    return "omni" in model_name.lower()


def ensure_odps_catalog_endpoint(odps_entry: Any) -> None:
    catalog = getattr(odps_entry, "catalog_endpoint", None)
    if not catalog:
        catalog = getattr(odps_entry, "_catalog_endpoint", None)
    if not catalog:
        return
    catalog_str = str(catalog).strip()
    if catalog_str.startswith(("http://", "https://")):
        return
    odps_entry._catalog_endpoint = f"https://{catalog_str.lstrip('/')}"
    odps_entry._catalog_rest = None


def configure_mf_ai_engine(*, dpe_image: str | None = None) -> None:
    from maxframe.config import options as mf_options

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
    from maxframe.config import options as mf_options

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
    configure_mf_ai_engine(dpe_image=dpe_image)
    apply_ai_quota(
        cu_quota_name=cu_quota_name,
        gu_quota_name=gu_quota_name,
        model_name=model_name,
    )


def create_ai_model(
    model_name: str,
    odps_entry: Any,
    *,
    modelset_project: str = DEFAULT_MODELSET_PROJECT,
):
    if is_public_modelset_model(model_name):
        from maxframe.learn.utils import read_odps_model

        ensure_odps_catalog_endpoint(odps_entry)
        return read_odps_model(model_name, project=modelset_project, odps_entry=odps_entry)
    from maxframe.learn.contrib.llm.models.managed import ManagedTextLLM

    return ManagedTextLLM(name=model_name)


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


def _fetch_series(result_df: Any, preferred: tuple[str, ...]) -> list[Any]:
    pdf = result_df.execute().fetch()
    columns = list(pdf.columns)
    col = _output_column(columns, preferred)
    if col not in columns:
        raise ValueError(f"AI output column {col!r} not in {columns}")
    return pdf[col].tolist()


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        return {}
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return {"raw": cleaned}
    try:
        loaded = json.loads(match.group(0))
        return loaded if isinstance(loaded, dict) else {"raw": cleaned}
    except json.JSONDecodeError:
        return {"raw": cleaned}


@dataclass
class McRuntime:
    """共享 MaxFrame session；按 model 配置 quota 后调用 AI Function。"""

    config: McBackendConfig
    odps_entry: Any = field(init=False)
    _session: Any | None = field(default=None, init=False, repr=False)
    _prepared_models: set[str] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        require_maxframe()
        self.odps_entry = resolve_odps_entry(self.config.odps_entry)

    def prepare_for_model(self, model_name: str) -> None:
        if model_name in self._prepared_models:
            return
        prepare_mf_ai_runtime(
            model_name=model_name,
            dpe_image=self.config.dpe_image,
            cu_quota_name=self.config.cu_quota_name,
            gu_quota_name=self.config.gu_quota_name,
        )
        self._prepared_models.add(model_name)

    def ensure_session(self) -> Any:
        if self._session is None:
            from maxframe import new_session

            self._session = new_session(self.odps_entry)
        return self._session

    def destroy(self) -> None:
        if self._session is not None:
            self._session.destroy()
            self._session = None

    @contextmanager
    def session_scope(self) -> Iterator[McRuntime]:
        try:
            self.ensure_session()
            yield self
        finally:
            self.destroy()


def running_options_for(config: McBackendConfig) -> dict[str, Any] | None:
    return build_ai_running_options(
        total_rpm_limit=config.total_rpm_limit,
        request_timeout=config.request_timeout_sec,
        ai_memory=config.ai_memory,
    )
