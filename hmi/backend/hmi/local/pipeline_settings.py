"""Persisted SDK pipeline run parameters for local HMI."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from hmi.data_source import LOCAL_ROOT

_SETTINGS_PATH = LOCAL_ROOT / "config" / "pipeline_settings.json"

# SDK still accepts noop/stub (tests/smoke via BBOX_DETECTOR env); product UI hides them.
_VALID_BBOX_DETECTORS = frozenset({"noop", "stub", "opencv", "yolo"})
_UI_HIDDEN_BBOX_DETECTORS = frozenset({"noop", "stub"})
_DEFAULT_PRODUCT_DETECTOR = "opencv"

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
    # BBox / encode preview (local SDK → BBOX_* / ENCODE_* env)
    "bbox_enabled": False,
    "bbox_detector": _DEFAULT_PRODUCT_DETECTOR,
    "bbox_element": "element",
    "encode_plain": True,
    "encode_bbox": False,
    "bbox_yolo_model": "yolov8n.pt",
    "bbox_yolo_conf": 0.25,
    # Comma-separated YOLO class names/ids (empty = all). Maps to BBOX_YOLO_CLASSES.
    "bbox_yolo_classes": "",
    # Inject BBox class/element summary into Omni label prompt (BBOX_IN_LABEL_PROMPT)
    "bbox_in_label_prompt": True,
    # OpenCV face gender/age DNN (BBOX_FACE_ATTRS); ignored by stub/yolo/noop
    "bbox_face_attrs": True,
    # Preview MP4 encode quality (CLIP_VIDEO_*)
    "clip_video_max_width": 1920,
    "clip_video_max_height": 1080,
    "clip_video_crf": 18,
}


def _product_bbox_detector(detector: str) -> str:
    """Map UI-hidden detectors to the product default (opencv)."""
    det = str(detector or "").strip().lower()
    if det not in _VALID_BBOX_DETECTORS or det in _UI_HIDDEN_BBOX_DETECTORS:
        return _DEFAULT_PRODUCT_DETECTOR
    return det


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


def get_bbox_detector_options() -> list[dict[str, str]]:
    """Product UI catalog (SDK list_detectors minus noop/stub smoke backends).

    noop/stub remain valid for SDK env / unit tests; set BBOX_DETECTOR directly
    or call apply_bbox_settings_to_environ with those ids — they are not listed here.
    """
    try:
        from oms_multimodal.bbox import list_detectors

        raw = list_detectors()
    except Exception:  # noqa: BLE001
        raw = [
            {
                "id": "opencv",
                "aliases": "opencv,haar,face",
                "desc": "OpenCV Haar cascade backend",
            },
            {
                "id": "yolo",
                "aliases": "yolo,ultralytics",
                "desc": "Ultralytics YOLO (optional deps)",
                "available": "0",
            },
        ]
    return [d for d in raw if str(d.get("id") or "").strip().lower() not in _UI_HIDDEN_BBOX_DETECTORS]


def is_yolo_ready() -> bool:
    """Whether BBOX_DETECTOR=yolo can run in this process."""
    try:
        from oms_multimodal.bbox import yolo_available

        return bool(yolo_available())
    except Exception:  # noqa: BLE001
        return False


def assert_bbox_settings_runnable(settings: dict[str, Any] | None = None) -> None:
    """Raise RuntimeError early if enabled YOLO lacks ultralytics."""
    cfg = settings if settings is not None else get_pipeline_settings_for_save()
    if not bool(cfg.get("bbox_enabled")):
        return
    detector = str(cfg.get("bbox_detector") or "noop").strip().lower()
    if detector != "yolo":
        return
    if is_yolo_ready():
        return
    from oms_multimodal.bbox import require_yolo_extra

    require_yolo_extra()


def get_bbox_yolo_class_catalog() -> list[dict[str, Any]]:
    """COCO-80 class checklist for pipeline settings UI."""
    try:
        from oms_multimodal.bbox import list_yolo_class_catalog

        return list_yolo_class_catalog()
    except Exception:  # noqa: BLE001
        return []


def get_bbox_yolo_class_presets() -> list[dict[str, Any]]:
    """YOLO class checklist presets (cabin leftover, person, vehicle, …)."""
    try:
        from oms_multimodal.bbox import list_yolo_class_presets

        return list_yolo_class_presets()
    except Exception:  # noqa: BLE001
        return []


def apply_bbox_settings_to_environ(settings: dict[str, Any] | None = None) -> dict[str, str]:
    """Set BBOX_*/ENCODE_* for the current process; return the applied map."""
    cfg = settings if settings is not None else get_pipeline_settings_for_save()
    bbox_enabled = bool(cfg.get("bbox_enabled"))
    detector = str(cfg.get("bbox_detector") or "noop").strip().lower()
    if detector not in _VALID_BBOX_DETECTORS:
        detector = "noop"
    encode_plain = bool(cfg.get("encode_plain", True))
    encode_bbox = bool(cfg.get("encode_bbox")) or bbox_enabled
    if bbox_enabled and detector == "noop":
        # Enabled with noop still runs annotate (empty boxes) + optional encode_bbox.
        pass
    applied = {
        "BBOX_ENABLED": "1" if bbox_enabled else "0",
        "BBOX_DETECTOR": detector if bbox_enabled else "noop",
        "BBOX_ELEMENT": str(cfg.get("bbox_element") or "element").strip() or "element",
        "ENCODE_PLAIN": "1" if encode_plain else "0",
        "ENCODE_BBOX": "1" if encode_bbox else "0",
        "BBOX_YOLO_MODEL": str(cfg.get("bbox_yolo_model") or "yolov8n.pt").strip() or "yolov8n.pt",
        "BBOX_YOLO_CONF": str(float(cfg.get("bbox_yolo_conf") if cfg.get("bbox_yolo_conf") is not None else 0.25)),
        "BBOX_YOLO_CLASSES": str(cfg.get("bbox_yolo_classes") or "").strip(),
        "BBOX_IN_LABEL_PROMPT": "1" if bool(cfg.get("bbox_in_label_prompt", True)) else "0",
        "BBOX_FACE_ATTRS": "1" if bool(cfg.get("bbox_face_attrs", True)) else "0",
        "CLIP_VIDEO_MAX_WIDTH": str(int(cfg.get("clip_video_max_width") or 1920)),
        "CLIP_VIDEO_MAX_HEIGHT": str(int(cfg.get("clip_video_max_height") or 1080)),
        "CLIP_VIDEO_CRF": str(int(cfg.get("clip_video_crf") if cfg.get("clip_video_crf") is not None else 18)),
    }
    for key, val in applied.items():
        os.environ[key] = val
    return applied


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
    return "默认（仓库标签树）"


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
    for bool_key in ("bbox_enabled", "encode_plain", "encode_bbox", "bbox_in_label_prompt", "bbox_face_attrs"):
        out[bool_key] = bool(out.get(bool_key))
    # Migrate legacy noop/stub (and unknown) to opencv for product settings.
    out["bbox_detector"] = _product_bbox_detector(str(out.get("bbox_detector") or ""))
    out["bbox_element"] = str(out.get("bbox_element") or "element").strip() or "element"
    out["bbox_yolo_model"] = str(out.get("bbox_yolo_model") or "yolov8n.pt").strip() or "yolov8n.pt"
    try:
        out["bbox_yolo_conf"] = float(out.get("bbox_yolo_conf") if out.get("bbox_yolo_conf") is not None else 0.25)
    except (TypeError, ValueError):
        out["bbox_yolo_conf"] = 0.25
    # Normalize class list: accept list[str]|str → comma-separated names
    raw_classes = out.get("bbox_yolo_classes")
    if isinstance(raw_classes, list):
        out["bbox_yolo_classes"] = ",".join(str(x).strip() for x in raw_classes if str(x).strip())
    else:
        out["bbox_yolo_classes"] = str(raw_classes or "").strip()
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
        elif key in {"sample_fps", "min_sec", "max_sec", "bbox_yolo_conf"}:
            current[key] = float(val)
        elif key == "max_clips":
            current[key] = int(val) if val is not None else 1
        elif key == "sdk_parallel":
            current[key] = max(1, min(8, int(val if val is not None else 1)))
        elif key in {"omni_model", "embedding_model"}:
            current[key] = str(val or "default")
        elif key == "bbox_element":
            current[key] = str(val or "element").strip() or "element"
        elif key == "bbox_yolo_model":
            current[key] = str(val or "yolov8n.pt").strip() or "yolov8n.pt"
        elif key == "bbox_yolo_classes":
            if isinstance(val, list):
                current[key] = ",".join(str(x).strip() for x in val if str(x).strip())
            else:
                current[key] = str(val or "").strip()
        elif key == "bbox_detector":
            # Persist product detectors only; noop/stub → opencv (SDK smoke still via env).
            current[key] = _product_bbox_detector(str(val or ""))
        elif key in {"bbox_enabled", "encode_plain", "encode_bbox", "bbox_in_label_prompt", "bbox_face_attrs"}:
            current[key] = bool(val)
        elif key in {"clip_video_max_width", "clip_video_max_height", "clip_video_crf"}:
            try:
                current[key] = int(val)
            except (TypeError, ValueError):
                current[key] = _DEFAULTS[key]
        elif key == "omni_label_prompt":
            if isinstance(val, dict):
                _, _, merge_fn, compact_fn = _sdk_prompt_helpers()
                merged = merge_fn(val)
                current[key] = compact_fn(merged)
            else:
                current[key] = {}
    # Opening bbox detection implies encode_bbox so Explorer can toggle.
    if current.get("bbox_enabled"):
        current["encode_bbox"] = True
        # Default: feed detected classes into Omni prompt when BBox is enabled
        if "bbox_in_label_prompt" not in updates:
            current.setdefault("bbox_in_label_prompt", True)
        if "bbox_face_attrs" not in updates:
            current.setdefault("bbox_face_attrs", True)
        if not current.get("encode_plain") and not current.get("encode_bbox"):
            current["encode_plain"] = True
        # Fail fast in UI save when YOLO is selected without ultralytics.
        if str(current.get("bbox_detector") or "").strip().lower() == "yolo":
            assert_bbox_settings_runnable(current)
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
