"""DataWorks PyODPS3 参数读取（工作流参数 + 节点参数）。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

# 与 workflow-params.example / config.yaml 一致，节点未配参时的兜底（非密钥）
_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_sdk__",
    "scan_prefix": "rosbags/",
    "clip_id_format": "sha256:{hex}",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_runs_subdir": "runs/{run_id}/",
}


def _parse_skynet_args(raw: str) -> dict[str, str]:
    """解析 DataWorks 注入的 SKYNET_ARGS（key=value 或 JSON）。"""
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
        hint = (
            f"Missing required parameter: {name}. "
            f"Configure it in DataWorks node/workflow parameters "
            f"(参数名={name}). Resolved keys: {sorted(resolved.keys()) or '(empty)'}"
        )
        raise ValueError(hint)
    return value


def get_int_arg(name: str, default: int) -> int:
    value = get_arg(name)
    if value is None:
        return default
    return int(value)


def load_json_arg(name: str, default: dict[str, Any]) -> dict[str, Any]:
    raw = get_arg(name)
    if not raw:
        return default
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        raise ValueError(f"Parameter {name} must be a JSON object")
    return loaded
