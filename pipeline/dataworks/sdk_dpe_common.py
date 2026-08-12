# =============================================================================
# SDK DPE 节点共享：Driver 批量编排 + DPE UDF 装饰器
# =============================================================================

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

import pandas as pd

# 与 workflow-params-sdk-pipeline-p0.example 一致；节点/工作流未配参时的兜底（非密钥）
_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipeline-bucket2",
    "cloud_region": "cn_shanghai",
    "sdk_table_prefix": "aig_sdk__",
    "table_prefix": "aig_sdk__",
    "scan_prefix": "rosbags/",
    "mount_path": "/mnt/oss",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "rosbag_sdk_dpe",
    "batch_rows": "1",
    "model_backend": "mc",
    "mc_image_mode": "base64",
    "mc_modelset_project": "bigdata_public_modelset",
}


def _parse_skynet_args(raw: str) -> dict[str, str]:
    """Parse DataWorks SKYNET_ARGS (semicolon key=value or JSON object)."""
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


def _all_dw_arg_sources() -> dict[str, str]:
    """args (node) > env aliases > SKYNET_ARGS > code defaults."""
    merged: dict[str, str] = dict(_PROJECT_DEFAULTS)
    merged.update(_parse_skynet_args(os.environ.get("SKYNET_ARGS", "")))
    for env_name, arg_name in (
        ("OSS_BUCKET", "oss_bucket"),
        ("CLOUD_REGION", "cloud_region"),
        ("DPE_IMAGE", "dpe_image"),
        ("ODPS_PROJECT", "odps_project"),
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


def get_dw_arg(name: str, default: str | None = None) -> str | None:
    value = _all_dw_arg_sources().get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def require_dw_arg(name: str) -> str:
    value = get_dw_arg(name)
    if not value:
        resolved = _all_dw_arg_sources()
        hint = (
            f"Missing required parameter: {name}. "
            f"Configure DataWorks node/workflow parameters (参数名={name}). "
            f"Resolved keys: {sorted(resolved.keys())}"
        )
        raise ValueError(hint)
    return value


def get_dw_int_arg(name: str, default: int) -> int:
    value = get_dw_arg(name)
    return default if value is None else int(value)


def get_dw_float_arg(name: str, default: float) -> float:
    value = get_dw_arg(name)
    return default if value is None else float(value)


def _account_security_token(account: Any) -> str:
    for attr in ("sts_token", "security_token", "token"):
        value = getattr(account, attr, None)
        if value:
            return str(value)
    return ""


def _odps_credential_fields(
    account: Any | None,
    odps_entry: Any | None = None,
) -> dict[str, str]:
    """Collect ODPS AK/SK/STS from DataWorks ``o`` / ``o.account`` for DPE env."""
    fields: dict[str, str] = {}
    for candidate in (account, getattr(odps_entry, "account", None) if odps_entry else None):
        if candidate is None:
            continue
        fields.setdefault("ODPS_ACCESS_ID", str(getattr(candidate, "access_id", "") or ""))
        fields.setdefault(
            "ODPS_ACCESS_KEY",
            str(
                getattr(candidate, "secret_access_key", "")
                or getattr(candidate, "access_key_secret", "")
                or ""
            ),
        )
        fields.setdefault("ODPS_PROJECT", str(getattr(candidate, "project", "") or ""))
        fields.setdefault("ODPS_ENDPOINT", str(getattr(candidate, "endpoint", "") or ""))
        token = _account_security_token(candidate)
        if token:
            fields["ODPS_STS_TOKEN"] = token
    for env_name, arg_name in (
        ("ODPS_ACCESS_ID", "odps_access_id"),
        ("ODPS_ACCESS_KEY", "odps_access_key"),
        ("ODPS_PROJECT", "odps_project"),
        ("ODPS_ENDPOINT", "odps_endpoint"),
        ("ODPS_STS_TOKEN", "odps_sts_token"),
    ):
        if fields.get(env_name, "").strip():
            continue
        try:
            value = get_dw_arg(arg_name)
        except NameError:
            value = None
        if value is not None and str(value).strip():
            fields[env_name] = str(value).strip()
    return fields


def derive_odps_catalog_endpoint(
    *,
    cloud_region: str = "cn_shanghai",
    odps_endpoint: str | None = None,
    explicit: str | None = None,
    catalog_host: str | None = None,
) -> str:
    """Catalog base URL for DPE nested ``read_odps_model``.

    Prefer ``catalog_host`` from ``o.get_catalog_host()`` on Driver; else derive
    from ODPS service endpoint (strip ``/api``), e.g. DataWorks
    ``service.cn-shanghai.maxcompute.apsara-inc.com``.
    """
    if explicit and str(explicit).strip():
        url = str(explicit).strip()
    elif catalog_host and str(catalog_host).strip():
        host = str(catalog_host).strip()
        url = host if host.startswith(("http://", "https://")) else f"http://{host}"
    else:
        endpoint = (odps_endpoint or "").strip().rstrip("/")
        if endpoint.endswith("/api"):
            endpoint = endpoint[:-4]
        if endpoint:
            url = endpoint
        else:
            region_id = (cloud_region or "cn_shanghai").replace("_", "-")
            url = f"http://service.{region_id}.maxcompute.apsara-inc.com"
    if not url.startswith(("http://", "https://")):
        url = f"http://{url.lstrip('/')}"
    return url.rstrip("/")


def resolve_catalog_endpoint_for_dpe(
    odps_entry: Any | None,
    *,
    cloud_region: str,
    account: Any | None = None,
    explicit: str | None = None,
) -> str:
    catalog_host: str | None = None
    odps_endpoint = ""
    for candidate in (odps_entry, account):
        if candidate is None:
            continue
        if not catalog_host:
            getter = getattr(candidate, "get_catalog_host", None)
            if callable(getter):
                try:
                    catalog_host = str(getter() or "").strip() or None
                except Exception:
                    catalog_host = None
        if not odps_endpoint:
            odps_endpoint = str(getattr(candidate, "endpoint", "") or "").strip()
    return derive_odps_catalog_endpoint(
        cloud_region=cloud_region,
        odps_endpoint=odps_endpoint or None,
        explicit=explicit,
        catalog_host=catalog_host,
    )


def _parse_version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in re.split(r"[.+]", str(version or "0").split("-", 1)[0]):
        if piece.isdigit():
            parts.append(int(piece))
    return tuple(parts or (0,))


def ensure_dpe_maxframe_for_mc_ai(min_version: str = "2.8.0") -> str:
    """Upgrade MaxFrame on DPE workers before nested ``read_odps_model`` (MLLM/ASR).

    Driver custom-script pip only affects the Driver pod; DPE workers keep the platform
    MaxFrame unless we install here. qwen3-asr-flash (format MLLM) needs MaxFrame 2.8+.
    """
    import importlib
    import subprocess
    import sys

    target = _parse_version_tuple(min_version)
    current = "0"
    try:
        import maxframe

        current = str(getattr(maxframe, "__version__", "0"))
        if _parse_version_tuple(current) >= target:
            print(f"DPE_MAXFRAME_VERSION={current}")
            return current
    except ImportError:
        pass

    mirror = "http://mirrors.cloud.aliyuncs.com/pypi/simple/"
    print(f"DPE_MAXFRAME_UPGRADE from={current} target>={min_version}")
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-q",
            f"maxframe>={min_version}",
            "-i",
            mirror,
            "--trusted-host",
            "mirrors.cloud.aliyuncs.com",
        ]
    )
    for name in list(sys.modules):
        if name == "maxframe" or name.startswith("maxframe."):
            del sys.modules[name]
    maxframe = importlib.import_module("maxframe")
    new_version = str(getattr(maxframe, "__version__", "?"))
    print(f"DPE_MAXFRAME_VERSION={new_version}")
    return new_version


