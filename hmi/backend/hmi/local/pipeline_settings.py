"""Persisted SDK pipeline run parameters for local HMI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hmi.data_source import LOCAL_ROOT

_SETTINGS_PATH = LOCAL_ROOT / "config" / "pipeline_settings.json"

_DEFAULTS: dict[str, Any] = {
    "omni_model": "default",
    "embedding_model": "default",
    "taxonomy_version_id": None,
    "sample_fps": 1.0,
    "min_sec": 5.0,
    "max_sec": 30.0,
    "max_clips": 1,
    "sdk_parallel": 1,
    "omni_label_prompt": {},
}


def _sdk_prompt_helpers():
    from oms_multimodal.label_prompt import (
        OMNI_LABEL_PROMPT_FIELD_META,
        default_omni_label_prompt,
        merge_omni_label_prompt,
        omni_label_prompt_overrides_only,
    )

    return (
        OMNI_LABEL_PROMPT_FIELD_META,
        default_omni_label_prompt,
        merge_omni_label_prompt,
        omni_label_prompt_overrides_only,
    )


def get_omni_label_prompt_schema() -> list[dict[str, Any]]:
    meta, *_ = _sdk_prompt_helpers()
    return list(meta)


def get_merged_omni_label_prompt(overrides: dict[str, Any] | None) -> dict[str, str]:
    _, _, merge_fn, _ = _sdk_prompt_helpers()
    return merge_fn(overrides)


def _model_options(env_key: str, fallback: str) -> list[str]:
    raw = os.getenv(env_key, "").strip()
    opts = ["default"]
    if raw:
        for part in raw.split(","):
            p = part.strip()
            if p and p not in opts:
                opts.append(p)
    else:
        opts.append(fallback)
    return opts


def get_model_option_lists() -> dict[str, list[str]]:
    return {
        "omni_models": _model_options("HMI_PIPELINE_OMNI_MODELS", "qwen3.5-omni-plus"),
        "embedding_models": _model_options(
            "HMI_PIPELINE_EMBEDDING_MODELS", "qwen3-vl-embedding"
        ),
    }


def resolve_sdk_parallel(settings: dict[str, Any] | None = None) -> int:
    """Concurrent local SDK clip workers (1=sequential). Env overrides saved settings."""
    raw_env = os.getenv("HMI_LOCAL_SDK_PARALLEL", "").strip()
    if raw_env:
        try:
            return max(1, min(8, int(raw_env)))
        except ValueError:
            pass
    cfg = settings if settings is not None else get_pipeline_settings_for_save()
    try:
        return max(1, min(8, int(cfg.get("sdk_parallel", 1))))
    except (TypeError, ValueError):
        return 1


def resolve_pipeline_taxonomy_display(settings: dict[str, Any] | None = None) -> str:
    """Label for pipeline UI when taxonomy_version_id may be unset (follow published)."""
    from hmi.taxonomy_db import (
        get_published_version,
        resolve_taxonomy_display_for_version_id,
    )

    cfg = settings or get_pipeline_settings()
    tid = cfg.get("taxonomy_version_id")
    explicit = resolve_taxonomy_display_for_version_id(
        str(tid).strip() if tid else None
    )
    if explicit:
        return explicit
    published = get_published_version()
    if published:
        from hmi.taxonomy_db import taxonomy_version_display_label

        return f"默认（{taxonomy_version_display_label(published)}）"
    return "默认（仓库 taxonomy）"


def _sanitize_stored_taxonomy_version_id(out: dict[str, Any]) -> None:
    """Drop stale taxonomy_version_id after DB reset (avoid UUID in UI)."""
    from hmi.taxonomy_db import get_version

    tid = out.get("taxonomy_version_id")
    if not tid:
        return
    tid_s = str(tid).strip()
    if get_version(tid_s):
        return
    out["taxonomy_version_id"] = None
    try:
        raw = get_pipeline_settings_for_save()
        if str(raw.get("taxonomy_version_id") or "").strip() == tid_s:
            raw["taxonomy_version_id"] = None
            _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            _SETTINGS_PATH.write_text(
                json.dumps(raw, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
    except OSError:
        pass


def get_pipeline_settings() -> dict[str, Any]:
    out = dict(_DEFAULTS)
    stored_prompt: dict[str, Any] = {}
    if _SETTINGS_PATH.is_file():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in _DEFAULTS:
                    if k in data:
                        out[k] = data[k]
                raw_prompt = data.get("omni_label_prompt")
                if isinstance(raw_prompt, dict):
                    stored_prompt = raw_prompt
        except (json.JSONDecodeError, OSError):
            pass
    _sanitize_stored_taxonomy_version_id(out)
    out["omni_label_prompt"] = get_merged_omni_label_prompt(stored_prompt)
    out["taxonomy_version_label"] = resolve_pipeline_taxonomy_display(out)
    return out


def get_pipeline_settings_for_save() -> dict[str, Any]:
    """Raw persisted dict (overrides only for omni_label_prompt)."""
    out = dict(_DEFAULTS)
    if _SETTINGS_PATH.is_file():
        try:
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for k in _DEFAULTS:
                    if k in data:
                        out[k] = data[k]
        except (json.JSONDecodeError, OSError):
            pass
    return out


def save_pipeline_settings(updates: dict[str, Any]) -> dict[str, Any]:
    current = get_pipeline_settings_for_save()
    for key in _DEFAULTS:
        if key not in updates:
            continue
        val = updates[key]
        if key == "taxonomy_version_id":
            current[key] = str(val).strip() if val else None
        elif key in {"sample_fps", "min_sec", "max_sec"}:
            current[key] = float(val)
        elif key == "max_clips":
            current[key] = int(val) if val is not None else 1
        elif key == "sdk_parallel":
            current[key] = max(1, min(8, int(val if val is not None else 1)))
        elif key in {"omni_model", "embedding_model"}:
            current[key] = str(val or "default")
        elif key == "omni_label_prompt":
            if isinstance(val, dict):
                _, _, merge_fn, compact_fn = _sdk_prompt_helpers()
                merged = merge_fn(val)
                current[key] = compact_fn(merged)
            else:
                current[key] = {}
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(
        json.dumps(current, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return get_pipeline_settings()


def resolve_taxonomy_path(settings: dict[str, Any] | None = None) -> Path:
    from repo_paths import TAXONOMY_PATH

    cfg = settings or get_pipeline_settings()
    version_id = cfg.get("taxonomy_version_id")
    if not version_id:
        return TAXONOMY_PATH

    from hmi.taxonomy.export import nodes_to_yaml_document, serialize_taxonomy_yaml
    from hmi.taxonomy_db import get_version, list_nodes

    version = get_version(str(version_id))
    if not version:
        return TAXONOMY_PATH

    nodes = list_nodes(str(version_id))
    doc = nodes_to_yaml_document(version, nodes)
    out = LOCAL_ROOT / "config" / f"taxonomy_{version_id}.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(serialize_taxonomy_yaml(doc), encoding="utf-8")
    return out


def omni_label_prompt_overrides_for_worker() -> dict[str, str]:
    """Compact overrides stored on disk (for ClientConfig.omni_label_prompt)."""
    raw = get_pipeline_settings_for_save().get("omni_label_prompt") or {}
    if not isinstance(raw, dict) or not raw:
        return {}
    _, _, merge_fn, compact_fn = _sdk_prompt_helpers()
    return compact_fn(merge_fn(raw))
