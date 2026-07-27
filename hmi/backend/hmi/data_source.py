"""HMI data source: cloud (MaxCompute+OSS) or local (SQLite+files)."""

from __future__ import annotations

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HMI_ROOT = REPO_ROOT / "hmi"
PROJECT_ROOT = HMI_ROOT
LOCAL_ROOT = HMI_ROOT / "data" / "hmi_local"
LOCAL_DB_PATH = LOCAL_ROOT / "hmi.db"
LOCAL_ARTIFACTS_ROOT = LOCAL_ROOT / "artifacts"
LOCAL_CONFIG_PATH = LOCAL_ROOT / "config.json"

VALID_SOURCES = ("cloud", "local")

_runtime_source: str | None = None


def _read_config_file() -> dict:
    if not LOCAL_CONFIG_PATH.is_file():
        return {}
    try:
        with LOCAL_CONFIG_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def get_data_source() -> str:
    global _runtime_source
    if _runtime_source in VALID_SOURCES:
        return _runtime_source
    file_mode = str(_read_config_file().get("data_source") or "").strip().lower()
    if file_mode in VALID_SOURCES:
        return file_mode
    env_mode = os.getenv("HMI_DATA_SOURCE", "local").strip().lower()
    return env_mode if env_mode in VALID_SOURCES else "local"


def ensure_local_data_source() -> str:
    """HMI 暂不提供云端 MC 浏览；启动时把遗留的 cloud 配置迁回 local。"""
    if get_data_source() == "cloud":
        return set_data_source("local")
    return get_data_source()


def set_data_source(mode: str) -> str:
    global _runtime_source
    mode = mode.strip().lower()
    if mode not in VALID_SOURCES:
        raise ValueError(f"data_source must be one of {VALID_SOURCES}")
    _runtime_source = mode
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    payload = _read_config_file()
    payload["data_source"] = mode
    # Drop legacy demo profile key if present
    payload.pop("local_profile", None)
    with LOCAL_CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    return mode


def is_local_mode() -> bool:
    return get_data_source() == "local"


def is_cloud_mode() -> bool:
    return get_data_source() == "cloud"


def local_db_exists() -> bool:
    return LOCAL_DB_PATH.is_file()


def safe_clip_dir(clip_id: str) -> str:
    """Filesystem-safe clip folder (Windows disallows ':' in paths)."""
    return clip_id.replace(":", "__")


def artifacts_dir(clip_id: str, run_id: str) -> Path:
    return LOCAL_ARTIFACTS_ROOT / "clips" / safe_clip_dir(clip_id) / "runs" / run_id


def artifact_path(clip_id: str, run_id: str, rel_path: str) -> Path:
    return artifacts_dir(clip_id, run_id) / rel_path.lstrip("/").replace("\\", "/")