def _ensure_odps_llm_registry() -> int:
    """Force-register ODPSLLM so ``read_odps_model`` can build MLLM/ASR models."""
    import maxframe.learn.contrib.llm.models.odps  # noqa: F401
    from maxframe.learn.utils.odpsio import _odps_model_classes

    count = len(_odps_model_classes)
    print(f"DPE_ODPS_MODEL_REGISTRY={count}")
    return count


def _patch_odps_llm_mllm_dispatch() -> None:
    """qwen3-asr-flash is MLLM with tasks ``image-text-to-text`` + ``auto-speech-recognition``.

    When Catalog returns empty/unknown tasks inside DPE, MaxFrame's
    ``ODPSLLM._determine_model_class`` returns None and ``read_odps_model`` raises the
    misleading \"format MLLM is not supported\" error even though MLLM is listed.
    """
    from maxframe.learn.contrib.llm.core import (
        TASK_IMAGE_TEXT_TO_TEXT,
        TASK_MULTI_MODAL_EMBEDDING,
    )
    from maxframe.learn.contrib.llm.models.managed import (
        ManagedMultiModalEmbeddingModel,
        ManagedMultiModalGenLLM,
    )
    from maxframe.learn.contrib.llm.models.odps import ODPSLLM, ODPSModelType

    if getattr(ODPSLLM._determine_model_class, "_rosbag_mllm_patched", False):
        return

    _orig = ODPSLLM._determine_model_class.__func__  # type: ignore[attr-defined]

    @classmethod  # type: ignore[misc]
    def _determine_model_class_patched(cls, tasks, model_type):  # noqa: ANN001
        result = _orig(cls, tasks, model_type)
        if result is not None:
            return result
        if model_type != ODPSModelType.MLLM:
            return None
        task_list = [str(t) for t in (tasks or [])]
        joined = " ".join(task_list).lower()
        if TASK_MULTI_MODAL_EMBEDDING in task_list or "embedding" in joined:
            print(f"DPE_MLLM_DISPATCH embedding tasks={task_list}")
            return ManagedMultiModalEmbeddingModel
        # ASR / empty tasks / unknown multimodal generation → GenLLM
        print(
            "DPE_MLLM_DISPATCH gen "
            f"tasks={task_list or ['(empty)']} "
            f"fallback={ManagedMultiModalGenLLM.__name__}"
        )
        return ManagedMultiModalGenLLM

    _determine_model_class_patched._rosbag_mllm_patched = True  # type: ignore[attr-defined]
    ODPSLLM._determine_model_class = _determine_model_class_patched  # type: ignore[method-assign]
    # Keep image-text-to-text as a known good path in logs when Catalog is healthy.
    _ = TASK_IMAGE_TEXT_TO_TEXT


