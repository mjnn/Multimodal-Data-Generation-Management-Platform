"""Resolve cloud settings from config.yaml with .env overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_DEFAULT_ODPS_ENDPOINTS: dict[str, str] = {
    "cn_hangzhou": "https://service.cn-hangzhou.maxcompute.aliyun.com/api",
    "cn_shanghai": "https://service.cn-shanghai.maxcompute.aliyun.com/api",
    "cn_beijing": "https://service.cn-beijing.maxcompute.aliyun.com/api",
    "cn_shenzhen": "https://service.cn-shenzhen.maxcompute.aliyun.com/api",
}

_DEFAULT_OSS_ENDPOINTS: dict[str, str] = {
    "cn_hangzhou": "https://oss-cn-hangzhou.aliyuncs.com",
    "cn_shanghai": "https://oss-cn-shanghai.aliyuncs.com",
    "cn_beijing": "https://oss-cn-beijing.aliyuncs.com",
    "cn_shenzhen": "https://oss-cn-shenzhen.aliyuncs.com",
}


def _first_non_empty(*values: str | None) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def load_cloud_env(env_path: Path | None = None) -> None:
    if env_path is None:
        load_dotenv()
        return
    load_dotenv(env_path)


def resolve_cloud_settings(config: dict[str, Any]) -> dict[str, str]:
    cloud_config = config.get("cloud", {})
    oss_config = cloud_config.get("oss", {})
    mc_config = cloud_config.get("maxcompute", {})

    region = _first_non_empty(
        os.getenv("CLOUD_REGION"),
        str(oss_config.get("region", "")),
        str(mc_config.get("region", "")),
        "cn_shanghai",
    )

    job1_config = cloud_config.get("job1_parse", {})
    dpe_config = job1_config.get("dpe", {}) if isinstance(job1_config.get("dpe"), dict) else {}

    return {
        "region": region,
        "oss_bucket": _first_non_empty(os.getenv("OSS_BUCKET"), str(oss_config.get("bucket", ""))),
        "oss_endpoint": _first_non_empty(
            os.getenv("OSS_ENDPOINT"),
            str(oss_config.get("endpoint", "")),
            _DEFAULT_OSS_ENDPOINTS.get(region, ""),
        ),
        "oss_data_prefix": _first_non_empty(
            str(oss_config.get("data_prefix", "")),
            "rosbags/",
        ),
        "oss_prefix_template": _first_non_empty(
            str(oss_config.get("prefix_template", "")),
            "clips/{clip_id}/",
        ),
        "oss_raw_subdir": _first_non_empty(str(oss_config.get("raw_subdir", "")), "raw/"),
        "oss_runs_subdir": _first_non_empty(
            str(oss_config.get("runs_subdir", "")),
            "runs/{run_id}/",
        ),
        "odps_project": _first_non_empty(
            os.getenv("ODPS_PROJECT"),
            str(mc_config.get("project", "")),
        ),
        "odps_endpoint": _first_non_empty(
            os.getenv("ODPS_ENDPOINT"),
            str(mc_config.get("endpoint", "")),
            _DEFAULT_ODPS_ENDPOINTS.get(region, ""),
        ),
        "odps_access_id": _first_non_empty(os.getenv("ODPS_ACCESS_ID")),
        "odps_access_key": _first_non_empty(os.getenv("ODPS_ACCESS_KEY")),
        "table_prefix": _first_non_empty(
            str(mc_config.get("table_prefix", "")),
            "aig_sdk__",
        ),
        "sdk_table_prefix": _first_non_empty(
            str(mc_config.get("sdk_table_prefix", "")),
            str(mc_config.get("table_prefix", "")),
            "aig_sdk__",
        ),
        "dpe_image": _first_non_empty(
            os.getenv("DPE_IMAGE"),
            str(dpe_config.get("image", "")),
        ),
        "oss_ram_role_arn": _first_non_empty(os.getenv("OSS_RAM_ROLE_ARN")),
        "dpe_cpu": _first_non_empty(str(dpe_config.get("cpu", "")), "4"),
        "dpe_memory_gb": _first_non_empty(str(dpe_config.get("memory_gb", "")), "16"),
        "dpe_mount_path": _first_non_empty(str(dpe_config.get("mount_path", "")), "/mnt/clip"),
    }


def oss_internal_url(region: str, bucket: str, object_prefix: str) -> str:
    prefix = object_prefix.lstrip("/")
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return f"oss://oss-{region}-internal.aliyuncs.com/{bucket}/{prefix}"


def format_clip_oss_prefix(settings: dict[str, str], clip_id: str) -> str:
    template = settings.get("oss_prefix_template", "clips/{clip_id}/")
    return template.format(clip_id=clip_id)


def require_job1_settings(settings: dict[str, str]) -> dict[str, str]:
    settings = require_odps_settings(settings)
    missing = [
        name
        for name in ("oss_bucket", "dpe_image", "oss_ram_role_arn")
        if not settings.get(name)
    ]
    if missing:
        raise ValueError(
            "Missing Job1 cloud settings: "
            + ", ".join(missing)
            + ". Set DPE_IMAGE and OSS_RAM_ROLE_ARN in .env."
        )
    return settings


def require_odps_settings(settings: dict[str, str]) -> dict[str, str]:
    missing = [
        name
        for name in ("odps_project", "odps_endpoint", "odps_access_id", "odps_access_key")
        if not settings.get(name)
    ]
    if missing:
        raise ValueError(
            "Missing cloud credentials/settings: "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill values."
        )
    return settings
