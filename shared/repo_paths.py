"""Monorepo path constants — single source for pipeline, HMI, SDK, and shared config."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SHARED_ROOT = REPO_ROOT / "shared"
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_ROOT = REPO_ROOT / "hmi"
SDK_ROOT = REPO_ROOT / "piplinesdk"

CONFIG_PATH = SHARED_ROOT / "config.yaml"
TAXONOMY_PATH = SHARED_ROOT / "config" / "oms_label_taxonomy.yaml"
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