def patch_mc_catalog_runtime_for_dpe() -> None:
    """Ensure nested MC AI uses internal Catalog API (works with SDK wheel <0.3.3)."""
    import os

    ensure_dpe_maxframe_for_mc_ai()
    try:
        _ensure_odps_llm_registry()
        _patch_odps_llm_mllm_dispatch()
    except Exception as exc:  # noqa: BLE001
        print(f"DPE_ODPS_LLM_PATCH_WARN={type(exc).__name__}: {exc}")

    region = (
        os.environ.get("MC_CLOUD_REGION")
        or os.environ.get("CLOUD_REGION")
        or "cn_shanghai"
    ).replace("_", "-")
    catalog = os.environ.get("ODPS_CATALOG_ENDPOINT", "").strip()
    if not catalog:
        catalog = derive_odps_catalog_endpoint(
            cloud_region=region,
            odps_endpoint=os.environ.get("ODPS_ENDPOINT", "").strip() or None,
        )
        os.environ["ODPS_CATALOG_ENDPOINT"] = catalog
    os.environ.setdefault("MC_USE_INTERNAL_CATALOG", "true")

    try:
        import oms_multimodal.mc.runtime as mc_runtime
    except ImportError:
        return

    def _configure_nested_mc_ai_for_dpe() -> None:
        """DPE UDF 内嵌套 MaxFrame AI session（与 Job2 Driver 侧 AI 对齐）。

        关键：勿把外层 ``apply_chunk`` 的 ``rosbag_sdk_dpe`` image 带进 AI session；
        ManagedLLM* 算子需要可调度的 MCSQL/平台引擎，自定义解析镜像常导致
        ``Operator type ... can't be accepted by any engine``。
        """
        try:
            from maxframe.config import options as mf_options
        except ImportError:
            return
        mf_options.local_execution.enabled = False
        # MCSQL first：AI Function 主路径；DPE 仅作备选
        mf_options.dag.settings = {
            "engine_order": ["MCSQL", "DPE"],
            "unavailable_engines": ["SPE"],
        }
        sql_settings = dict(mf_options.sql.settings or {})
        sql_settings["odps.sql.python.version"] = "cp311"
        sql_settings["odps.sql.using.public.model"] = "true"
        # Nested AI session image: default = platform (unset). Override with MC_AI_SESSION_IMAGE.
        ai_image = os.environ.get("MC_AI_SESSION_IMAGE", "").strip()
        if ai_image:
            sql_settings["odps.session.image"] = ai_image
        else:
            sql_settings.pop("odps.session.image", None)
        mf_options.sql.settings = sql_settings
        inference_quota = (
            os.environ.get("MC_INFERENCE_QUOTA_NAME", "").strip()
            or os.environ.get("AI_INFERENCE_QUOTA_NAME", "").strip()
            or os.environ.get("INFERENCE_QUOTA_NAME", "").strip()
        )
        if inference_quota:
            mf_options.session.inference_quota_name = inference_quota
        print(
            "DPE_MC_AI_CONFIG "
            f"engine_order={mf_options.dag.settings.get('engine_order')} "
            f"unavailable={mf_options.dag.settings.get('unavailable_engines')} "
            f"session_image={sql_settings.get('odps.session.image') or '(platform-default)'} "
            f"inference_quota={inference_quota or '(unset)'} "
            f"local_execution={mf_options.local_execution.enabled}"
        )

    def _configure_mc_sql_for_public_modelset() -> None:
        _configure_nested_mc_ai_for_dpe()

    _configure_mc_sql_for_public_modelset()

    _orig_prepare = mc_runtime.prepare_mf_ai_runtime

    def _prepare_mf_ai_runtime_patched(**kwargs: Any) -> None:
        # SDK prepare 会再写入 dpe_image；嵌套配置必须在其后覆盖。
        _orig_prepare(**kwargs)
        _configure_nested_mc_ai_for_dpe()

    mc_runtime.prepare_mf_ai_runtime = _prepare_mf_ai_runtime_patched

    # Force a fresh nested MaxFrame session before generate/execute (Job2-style AI session).
    _McRuntime = mc_runtime.McRuntime
    _orig_ensure_session = _McRuntime.ensure_session
    _orig_prepare_for_model = _McRuntime.prepare_for_model

    def _ensure_session_patched(self: Any) -> Any:
        _configure_nested_mc_ai_for_dpe()
        if self._session is not None:
            return self._session
        from maxframe import new_session

        try:
            from maxframe.session import reset_default_session

            reset_default_session()
            print("DPE_NESTED_SESSION reset_default_session=ok")
        except Exception as reset_exc:  # noqa: BLE001
            print(f"DPE_NESTED_SESSION reset_warn={type(reset_exc).__name__}: {reset_exc}")
        self._session = new_session(self.odps_entry)
        try:
            logview = self._session.get_logview_address()
        except Exception:  # noqa: BLE001
            logview = ""
        print(f"DPE_NESTED_SESSION created logview={logview}")
        return self._session

    def _prepare_for_model_patched(self: Any, model_name: str) -> None:
        _orig_prepare_for_model(self, model_name)
        # ensure_session after options so execute() binds to nested AI session
        self.ensure_session()

    _McRuntime.ensure_session = _ensure_session_patched  # type: ignore[method-assign]
    _McRuntime.prepare_for_model = _prepare_for_model_patched  # type: ignore[method-assign]

    _orig_fetch_series = mc_runtime._fetch_series

    def _fetch_series_patched(result_df: Any, preferred: tuple[str, ...]) -> list[Any]:
        from maxframe.session import get_default_session

        session = None
        try:
            session = get_default_session()
        except Exception:  # noqa: BLE001
            session = None
        if session is not None:
            pdf = result_df.execute(session=session).fetch()
        else:
            pdf = result_df.execute().fetch()
        columns = list(pdf.columns)
        col = mc_runtime._output_column(columns, preferred)
        if col not in columns:
            raise ValueError(f"AI output column {col!r} not in {columns}")
        return pdf[col].tolist()

    mc_runtime._fetch_series = _fetch_series_patched
    # Clients bind `_fetch_series` at import time — refresh if already loaded.
    for mod_name in (
        "oms_multimodal.mc.asr_client",
        "oms_multimodal.mc.omni_client",
        "oms_multimodal.mc.embedding_client",
    ):
        try:
            mod = __import__(mod_name, fromlist=["_fetch_series"])
            if hasattr(mod, "_fetch_series"):
                mod._fetch_series = _fetch_series_patched
        except ImportError:
            pass

    _orig_create = mc_runtime.create_ai_model

    def _create_ai_model_patched(
        model_name: str,
        odps_entry: Any,
        *,
        modelset_project: str = mc_runtime.DEFAULT_MODELSET_PROJECT,
    ) -> Any:
        _configure_nested_mc_ai_for_dpe()
        try:
            _ensure_odps_llm_registry()
            _patch_odps_llm_mllm_dispatch()
        except Exception as exc:  # noqa: BLE001
            print(f"DPE_ODPS_LLM_PATCH_WARN={type(exc).__name__}: {exc}")
        try:
            # Prefetch Catalog metadata so failures include format/tasks in Driver logs.
            if odps_entry is not None and hasattr(odps_entry, "get_model"):
                try:
                    model_obj = odps_entry.get_model(model_name, modelset_project, None)
                    model_obj.reload()
                    fmt = getattr(getattr(model_obj, "type", None), "value", None) or getattr(
                        model_obj, "type", "?"
                    )
                    tasks = list(getattr(model_obj, "tasks", None) or [])
                    print(
                        f"DPE_MODEL_META name={model_name} format={fmt} tasks={tasks}"
                    )
                except Exception as meta_exc:  # noqa: BLE001
                    print(
                        f"DPE_MODEL_META_WARN name={model_name} "
                        f"{type(meta_exc).__name__}: {meta_exc}"
                    )
            return _orig_create(model_name, odps_entry, modelset_project=modelset_project)
        except Exception as exc:
            import maxframe

            raise RuntimeError(
                f"{type(exc).__name__}: {exc} | "
                f"maxframe={getattr(maxframe, '__version__', '?')} "
                f"model={model_name} project={modelset_project}"
            ) from exc

    mc_runtime.create_ai_model = _create_ai_model_patched

    def _ensure(odps_entry: Any) -> None:
        if odps_entry is None:
            return
        cat = os.environ.get("ODPS_CATALOG_ENDPOINT", "").strip() or derive_odps_catalog_endpoint(
            cloud_region=region,
            odps_endpoint=os.environ.get("ODPS_ENDPOINT", "").strip() or None,
        )
        odps_entry._catalog_endpoint = cat
        odps_entry._catalog_rest = None

    def _resolve(entry: Any | None = None) -> Any:
        if entry is not None:
            _ensure(entry)
            return entry
        access_id = os.environ.get("ODPS_ACCESS_ID", "").strip()
        secret = os.environ.get("ODPS_ACCESS_KEY", "").strip()
        project = os.environ.get("ODPS_PROJECT", "").strip()
        endpoint = os.environ.get("ODPS_ENDPOINT", "").strip()
        sts_token = os.environ.get("ODPS_STS_TOKEN", "").strip()
        if not all([access_id, secret, project, endpoint]):
            return mc_runtime.resolve_odps_entry(entry)
        from odps import ODPS

        catalog = (
            cat
            if (cat := os.environ.get("ODPS_CATALOG_ENDPOINT", "").strip())
            else derive_odps_catalog_endpoint(
                cloud_region=region,
                odps_endpoint=os.environ.get("ODPS_ENDPOINT", "").strip() or None,
            )
        )
        # pyodps rejects ODPS(..., sts_token=...); use StsAccount instead.
        if sts_token:
            from odps.accounts import StsAccount

            odps = ODPS(
                account=StsAccount(access_id, secret, sts_token),
                project=project,
                endpoint=endpoint,
                catalog_endpoint=catalog,
            )
        else:
            odps = ODPS(
                access_id,
                secret,
                project=project,
                endpoint=endpoint,
                catalog_endpoint=catalog,
            )
        _ensure(odps)
        return odps

    mc_runtime.ensure_odps_catalog_endpoint = _ensure
    mc_runtime.resolve_odps_entry = _resolve


