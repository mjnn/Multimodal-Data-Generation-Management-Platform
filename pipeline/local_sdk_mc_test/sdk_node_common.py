# =============================================================================
# 本地 SDK MC 联调：参数读取（模拟 DataWorks 工作流 / 节点参数）
#
# DataWorks 中：args["bag_local_path"] = "..."
# 本地联调：.env 写 BAG_LOCAL_PATH=...（或 bag_local_path=...）
# =============================================================================

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from oms_multimodal import ClientConfig, McBackendConfig, OmsMultimodalClient, bundled_taxonomy_path

HERE = Path(__file__).resolve().parent

MediaMode = Literal["local", "oss", "auto"]
ModelBackend = Literal["api", "mc"]


def load_local_env(*, override: bool = False) -> Path | None:
    """加载本目录 .env（工作流 + 节点参数）。返回加载的路径或 None。"""
    env_path = HERE / ".env"
    if not env_path.is_file():
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:
        # 无 python-dotenv 时手写解析
        for line in env_path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, value = text.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if override or key not in os.environ or not str(os.environ.get(key, "")).strip():
                os.environ[key] = value
        return env_path
    load_dotenv(env_path, override=override)
    return env_path


# 启动 import 时加载一次（单节点直接 python sdk_xxx_node.py 也生效）
_LOADED = load_local_env()


def get_arg(name: str, default: str | None = None) -> str | None:
    """模拟 DataWorks ``args.get(name)``：支持小写参数名与 UPPER_ENV。"""
    # 1) DataWorks 风格：若存在全局 args
    try:
        node_args = args  # type: ignore[name-defined]
        if isinstance(node_args, dict) and name in node_args and node_args[name] is not None:
            raw = str(node_args[name]).strip()
            if raw:
                return raw
    except NameError:
        pass
    # 2) 原样 / 大写 / 小写
    for key in (name, name.upper(), name.lower()):
        value = os.environ.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def require_arg(name: str) -> str:
    value = get_arg(name)
    if not value:
        raise ValueError(
            f"Missing required parameter: {name} "
            f"(set in .env as {name.upper()}=... or export {name.upper()})"
        )
    return value


def get_int_arg(name: str, default: int) -> int:
    value = get_arg(name)
    return default if value is None else int(value)


def get_float_arg(name: str, default: float) -> float:
    value = get_arg(name)
    return default if value is None else float(value)


def resolve_odps_entry() -> Any | None:
    try:
        return o  # type: ignore[name-defined]
    except NameError:
        return None


def resolve_backend() -> ModelBackend:
    raw = (get_arg("model_backend") or os.environ.get("MODEL_BACKEND") or "api").strip().lower()
    return "mc" if raw == "mc" else "api"


def resolve_media_mode(default: MediaMode = "local") -> MediaMode:
    raw = (get_arg("media_mode") or default).strip().lower()
    if raw in {"local", "oss", "auto"}:
        return raw  # type: ignore[return-value]
    return default


def set_env_from_arg(env_name: str, arg_name: str, *, default: str | None = None) -> None:
    if os.environ.get(env_name, "").strip():
        return
    value = get_arg(arg_name, default)
    if value is not None and str(value).strip():
        os.environ[env_name] = str(value).strip()


