"""把本地排队开跑绑定到已发布 DataType（预检 + 配方覆盖）。

管线管理多选源时走这里，而不是让用户手搓 Sample。
"""

from __future__ import annotations

from typing import Any

from hmi.platform.file_kinds import modality_of, normalize_source_kind
from hmi.platform.preflight import preflight
from hmi.platform.recipe import validate_recipe


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
    from hmi.platform.file_kinds import resolve_source_kind

    mapped = resolve_source_kind(kind=upload_kind)
    if mapped is None:
        raise ValueError(f"unsupported upload kind={upload_kind!r}")
    return mapped


def source_kind_from_filename(filename: str) -> str | None:
    from hmi.platform.file_kinds import kind_from_filename, resolve_source_kind

    return kind_from_filename(filename) or resolve_source_kind(kind=None, filename=filename)


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


def validate_source_assignments(
    recipe: dict[str, Any],
    assignments: list[dict[str, Any]],
    *,
    source_kind_by_id: dict[str, str],
) -> list[str]:
    """Flatten assignments into source_ids. Raise ValueError naming the slot title."""
    rec = validate_recipe(recipe)
    slot_by_id = {str(s["id"]): s for s in rec.get("slots") or []}
    assigned: dict[str, list[str]] = {}
    for asg in assignments or []:
        if not isinstance(asg, dict):
            raise ValueError("assignments items must be objects")
        slot_id = str(asg.get("slot_id") or "").strip()
        if not slot_id:
            raise ValueError("assignments.slot_id required")
        if slot_id not in slot_by_id:
            raise ValueError(f"unknown slot_id={slot_id}")
        if slot_id in assigned:
            raise ValueError(f"duplicate assignment for slot {slot_id}")
        ids = [str(s).strip() for s in (asg.get("source_ids") or []) if str(s).strip()]
        assigned[slot_id] = ids

    seen: set[str] = set()
    flattened: list[str] = []
    for slot in rec.get("slots") or []:
        slot_id = str(slot["id"])
        title = str(slot.get("title") or slot_id)
        ids = assigned.get(slot_id)
        if ids is None:
            if slot.get("required"):
                raise ValueError(f"assignments required for {title}")
            continue
        cmin = int(slot.get("cardinality_min") or 1)
        cmax = int(slot.get("cardinality_max") or cmin)
        n = len(ids)
        if n < cmin or n > cmax:
            raise ValueError(f"{title}：需要 {cmin}–{cmax} 个文件，已选 {n}")
        allowed: set[str] = set()
        for kind in slot.get("kinds") or []:
            nk = normalize_source_kind(str(kind)) or str(kind).strip().lower()
            if nk:
                allowed.add(nk)
        for sid in ids:
            if sid in seen:
                raise ValueError(f"source {sid} assigned to multiple slots")
            seen.add(sid)
            raw_kind = source_kind_by_id.get(sid)
            if raw_kind is None:
                raise ValueError(f"unknown source_id={sid}")
            nk = normalize_source_kind(str(raw_kind)) or str(raw_kind).strip().lower()
            if nk not in allowed:
                raise ValueError(f"{title}：文件类型 {nk} 不在允许的 {sorted(allowed)}")
            flattened.append(sid)
    return flattened


def resolve_run_source_bindings(
    recipe: dict[str, Any],
    *,
    source_ids: list[str] | None = None,
    assignments: list[dict[str, Any]] | None = None,
    source_kind_by_id: dict[str, str],
) -> list[str]:
    """Shared by create_run_from_sources and POST /runs/preflight.

    Explicit assignments always win. Bare source_ids auto-wrap into the sole slot;
    multi-slot recipes require assignments.
    """
    rec = validate_recipe(recipe)
    if assignments:
        return validate_source_assignments(rec, assignments, source_kind_by_id=source_kind_by_id)
    ids = [str(s).strip() for s in (source_ids or []) if str(s).strip()]
    slots = list(rec.get("slots") or [])
    if len(slots) != 1:
        raise ValueError("assignments required")
    if not ids:
        raise ValueError("source_ids required")
    return validate_source_assignments(
        rec,
        [{"slot_id": str(slots[0]["id"]), "source_ids": ids}],
        source_kind_by_id=source_kind_by_id,
    )


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
        if modality_of(kind) == "text":
            kwargs["text_schema_id"] = "generic_text"
        src = put_source(content=data, kind=kind, filename=filename, **kwargs)
        source_ids.append(src["source_id"])
    if not source_ids:
        raise ValueError("no classified sources to record")
    sample = create_sample(source_ids, sample_id=sample_id)
    return create_run(sample["sample_id"], data_type_id, pipeline_run_id=pipeline_run_id)
