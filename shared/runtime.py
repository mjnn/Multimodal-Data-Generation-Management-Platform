"""Import path setup for CLI scripts and legacy entrypoints."""

from __future__ import annotations

from pathlib import Path

from shared.repo_paths import (
    CONFIG_PATH,
    ENV_PATH,
    HMI_BACKEND_ROOT,
    HMI_ROOT,
    PIPELINE_ROOT,
    REPO_ROOT,
    ensure_import_paths,
)


def repo_root_from(caller_file: str | Path, levels_up: int = 2) -> Path:
    return Path(caller_file).resolve().parents[levels_up]


def bootstrap_hmi_cli(caller_file: str | Path) -> tuple[Path, Path, Path]:
    """For files under ``hmi/scripts/*.py`` (``levels_up=2`` → repo root)."""
    repo = repo_root_from(caller_file, 2)
    ensure_import_paths()
    return repo, repo / "hmi", HMI_BACKEND_ROOT


def bootstrap_pipeline_cli(caller_file: str | Path) -> tuple[Path, Path]:
    """For files under ``pipeline/scripts/*.py``."""
    repo = repo_root_from(caller_file, 2)
    ensure_import_paths()
    return repo, PIPELINE_ROOT


__all__ = [
    "CONFIG_PATH",
    "ENV_PATH",
    "bootstrap_hmi_cli",
    "bootstrap_pipeline_cli",
    "ensure_import_paths",
    "HMI_BACKEND_ROOT",
    "HMI_ROOT",
    "PIPELINE_ROOT",
    "REPO_ROOT",
    "repo_root_from",
]
