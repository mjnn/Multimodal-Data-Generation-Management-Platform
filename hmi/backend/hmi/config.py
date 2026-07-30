"""Load HMI settings from project config.yaml + .env."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
HMI_ROOT = REPO_ROOT / "hmi"
PROJECT_ROOT = HMI_ROOT  # legacy alias: HMI-local data & scripts

_shared = REPO_ROOT / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))

from repo_paths import CONFIG_PATH, ENV_PATH, TAXONOMY_PATH, ensure_import_paths

ensure_import_paths()

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings

SDK_PIPELINE_VERSION = "sdk_v1"

SDK_STEP_LABELS = {
    "sdk_discover": "Bag 登记",
    "sdk_infer": "SDK 打标与向量",
    "sdk_upload": "OSS 上传",
    "sdk_mc_write": "MC 写入",
    "sdk_dispatch": "调度发布",
}

# Cloud DataWorks: infer → upload OSS → MC facts → dispatch
SDK_PIPELINE_STEP_ORDER = (
    "sdk_discover",
    "sdk_infer",
    "sdk_upload",
    "sdk_mc_write",
    "sdk_dispatch",
)

# Local worker: infer → import SQLite + artifacts → mirror local oss/ → dispatch
SDK_PIPELINE_STEP_ORDER_LOCAL = (
    "sdk_discover",
    "sdk_infer",
    "sdk_mc_write",
    "sdk_upload",
    "sdk_dispatch",
)


def sdk_pipeline_step_order(*, local: bool = False) -> tuple[str, ...]:
    return SDK_PIPELINE_STEP_ORDER_LOCAL if local else SDK_PIPELINE_STEP_ORDER


STEP_LABELS = {
    "job0_discover": "OSS 发现",
    "job1_parse": "解析 Rosbag",
    "job1_align": "多模态对齐",
    "job2_labeling": "主模型打标",
    "job2_embedding": "Clip 向量化",
    "job3_labeling_by_other_model": "副模型打标",
    "job4_label_merge_and_compare": "多模型比对合并",
    # legacy
    "job2_clip_omni": "Clip Omni 打标+向量",
    "job2_sample": "帧图抽样",
    "job2_asr": "音频 ASR",
    "job3_label": "AI 打标",
    "job4_embed": "向量化",
    **SDK_STEP_LABELS,
}


def pipeline_step_label(step_id: str, *, local: bool = False) -> str:
    if local and step_id == "sdk_mc_write":
        return "SQLite 写入"
    return STEP_LABELS.get(step_id, step_id)


PIPELINE_VERSION = "clip_omni_v2"

PIPELINE_STEP_ORDER = (
    "job0_discover",
    "job1_parse",
    "job1_align",
    "job2_labeling",
    "job2_embedding",
    "job3_labeling_by_other_model",
    "job4_label_merge_and_compare",
)

LEGACY_PIPELINE_STEP_ORDER = (
    "job0_discover",
    "job1_parse",
    "job2_sample",
    "job2_asr",
    "job3_label",
    "job4_embed",
)


@lru_cache
def get_settings() -> dict[str, str]:
    load_cloud_env(ENV_PATH)
    try:
        from dotenv import load_dotenv

        from hmi.system_env import resolve_system_env_path

        extra = resolve_system_env_path()
        if extra.is_file() and extra.resolve() != ENV_PATH.resolve():
            load_dotenv(extra, override=True)
    except Exception:
        pass
    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    settings = require_odps_settings(resolve_cloud_settings(config))
    if not settings.get("oss_bucket"):
        raise ValueError("OSS_BUCKET is required for HMI backend.")
    settings["_project_root"] = str(HMI_ROOT)
    settings["_repo_root"] = str(REPO_ROOT)
    settings["_alignment_window_ms"] = str(
        config.get("cloud", {}).get("alignment", {}).get("default_window_ms", 200)
    )
    return settings


def table_name(settings: dict[str, str], suffix: str) -> str:
    prefix = settings.get("table_prefix") or "aig_sdk__"
    return f"{prefix}{suffix}"


def sdk_table_name(settings: dict[str, str], suffix: str) -> str:
    prefix = settings.get("sdk_table_prefix") or settings.get("table_prefix") or "aig_sdk__"
    return f"{prefix}{suffix}"
