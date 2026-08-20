"""Bind a local pipeline enqueue to a published DataType (preflight + recipe overlay)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hmi.platform.preflight import preflight
from hmi.platform.recipe import validate_recipe

_UPLOAD_KIND_TO_SOURCE = {
    "bag": "rosbag",
    "rosbag": "rosbag",
    "video": "video",
    "audio": "audio",
    "text": "text",
    "image": "image",
}


class PreflightError(ValueError):
    """Upload kinds do not satisfy a published DataType recipe."""

    def __init__(
        self,
        message: str,
        *,
        missing: list[str] | None = None,
        data_type_id: str = "",
        title: str = "",
    ) -> None:
        super().__init__(message)
        self.missing = list(missing or [])
        self.data_type_id = data_type_id
        self.title = title

    def http_detail(self) -> dict[str, Any]:
        return {
            "code": "PREFLIGHT_FAILED",
            "message": str(self),
            "missing": self.missing,
            "data_type_id": self.data_type_id,
        }


def upload_kind_to_source_kind(upload_kind: str) -> str:
    k = str(upload_kind or "").strip().lower()
    mapped = _UPLOAD_KIND_TO_SOURCE.get(k)
    if mapped is None:
        raise ValueError(f"unsupported upload kind={upload_kind!r}")
    return mapped


def source_kind_from_filename(filename: str) -> str | None:
    from hmi.local.source_upload import classify_source_filename

    kind = classify_source_filename(filename)
    if kind is None:
        suffix = Path(filename.replace("\\", "/")).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
            return "image"
        return None
    return upload_kind_to_source_kind(kind)


def source_kinds_from_filenames(filenames: list[str]) -> list[str]:
    out: list[str] = []
    for name in filenames:
        kind = source_kind_from_filename(name)
        if kind:
            out.append(kind)
    return out


def require_published_preflight(data_type_id: str, filenames: list[str]) -> dict[str, Any]:
    """Validate uploads against a published recipe. Does not create a Run."""
    from hmi.platform.store import get_data_type

    dt_id = str(data_type_id or "").strip()
    if not dt_id:
        raise PreflightError("请选择数据类型", missing=[], data_type_id="")
    recipe = get_data_type(dt_id)
    if recipe is None:
        raise PreflightError(f"未知数据类型 {dt_id}", missing=[], data_type_id=dt_id)
    rec = validate_recipe(recipe)
    if rec.get("status") != "published":
        raise PreflightError(
            f"数据类型 {rec.get('title') or dt_id} 未发布",
            missing=[],
            data_type_id=dt_id,
            title=str(rec.get("title") or ""),
        )
    kinds = source_kinds_from_filenames(filenames)
    result = preflight(rec, kinds)
    result["data_type_id"] = dt_id
    result["source_kinds"] = kinds
    result["title"] = rec.get("title") or dt_id
    if not result.get("ok"):
        missing = list(result.get("missing") or [])
        miss_txt = "、".join(missing) if missing else "所需源类型"
        raise PreflightError(
            f"预检失败：数据类型「{rec.get('title') or dt_id}」缺少 {miss_txt}",
            missing=missing,
            data_type_id=dt_id,
            title=str(rec.get("title") or ""),
        )
    return result


def overlay_run_request(recipe: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    """Kwargs for SDK RunRequest derived from recipe + user settings."""
    rec = validate_recipe(recipe)
    bbox_enabled = bool(settings.get("bbox_enabled", False))
    bbox_detector = str(settings.get("bbox_detector") or "opencv")
    yolo_classes = str(settings.get("bbox_yolo_classes") or "")
    if rec["bbox"]["enabled"]:
        bbox_enabled = True
        bbox_detector = rec["bbox"]["detector"]
        rec_classes = str(rec["bbox"].get("yolo_classes") or "").strip()
        if rec_classes:
            yolo_classes = rec_classes
    return {
        "need_label": bool(rec["stages"]["label"]["enabled"]),
        "need_embed": bool(rec["stages"]["embed"]["enabled"]),
        "bbox_enabled": bbox_enabled,
        "bbox_detector": bbox_detector,
        "bbox_yolo_classes": yolo_classes,
    }


def overlay_pipeline_settings(settings: dict[str, Any], recipe: dict[str, Any]) -> dict[str, Any]:
    """Copy of persisted settings with recipe-forced bbox fields (does not persist)."""
    out = dict(settings)
    overlay = overlay_run_request(recipe, settings)
    out["bbox_enabled"] = overlay["bbox_enabled"]
    out["bbox_detector"] = overlay["bbox_detector"]
    if overlay.get("bbox_yolo_classes"):
        out["bbox_yolo_classes"] = overlay["bbox_yolo_classes"]
    return out


def record_execution_platform_run(
    *,
    files: list[tuple[str, bytes]],
    data_type_id: str,
    pipeline_run_id: str,
    sample_id: str | None = None,
) -> dict[str, Any]:
    """Put upload bytes into the source lake and create a platform Run (y isolation)."""
    from hmi.platform.store import create_run, create_sample, put_source

    source_ids: list[str] = []
    for filename, data in files:
        kind = source_kind_from_filename(filename)
        if kind is None:
            continue
        kwargs: dict[str, Any] = {}
        if kind == "text":
            kwargs["text_schema_id"] = "generic_text"
        src = put_source(content=data, kind=kind, filename=filename, **kwargs)
        source_ids.append(src["source_id"])
    if not source_ids:
        raise ValueError("no classified sources to record")
    sample = create_sample(source_ids, sample_id=sample_id)
    return create_run(sample["sample_id"], data_type_id, pipeline_run_id=pipeline_run_id)
