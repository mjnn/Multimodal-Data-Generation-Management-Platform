"""HMI data source: cloud (MaxCompute+OSS) or local (SQLite + on-disk OSS mirror)."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_repo = Path(__file__).resolve().parents[3]
_shared = _repo / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from repo_paths import HMI_LOCAL_ROOT, HMI_RUNTIME_ROOT  # noqa: E402

REPO_ROOT = _repo
HMI_ROOT = REPO_ROOT / "hmi"
PROJECT_ROOT = HMI_ROOT

VALID_SOURCES = ("cloud", "local")

_runtime_source: str | None = None


def resolve_local_root() -> Path:
    """Local test runtime: SQLite + artifacts + oss/ tree (ECS disk counts as local)."""
    env = os.getenv("HMI_RUNTIME_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    if HMI_RUNTIME_ROOT.joinpath("hmi.db").is_file():
        return HMI_RUNTIME_ROOT.resolve()
    if HMI_LOCAL_ROOT.joinpath("hmi.db").is_file() and not HMI_RUNTIME_ROOT.joinpath(".initialized").is_file():
        return HMI_LOCAL_ROOT.resolve()
    return HMI_RUNTIME_ROOT.resolve()


LOCAL_ROOT = resolve_local_root()
LOCAL_DB_PATH = LOCAL_ROOT / "hmi.db"
LOCAL_ARTIFACTS_ROOT = LOCAL_ROOT / "artifacts"
LOCAL_OSS_ROOT = LOCAL_ROOT / "oss"
LOCAL_CONFIG_PATH = LOCAL_ROOT / "config.json"


def ensure_runtime_layout() -> Path:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    LOCAL_ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
    for sub in ("rosbags", "clips", "pipeline", "config", "reviews", "datasets"):
        (LOCAL_OSS_ROOT / sub).mkdir(parents=True, exist_ok=True)
    (LOCAL_ROOT / "work" / "sdk_runs").mkdir(parents=True, exist_ok=True)
    return LOCAL_ROOT


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


def set_data_source(mode: str) -> str:
    global _runtime_source
    mode = mode.strip().lower()
    if mode not in VALID_SOURCES:
        raise ValueError(f"data_source must be one of {VALID_SOURCES}")
    _runtime_source = mode
    ensure_runtime_layout()
    payload = _read_config_file()
    payload["data_source"] = mode
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


def oss_key_path(oss_key: str) -> Path:
    """Map OSS object key to file under LOCAL_OSS_ROOT (local mode simulation)."""
    key = oss_key.lstrip("/").replace("\\", "/")
    return LOCAL_OSS_ROOT / key
