# =============================================================================
# SDK DPE 节点共享：Driver 批量编排 + DPE UDF 装饰器
# =============================================================================

from __future__ import annotations

import json
import os
from typing import Any, Callable

import pandas as pd


def get_dw_arg(name: str, default: str | None = None) -> str | None:
    try:
        value = args.get(name)  # type: ignore[name-defined]
    except NameError:
        value = None
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def require_dw_arg(name: str) -> str:
    value = get_dw_arg(name)
    if not value:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def get_dw_int_arg(name: str, default: int) -> int:
    value = get_dw_arg(name)
    return default if value is None else int(value)


def get_dw_float_arg(name: str, default: float) -> float:
    value = get_dw_arg(name)
    return default if value is None else float(value)


def apply_dpe_runtime_settings(dpe_image: str | None) -> None:
    from maxframe.config import options as mf_options

    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings


def configure_dpe_engine() -> None:
    from maxframe.config import options as mf_options

    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    mf_options.local_execution.enabled = False


def oss_internal_url(region: str, bucket: str, prefix: str) -> str:
    host = f"oss-{region}-internal.aliyuncs.com"
    base = f"oss://{bucket}.{host}"
    if prefix:
        return f"{base}/{prefix.strip('/')}/"
    return f"{base}/"


def storage_options(role_arn: str | None, account: Any) -> dict[str, str]:
    if role_arn:
        return {"oss_role_arn": role_arn}
    return {
        "oss_access_key_id": account.access_id,
        "oss_access_key_secret": account.secret_access_key,
    }


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


def collect_sdk_env_for_dpe(account: Any | None = None) -> dict[str, str]:
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
        if account is not None:
            env.setdefault("ODPS_ACCESS_ID", str(getattr(account, "access_id", "") or ""))
            env.setdefault(
                "ODPS_ACCESS_KEY",
                str(getattr(account, "secret_access_key", "") or getattr(account, "access_key_secret", "") or ""),
            )
            env.setdefault("ODPS_PROJECT", str(getattr(account, "project", "") or ""))
            env.setdefault("ODPS_ENDPOINT", str(getattr(account, "endpoint", "") or ""))
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
