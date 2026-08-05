"""Upload run grouping: one upload session → N bags (clip_id) → one shared pipeline run_id."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_UPLOADS_PREFIX = "rosbags/uploads/"
UPLOAD_RUN_MARKER_FILES = (".upload_complete", "upload_complete.json", "upload_manifest.json")
# yyyy-MM-dd-HH-mm-ss.ssss（UTC+8；ssss=4 位毫秒）
CN_TZ = timezone(timedelta(hours=8))
PIPELINE_RUN_ID_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.\d{4}$"
)


def new_pipeline_run_id(now: datetime | None = None) -> str:
    """一次 upload_run 共享的 pipeline run_id（UTC+8 毫秒时间戳，可读）。"""
    dt = now or datetime.now(CN_TZ)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=CN_TZ)
    else:
        dt = dt.astimezone(CN_TZ)
    ms = dt.microsecond // 1000
    return f"{dt.strftime('%Y-%m-%d-%H-%M-%S')}.{ms:04d}"


def normalize_uploads_prefix(prefix: str) -> str:
    text = (prefix or DEFAULT_UPLOADS_PREFIX).strip()
    if not text.endswith("/"):
        text += "/"
    return text


def upload_run_id_from_object_key(object_key: str, uploads_prefix: str = DEFAULT_UPLOADS_PREFIX) -> str | None:
    """``rosbags/uploads/{upload_run_id}/foo.bag`` → ``upload_run_id``."""
    prefix = normalize_uploads_prefix(uploads_prefix)
    key = object_key.strip("/")
    prefix_stripped = prefix.strip("/")
    if not key.startswith(prefix_stripped):
        return None
    rest = key[len(prefix_stripped) :].lstrip("/")
    if not rest or "/" not in rest:
        return None
    upload_run_id = rest.split("/", 1)[0].strip()
    return upload_run_id or None


def solo_upload_run_id(clip_id: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", clip_id)[-48:]
    return f"solo-{safe}"


def group_bags_by_upload_run(
    bags: list[dict[str, Any]],
    *,
    uploads_prefix: str = DEFAULT_UPLOADS_PREFIX,
    allow_legacy_flat: bool = False,
) -> list[dict[str, Any]]:
    """Group flat bag rows into upload runs (legacy flat → solo upload_run per bag)."""
    prefix = normalize_uploads_prefix(uploads_prefix)
    grouped: dict[str, dict[str, Any]] = {}

    for bag in bags:
        object_key = str(bag.get("object_key") or bag.get("bag_oss_key") or "").strip()
        clip_id = str(bag.get("clip_id") or "").strip()
        if not object_key or not clip_id:
            continue
        upload_run_id = upload_run_id_from_object_key(object_key, prefix)
        if upload_run_id is None:
            if not allow_legacy_flat:
                continue
            upload_run_id = solo_upload_run_id(clip_id)
        bucket = grouped.setdefault(
            upload_run_id,
            {
                "upload_run_id": upload_run_id,
                "upload_prefix": f"{prefix.strip('/')}/{upload_run_id}/",
                "bags": [],
                "complete": True,
            },
        )
        bucket["bags"].append(dict(bag))

    runs = list(grouped.values())
    runs.sort(key=lambda item: str(item.get("upload_run_id") or ""))
    return runs


def mark_upload_run_complete_flags(
    upload_runs: list[dict[str, Any]],
    *,
    mount_root: Any,
    uploads_prefix: str = DEFAULT_UPLOADS_PREFIX,
) -> list[dict[str, Any]]:
    """Set ``complete`` from marker files under each upload directory (DPE mount path)."""
    prefix = normalize_uploads_prefix(uploads_prefix)
    out: list[dict[str, Any]] = []
    for run in upload_runs:
        item = dict(run)
        upload_run_id = str(item.get("upload_run_id") or "").strip()
        if not upload_run_id:
            continue
        if str(upload_run_id).startswith("solo-"):
            item["complete"] = True
            out.append(item)
            continue
        upload_dir = mount_root / prefix.strip("/") / upload_run_id
        item["complete"] = any((upload_dir / name).is_file() for name in UPLOAD_RUN_MARKER_FILES)
        out.append(item)
    return out


def upload_run_state_oss_key(upload_run_id: str) -> str:
    return f"pipeline/upload_runs/{upload_run_id}.json"
