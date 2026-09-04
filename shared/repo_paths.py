"""Monorepo 路径常量（管线 / HMI / SDK / 配置的单一来源）。

入口脚本应把 shared/ 加入 sys.path 后 `from repo_paths import CONFIG_PATH, ENV_PATH`。
HMI 运行时目录：HMI_RUNTIME_ROOT（默认 hmi/data/hmi_runtime）。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = REPO_ROOT / "shared"
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_ROOT = REPO_ROOT / "hmi"
SDK_ROOT = REPO_ROOT / "piplinesdk"

CONFIG_PATH = SHARED_ROOT / "config.yaml"
TAXONOMY_PATH = SHARED_ROOT / "config" / "oms_label_taxonomy.yaml"
AUDIO_NVH_TAXONOMY_PATH = SHARED_ROOT / "config" / "audio_nvh_taxonomy.yaml"
ENV_PATH = REPO_ROOT / ".env"

HMI_BACKEND_ROOT = HMI_ROOT / "backend"
HMI_DATA_ROOT = HMI_ROOT / "data"
HMI_LOCAL_ROOT = HMI_DATA_ROOT / "hmi_local"
HMI_RUNTIME_ROOT = HMI_DATA_ROOT / "hmi_runtime"
PIPELINE_DATA_ROOT = PIPELINE_ROOT / "data"
PIPELINE_SCRIPTS_ROOT = PIPELINE_ROOT / "scripts"
HMI_SCRIPTS_ROOT = HMI_ROOT / "scripts"


def ensure_import_paths() -> None:
    """Register shared, pipeline, and HMI backend on sys.path (idempotent)."""
    import sys

    for entry in (SHARED_ROOT, PIPELINE_ROOT, HMI_BACKEND_ROOT):
        text = str(entry)
        if text not in sys.path:
            sys.path.insert(0, text)
