"""Read/write project environment variables for admin UI."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from hmi.data_source import LOCAL_ROOT
from repo_paths import ENV_PATH, REPO_ROOT

_ENV_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MASK_SENTINEL = "__UNCHANGED__"

_SENSITIVE_SUBSTRINGS = (
    "SECRET",
    "PASSWORD",
    "PASS",
    "ACCESS_KEY",
    "PRIVATE",
    "TOKEN",
    "API_KEY",
    "CREDENTIAL",
)

_EXTRA_CATALOG_KEYS = (
    "SERVICE_NAME",
    "IMAGE",
    "HOST_PORT",
    "CONTAINER_PORT",
    "HMI_PUBLIC_API_BASE",
    "HMI_LOCAL_SDK_POLL_ENABLED",
    "HMI_LOCAL_SDK_POLL_INTERVAL_SEC",
    "HMI_MIRROR_ARTIFACTS_TO_OSS",
    "HMI_OSS_SYNC_POLL_ENABLED",
    "HMI_OSS_SYNC_POLL_INTERVAL_SEC",
    "HMI_OSS_SYNC_AUTO_LOCAL",
    "HMI_OSS_SYNC_TIMEOUT_SEC",
    "CORS_ORIGINS",
    "DASHSCOPE_API_KEY",
    "DASHSCOPE_WORKSPACE_ID",
    "DASHSCOPE_REGION",
    "STORAGE_BACKEND",
    "FRONTEND_DIST",
    "PORT",
    "HMI_PIPELINE_OMNI_MODELS",
    "HMI_PIPELINE_EMBEDDING_MODELS",
    "HMI_SYSTEM_ENV_FILE",
    "HMI_DEPLOY_ENV_FILE",
)


def is_sensitive_key(key: str) -> bool:
    upper = key.upper()
    return any(part in upper for part in _SENSITIVE_SUBSTRINGS)


def _catalog_paths() -> list[Path]:
    paths = [
        REPO_ROOT / ".env.example",
        REPO_ROOT / "hmi" / "deploy" / ".env.runtime.example",
    ]
    return [p for p in paths if p.is_file()]


def catalog_keys() -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for path in _catalog_paths():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" not in stripped:
                continue
            key = stripped.split("=", 1)[0].strip()
            if _ENV_KEY.match(key) and key not in seen:
                seen.add(key)
                keys.append(key)
    for key in _EXTRA_CATALOG_KEYS:
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def resolve_system_env_path() -> Path:
    explicit = os.getenv("HMI_SYSTEM_ENV_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    deploy = os.getenv("HMI_DEPLOY_ENV_FILE", "").strip()
    if deploy:
        return Path(deploy).expanduser().resolve()
    if ENV_PATH.is_file():
        return ENV_PATH.resolve()
    try:
        if ENV_PATH.parent.is_dir() and os.access(ENV_PATH.parent, os.W_OK):
            return ENV_PATH.resolve()
    except OSError:
        pass
    return (LOCAL_ROOT / "config" / "project.env").resolve()


def _file_values(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    raw = dotenv_values(path)
    return {str(k): str(v) if v is not None else "" for k, v in raw.items()}


def _merged_values(path: Path) -> dict[str, str]:
    file_vals = _file_values(path)
    out: dict[str, str] = {}
    for key in catalog_keys():
        if key in file_vals:
            out[key] = file_vals[key]
        elif key in os.environ:
            out[key] = os.environ[key]
        else:
            out[key] = ""
    for key, val in file_vals.items():
        if key not in out:
            out[key] = val
    for key, val in os.environ.items():
        if _ENV_KEY.match(key) and key not in out and _is_project_env_key(key):
            out[key] = val
    return out


def _is_project_env_key(key: str) -> bool:
    upper = key.upper()
    prefixes = (
        "HMI_",
        "ODPS_",
        "OSS_",
        "CLOUD_",
        "DPE_",
        "DASHSCOPE_",
        "ACR_",
        "ALIYUN_",
        "STORAGE_",
        "CORS_",
        "SERVICE_",
        "HOST_",
        "CONTAINER_",
        "IMAGE",
        "PORT",
        "FRONTEND_",
    )
    return any(upper.startswith(p) or key == p.rstrip("_") for p in prefixes)


def get_system_env_snapshot(*, reveal_secrets: bool = True) -> dict[str, Any]:
    path = resolve_system_env_path()
    merged = _merged_values(path)
    catalog = catalog_keys()
    ordered: list[str] = []
    seen: set[str] = set()
    for key in catalog:
        if key in merged:
            ordered.append(key)
            seen.add(key)
    for key in sorted(merged.keys()):
        if key not in seen:
            ordered.append(key)
    variables: list[dict[str, Any]] = []
    for key in ordered:
        val = merged[key]
        sensitive = is_sensitive_key(key)
        display = val
        if sensitive and not reveal_secrets and val:
            display = _MASK_SENTINEL
        variables.append(
            {
                "key": key,
                "value": display,
                "sensitive": sensitive,
                "in_catalog": key in catalog,
            }
        )
    writable = _path_writable(path)
    return {
        "path": str(path),
        "writable": writable,
        "catalog_keys": catalog_keys(),
        "variables": variables,
        "restart_required_hint": "保存后已写入文件并刷新当前进程环境；Docker/compose 注入项可能仍需重启容器。",
    }


def _path_writable(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            return os.access(path, os.W_OK)
        probe = path.parent / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _escape_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(c in value for c in " #\"'\n\r\t"):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def save_system_env(updates: dict[str, str | None]) -> dict[str, Any]:
    path = resolve_system_env_path()
    if not _path_writable(path):
        raise ValueError(f"env file not writable: {path}")

    current = _merged_values(path)
    catalog = catalog_keys()
    order: list[str] = []
    seen: set[str] = set()
    for key in catalog:
        if key not in seen:
            order.append(key)
            seen.add(key)
    for key in sorted(current.keys()):
        if key not in seen:
            order.append(key)
            seen.add(key)
    for key in updates:
        if key not in seen and _ENV_KEY.match(key):
            order.append(key)
            seen.add(key)

    merged = dict(current)
    for key, val in updates.items():
        if not _ENV_KEY.match(key):
            continue
        if val == _MASK_SENTINEL:
            continue
        if val is None or val == "":
            merged.pop(key, None)
        else:
            merged[key] = str(val)

    lines = [
        "# Managed via HMI 系统参数管理",
        f"# Path: {path}",
        "",
    ]
    for key in order:
        if key not in merged:
            continue
        lines.append(f"{key}={_escape_env_value(merged[key])}")
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")

    from dotenv import load_dotenv

    load_dotenv(path, override=True)
    for key in order:
        if key in merged:
            os.environ[key] = merged[key]
        elif key in os.environ:
            os.environ.pop(key, None)

    from hmi.config import get_settings

    get_settings.cache_clear()

    return get_system_env_snapshot(reveal_secrets=True)