def apply_dpe_runtime_settings(dpe_image: str | None) -> None:
    from maxframe.config import options as mf_options

    # extract+mc ASR inside one DPE chunk routinely exceeds the ~20min default
    # container/session wait; raise before new_session().
    alive_sec = int(get_dw_arg("session_max_alive_sec", "14400") or "14400")
    idle_sec = int(get_dw_arg("session_max_idle_sec", str(alive_sec)) or str(alive_sec))
    if alive_sec > 0:
        mf_options.session.max_alive_seconds = alive_sec
    if idle_sec > 0:
        mf_options.session.max_idle_seconds = min(idle_sec, alive_sec) if alive_sec > 0 else idle_sec

    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    # Long per-chunk UDF (parse bag + nested MaxFrame AI ASR).
    sql_settings["odps.function.timeout"] = str(
        int(get_dw_arg("odps_function_timeout_sec", "3600") or "3600")
    )
    sql_settings["odps.sql.executionengine.batch.rowcount"] = "1"
    sql_settings.setdefault("odps.sql.job.max.time.hours", "24")
    mf_options.sql.settings = sql_settings


def configure_dpe_engine() -> None:
    from maxframe.config import options as mf_options

    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    mf_options.local_execution.enabled = False


def oss_internal_url(region: str, bucket: str, prefix: str) -> str:
    """MaxFrame 2.8 mount path: oss://{endpoint}/{bucket}/{prefix}/"""
    region_id = region.replace("_", "-")
    bucket_name = (bucket or "").strip()
    if not bucket_name:
        raise ValueError("oss_bucket is required for OSS mount URL")
    normalized = (prefix or "").strip("/")
    base = f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket_name}"
    if not normalized:
        return f"{base}/"
    return f"{base}/{normalized}/"