def apply_env_from_args(backend: ModelBackend) -> None:
    set_env_from_arg("MODEL_BACKEND", "model_backend", default=backend)
    set_env_from_arg("OMNI_MODEL", "omni_model")
    set_env_from_arg("ASR_MODEL", "asr_model")
    set_env_from_arg("EMBEDDING_MODEL", "embedding_model")
    set_env_from_arg("EMBEDDING_DIMENSION", "embedding_dimension")
    set_env_from_arg("DASHSCOPE_API_KEY", "dashscope_api_key")
    set_env_from_arg("DASHSCOPE_WORKSPACE_ID", "dashscope_workspace_id")
    set_env_from_arg("DASHSCOPE_REGION", "dashscope_region")
    if backend != "mc":
        return
    set_env_from_arg("MC_MODELSET_PROJECT", "mc_modelset_project", default="bigdata_public_modelset")
    set_env_from_arg("MC_OMNI_FALLBACK_MODEL", "mc_omni_fallback_model")
    set_env_from_arg("MC_CLOUD_REGION", "cloud_region", default="cn_shanghai")
    set_env_from_arg("MC_OSS_BUCKET", "oss_bucket")
    set_env_from_arg("OSS_BUCKET", "oss_bucket")
    set_env_from_arg("MC_DPE_IMAGE", "dpe_image")
    set_env_from_arg("DPE_IMAGE", "dpe_image")
    set_env_from_arg("MC_AI_CU_QUOTA_NAME", "ai_cu_quota_name")
    set_env_from_arg("AI_CU_QUOTA_NAME", "ai_cu_quota_name")
    set_env_from_arg("MC_AI_GU_QUOTA_NAME", "ai_gu_quota_name")
    set_env_from_arg("AI_GU_QUOTA_NAME", "ai_gu_quota_name")
    set_env_from_arg("MC_TOTAL_RPM_LIMIT", "total_rpm_limit")
    set_env_from_arg("MC_REQUEST_TIMEOUT_SEC", "request_timeout")
    set_env_from_arg("MC_AI_MEMORY", "ai_memory")
    set_env_from_arg("MC_IMAGE_MODE", "mc_image_mode")
    set_env_from_arg("OSS_VL_ACCESS_KEY_ID", "oss_vl_access_key_id")
    set_env_from_arg("OSS_VL_ACCESS_KEY_SECRET", "oss_vl_access_key_secret")
    set_env_from_arg("MC_OSS_ACCESS_KEY_ID", "oss_vl_access_key_id")
    set_env_from_arg("MC_OSS_ACCESS_KEY_SECRET", "oss_vl_access_key_secret")


def validate_mc_backend() -> None:
    if resolve_odps_entry() is None:
        required = ("ODPS_ACCESS_ID", "ODPS_ACCESS_KEY", "ODPS_PROJECT", "ODPS_ENDPOINT")
        if not all(os.environ.get(k, "").strip() for k in required):
            raise ValueError(
                "model_backend=mc requires DataWorks odps entry `o` or env " + str(required)
            )


def oss_run_prefix_for(clip_id: str, run_id: str) -> str:
    clip_prefix = get_arg("oss_prefix_template", "clips/{clip_id}/") or "clips/{clip_id}/"
    runs_subdir = get_arg("oss_runs_subdir", "runs/{run_id}/") or "runs/{run_id}/"
    return (
        clip_prefix.format(clip_id=clip_id).strip("/")
        + "/"
        + runs_subdir.format(run_id=run_id).strip("/")
        + "/"
    )


def build_sdk_client(
    *,
    backend: ModelBackend | None = None,
    require_taxonomy: bool = False,
    load_dotenv: bool = True,
    work_dir: Path | str | None = None,
) -> tuple[OmsMultimodalClient, ClientConfig, McBackendConfig | None]:
    if load_dotenv:
        load_local_env()
    backend = backend or resolve_backend()
    apply_env_from_args(backend)
    if backend == "mc":
        validate_mc_backend()
    odps_entry = resolve_odps_entry()
    taxonomy_raw = get_arg("taxonomy_path")
    tax_path = Path(taxonomy_raw) if taxonomy_raw else (bundled_taxonomy_path() if require_taxonomy else None)
    if require_taxonomy and tax_path is None:
        tax_path = bundled_taxonomy_path()
    mc_config = McBackendConfig.from_env(odps_entry=odps_entry) if backend == "mc" else None
    cfg = ClientConfig.from_env(taxonomy_path=tax_path)
    cfg.model_backend = backend
    cfg.mc_odps_entry = odps_entry
    cfg.mc_config = mc_config
    if tax_path is not None:
        cfg.taxonomy_path = tax_path
    client = OmsMultimodalClient(config=cfg, work_dir=work_dir, load_dotenv=False)
    return client, cfg, mc_config


def make_run_context(
    client: OmsMultimodalClient,
    run_out: Path,
    *,
    clip_id: str,
    run_id: str,
    media_mode: MediaMode | None = None,
) -> Any:
    mode = media_mode or resolve_media_mode("local")
    prefix = ""
    if mode in {"oss", "auto"}:
        prefix = oss_run_prefix_for(clip_id, run_id)
    return client.make_run_context(
        run_out,
        media_mode=mode,
        clip_id=clip_id,
        run_id=run_id,
        oss_run_prefix=prefix,
    )


def require_run_paths() -> tuple[Path, str, str]:
    run_out = Path(require_arg("run_out_dir"))
    clip_id = require_arg("clip_id")
    run_id = require_arg("run_id")
    run_out.mkdir(parents=True, exist_ok=True)
    return run_out, clip_id, run_id
