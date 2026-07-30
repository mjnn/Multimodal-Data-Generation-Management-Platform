"""Publish / browse simulated OSS under hmi_runtime/oss/."""

from __future__ import annotations

import json
import mimetypes
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hmi.data_source import (
    LOCAL_OSS_ROOT,
    artifacts_dir,
    oss_key_path,
    safe_clip_dir,
)
from hmi.oss_layout import OSS_LAYOUT_PREFIXES
from hmi.services.pipeline_status import DISPATCH_MANIFEST_KEY

LOCAL_BUCKET_LABEL = "本地磁盘"


def clip_run_oss_prefix(clip_id: str, run_id: str) -> str:
    """Filesystem-safe OSS key prefix for sdk_v1 clip runs."""
    return f"clips/{safe_clip_dir(clip_id)}/runs/{run_id}/"


def clip_run_oss_dir(clip_id: str, run_id: str) -> Path:
    return oss_key_path(clip_run_oss_prefix(clip_id, run_id))


def mirror_tree_to_oss(*, source: Path, oss_prefix: str) -> int:
    """Copy all files under source into LOCAL_OSS_ROOT/oss_prefix/rel."""
    if not source.is_dir():
        return 0
    base = oss_key_path(oss_prefix.rstrip("/") + "/")
    count = 0
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        dest = base / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        count += 1
    return count


def mirror_artifacts_run_to_oss(clip_id: str, run_id: str) -> int:
    src = artifacts_dir(clip_id, run_id)
    if not src.is_dir():
        raise FileNotFoundError(f"artifacts run missing: {src}")
    return mirror_tree_to_oss(source=src, oss_prefix=clip_run_oss_prefix(clip_id, run_id))


def write_local_dispatch_manifest(
    *,
    clip_id: str,
    run_id: str,
    bag_oss_key: str,
    ds: str | None = None,
) -> Path:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    rel_key = bag_oss_key[len("local://") :] if bag_oss_key.startswith("local://") else bag_oss_key
    payload: dict[str, Any] = {
        "action": "run",
        "clip_id": clip_id,
        "run_id": run_id,
        "bag_oss_key": rel_key,
        "ds": ds,
        "dispatched_at": now,
        "source": "local_sdk_worker",
    }
    path = oss_key_path(DISPATCH_MANIFEST_KEY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def read_local_dispatch_manifest() -> dict[str, Any] | None:
    path = oss_key_path(DISPATCH_MANIFEST_KEY)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def mirror_all_artifact_runs_to_oss() -> dict[str, int]:
    """Backfill oss/clips from artifacts/clips (existing imports)."""
    from hmi.local import store

    store.ensure_db()
    rows = store.query("SELECT clip_id, active_run_id FROM dim_clip WHERE active_run_id IS NOT NULL")
    ok = 0
    files = 0
    for row in rows:
        clip_id = str(row["clip_id"])
        run_id = str(row["active_run_id"])
        try:
            n = mirror_artifacts_run_to_oss(clip_id, run_id)
            if n > 0:
                ok += 1
                files += n
        except FileNotFoundError:
            continue
    return {"clips": ok, "files": files}


def _normalize_prefix(prefix: str) -> str:
    p = prefix.strip().lstrip("/").replace("\\", "/")
    if ".." in p.split("/"):
        raise ValueError("invalid prefix")
    return p


def list_local_objects(prefix: str = "", delimiter: str = "/", max_keys: int = 500) -> dict[str, Any]:
    prefix = _normalize_prefix(prefix)
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    root = LOCAL_OSS_ROOT
    base = root / prefix if prefix else root
    if not base.is_dir():
        base.mkdir(parents=True, exist_ok=True)

    items: list[dict[str, Any]] = []
    if delimiter == "/":
        try:
            children = sorted(base.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            children = []
        for child in children[:max_keys]:
            name = child.name
            key = f"{prefix}{name}/" if child.is_dir() else f"{prefix}{name}"
            if child.is_dir():
                items.append(
                    {
                        "name": name,
                        "key": key,
                        "type": "dir",
                        "size": 0,
                        "last_modified": None,
                    }
                )
            else:
                stat = child.stat()
                items.append(
                    {
                        "name": name,
                        "key": key,
                        "type": "file",
                        "size": int(stat.st_size),
                        "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    }
                )
    else:
        count = 0
        for path in base.rglob("*"):
            if count >= max_keys:
                break
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
            items.append(
                {
                    "name": path.name,
                    "key": rel,
                    "type": "file",
                    "size": int(stat.st_size),
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
            count += 1

    items.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    parent = ""
    if prefix:
        parts = prefix.rstrip("/").split("/")
        parent = "/".join(parts[:-1])
        if parent:
            parent += "/"

    return {
        "bucket": LOCAL_BUCKET_LABEL,
        "prefix": prefix,
        "parent_prefix": parent,
        "items": items,
    }


def get_local_oss_info() -> dict[str, Any]:
    return {
        "bucket": LOCAL_BUCKET_LABEL,
        "endpoint": str(LOCAL_OSS_ROOT.resolve()),
        "root_prefixes": list(OSS_LAYOUT_PREFIXES),
        "simulated": True,
    }


def upload_local_bytes(key: str, data: bytes, *, content_type: str | None = None) -> dict[str, Any]:
    key = key.strip().lstrip("/").replace("\\", "/")
    if not key or ".." in key.split("/"):
        raise ValueError("invalid object key")
    path = oss_key_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    _ = content_type or mimetypes.guess_type(key)[0]
    return {
        "key": key,
        "size": len(data),
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