def storage_options(
    role_arn: str | None,
    account: Any,
    *,
    oss_bucket: str | None = None,
) -> dict[str, str]:
    # MaxFrame ``with_fs_mount`` expects ``role_arn`` or ``access_key_id``/``access_key_secret``;
    # ossfs2 also reads ``oss_bucket`` from storage_options on DPE workers.
    opts: dict[str, str] = {}
    if oss_bucket and str(oss_bucket).strip():
        opts["oss_bucket"] = str(oss_bucket).strip()
    if role_arn:
        opts["role_arn"] = role_arn
        return opts
    opts["access_key_id"] = account.access_id
    opts["access_key_secret"] = account.secret_access_key
    return opts


def work_items_to_job_rows(work_items: list[dict[str, Any]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in work_items:
        bag_oss_key = str(item.get("bag_oss_key") or "").strip()
        run_relpath = str(item.get("run_relpath") or "").strip()
        clip_id = str(item.get("clip_id") or "").strip()
        run_id = str(item.get("run_id") or "").strip()
        if not clip_id or not run_id or not run_relpath:
            raise ValueError(f"invalid batch item: {item!r}")
        row = {
            "clip_id": clip_id,
            "run_id": run_id,
            "run_relpath": run_relpath,
        }
        if bag_oss_key:
            row["bag_oss_key"] = bag_oss_key
        rows.append(row)
    return rows


def make_batch_input_df(job_rows: list[dict[str, str]], dpe_parallel: int):
    import maxframe.dataframe as md

    if not job_rows:
        raise ValueError("job_rows empty")
    input_df = md.DataFrame(pd.DataFrame(job_rows))
    parallel = min(max(int(dpe_parallel or 1), 1), len(job_rows))
    if parallel > 1:
        input_df = input_df.mf.rebalance(num_partitions=parallel)
    return input_df, parallel


def _set_env_from_arg(env: dict[str, str], env_name: str, arg_name: str, *, default: str | None = None) -> None:
    if env_name in env and str(env[env_name]).strip():
        return
    try:
        value = get_dw_arg(arg_name, default)
    except NameError:
        value = default
    if value is not None and str(value).strip():
        env[env_name] = str(value).strip()


def collect_sdk_env_for_dpe(
    account: Any | None = None,
    odps_entry: Any | None = None,
) -> dict[str, str]:
    """Driver 收集工作流参数 → DPE UDF 内 os.environ（仅 oms_multimodal import）。"""
    backend_raw = (get_dw_arg("model_backend") or "mc").strip().lower()
    backend = "mc" if backend_raw == "mc" else "api"
    env: dict[str, str] = {"MODEL_BACKEND": backend}
    for env_name, arg_name in (
        ("OMNI_MODEL", "omni_model"),
        ("ASR_MODEL", "asr_model"),
        ("EMBEDDING_MODEL", "embedding_model"),
        ("EMBEDDING_DIMENSION", "embedding_dimension"),
        ("DASHSCOPE_API_KEY", "dashscope_api_key"),
        ("DASHSCOPE_WORKSPACE_ID", "dashscope_workspace_id"),
        ("DASHSCOPE_REGION", "dashscope_region"),
    ):
        _set_env_from_arg(env, env_name, arg_name)
    if backend == "mc":
        for env_name, arg_name, default in (
            ("MC_MODELSET_PROJECT", "mc_modelset_project", "bigdata_public_modelset"),
            ("MC_OMNI_FALLBACK_MODEL", "mc_omni_fallback_model", None),
            ("MC_CLOUD_REGION", "cloud_region", "cn_shanghai"),
            ("MC_OSS_BUCKET", "oss_bucket", None),
            ("OSS_BUCKET", "oss_bucket", None),
            ("MC_DPE_IMAGE", "dpe_image", None),
            ("DPE_IMAGE", "dpe_image", None),
            ("MC_AI_CU_QUOTA_NAME", "ai_cu_quota_name", None),
            ("AI_CU_QUOTA_NAME", "ai_cu_quota_name", None),
            ("MC_AI_GU_QUOTA_NAME", "ai_gu_quota_name", None),
            ("AI_GU_QUOTA_NAME", "ai_gu_quota_name", None),
            ("MC_INFERENCE_QUOTA_NAME", "inference_quota_name", None),
            ("AI_INFERENCE_QUOTA_NAME", "inference_quota_name", None),
            ("INFERENCE_QUOTA_NAME", "inference_quota_name", None),
            ("MC_TOTAL_RPM_LIMIT", "total_rpm_limit", None),
            ("MC_REQUEST_TIMEOUT_SEC", "request_timeout", None),
            ("MC_AI_MEMORY", "ai_memory", None),
            ("MC_IMAGE_MODE", "mc_image_mode", None),
            ("OSS_VL_ACCESS_KEY_ID", "oss_vl_access_key_id", None),
            ("OSS_VL_ACCESS_KEY_SECRET", "oss_vl_access_key_secret", None),
            ("MC_OSS_ACCESS_KEY_ID", "oss_vl_access_key_id", None),
            ("MC_OSS_ACCESS_KEY_SECRET", "oss_vl_access_key_secret", None),
        ):
            _set_env_from_arg(env, env_name, arg_name, default=default)
        for key, value in _odps_credential_fields(account, odps_entry).items():
            if value:
                env.setdefault(key, value)
        env["ODPS_CATALOG_ENDPOINT"] = resolve_catalog_endpoint_for_dpe(
            odps_entry,
            cloud_region=get_dw_arg("cloud_region", "cn_shanghai") or "cn_shanghai",
            account=account,
            explicit=get_dw_arg("odps_catalog_endpoint"),
        )
        env.setdefault("MC_USE_INTERNAL_CATALOG", "true")
    return env


def wrap_dpe_udf(
    row_fn: Callable,
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    from maxframe.udf import with_fs_mount, with_running_options

    wrapped = with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)(row_fn)
    return with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options_dict)(wrapped)


def run_dpe_batch_apply(
    odps_entry: Any,
    input_df: Any,
    udf: Callable,
    output_dtypes: dict[str, str],
) -> pd.DataFrame:
    from maxframe.session import new_session

    session = new_session(odps_entry)
    try:
        print(f"Logview: {session.get_logview_address()}")
        result_df = input_df.apply(
            udf,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes=output_dtypes,
            skip_infer=True,
        )
        result = result_df.execute().fetch()
        if result.empty:
            raise RuntimeError("DPE batch apply returned no rows")
        return result
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


def print_batch_summary(capability: str, result: pd.DataFrame, *, parallel: int) -> None:
    summaries = []
    for _, row in result.iterrows():
        item = row.to_dict()
        summaries.append(item)
        print(
            f"BATCH_DONE clip_id={item.get('clip_id')} run_id={item.get('run_id')} "
            f"capability={capability}"
        )
    print(
        json.dumps(
            {
                "ok": True,
                "capability": capability,
                "batch_size": len(summaries),
                "parallel": parallel,
                "items": summaries,
            },
            ensure_ascii=False,
            default=str,
        )
    )
    print(f"NEXT_NODE_PARAM batch_size={len(summaries)}")
