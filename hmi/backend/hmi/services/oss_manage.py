"""OSS bucket browser and file operations for HMI."""

from __future__ import annotations

import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import oss2

from hmi.config import get_settings
from hmi.data_source import is_local_mode
from hmi.oss_layout import OSS_LAYOUT_PREFIXES
from hmi.oss_signer import _bucket, sign_key

PREVIEW_MAX_BYTES = 256 * 1024
PREVIEW_JSONL_MAX_LINES = 40
PREVIEW_TEXT_SUFFIXES = frozenset(
    {
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".txt",
        ".md",
        ".log",
        ".csv",
        ".xml",
        ".keep",
        ".sql",
        ".py",
        ".js",
        ".ts",
        ".html",
        ".css",
        ".toml",
        ".ini",
        ".cfg",
        ".env",
    }
)


def _normalize_key(key: str) -> str:
    k = key.strip().lstrip("/").replace("\\", "/")
    if not k or ".." in k.split("/"):
        raise ValueError("invalid object key")
    return k


def _normalize_prefix(prefix: str) -> str:
    p = prefix.strip().lstrip("/").replace("\\", "/")
    if ".." in p.split("/"):
        raise ValueError("invalid prefix")
    return p


def get_oss_info() -> dict[str, Any]:
    if is_local_mode():
        from hmi.local.oss_publish import get_local_oss_info

        return get_local_oss_info()
    settings = get_settings()
    return {
        "bucket": settings["oss_bucket"],
        "endpoint": settings["oss_endpoint"],
        "root_prefixes": list(OSS_LAYOUT_PREFIXES),
    }


def list_objects(prefix: str = "", delimiter: str = "/", max_keys: int = 500) -> dict[str, Any]:
    if is_local_mode():
        from hmi.local.oss_publish import list_local_objects

        return list_local_objects(prefix=prefix, delimiter=delimiter, max_keys=max_keys)
    prefix = _normalize_prefix(prefix)
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    bucket = _bucket()
    settings = get_settings()
    items: list[dict[str, Any]] = []

    for obj in oss2.ObjectIterator(bucket, prefix=prefix, delimiter=delimiter, max_keys=max_keys):
        if obj.is_prefix():
            name = obj.key[len(prefix) :].rstrip("/")
            if not name:
                continue
            items.append(
                {
                    "name": name,
                    "key": obj.key,
                    "type": "dir",
                    "size": 0,
                    "last_modified": None,
                }
            )
        else:
            name = obj.key[len(prefix) :] if prefix else obj.key
            if not name or name.endswith("/"):
                continue
            lm = getattr(obj, "last_modified", None)
            items.append(
                {
                    "name": name,
                    "key": obj.key,
                    "type": "file",
                    "size": int(getattr(obj, "size", 0) or 0),
                    "last_modified": lm.isoformat() if isinstance(lm, datetime) else None,
                }
            )

    items.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
    parent = ""
    if prefix:
        parts = prefix.rstrip("/").split("/")
        parent = "/".join(parts[:-1])
        if parent:
            parent += "/"

    return {
        "bucket": settings["oss_bucket"],
        "prefix": prefix,
        "parent_prefix": parent,
        "items": items,
    }


def upload_bytes(key: str, data: bytes, *, content_type: str | None = None) -> dict[str, Any]:
    if is_local_mode():
        from hmi.local.oss_publish import upload_local_bytes

        return upload_local_bytes(key, data, content_type=content_type)
    key = _normalize_key(key)
    ct = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    bucket = _bucket()
    bucket.put_object(key, data, headers={"Content-Type": ct})
    return {"key": key, "size": len(data), "uploaded_at": datetime.now(timezone.utc).isoformat()}


def resolve_upload_key(prefix: str, filename: str) -> str:
    """Place file under current prefix; .bag under rosbags/ uses collection subfolder."""
    prefix = _normalize_prefix(prefix)
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    safe_name = filename.replace("\\", "/").split("/")[-1].strip()
    if not safe_name:
        raise ValueError("empty filename")

    settings = get_settings()
    data_prefix = settings["oss_data_prefix"].strip("/") + "/"
    if safe_name.lower().endswith(".bag") and prefix.rstrip("/") == data_prefix.rstrip("/"):
        stem = safe_name[:-4] if safe_name.lower().endswith(".bag") else safe_name
        return f"{prefix}{stem}/{safe_name}"

    return f"{prefix}{safe_name}"


def delete_objects(keys: list[str]) -> dict[str, Any]:
    normalized = [_normalize_key(k) for k in keys if k.strip()]
    if not normalized:
        raise ValueError("no keys to delete")
    bucket = _bucket()
    if len(normalized) == 1:
        bucket.delete_object(normalized[0])
        return {"deleted": normalized}
    bucket.batch_delete_objects(normalized)
    return {"deleted": normalized}


def delete_prefix(prefix: str) -> dict[str, Any]:
    prefix = _normalize_prefix(prefix)
    if not prefix.endswith("/"):
        prefix += "/"
    bucket = _bucket()
    keys: list[str] = []
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
        if not obj.is_prefix():
            keys.append(obj.key)
    if not keys:
        return {"deleted": [], "prefix": prefix}
    if len(keys) <= 1000:
        bucket.batch_delete_objects(keys)
    else:
        for i in range(0, len(keys), 1000):
            bucket.batch_delete_objects(keys[i : i + 1000])
    return {"deleted": keys, "prefix": prefix, "count": len(keys)}


def mkdir(prefix: str) -> dict[str, Any]:
    prefix = _normalize_prefix(prefix)
    if not prefix.endswith("/"):
        prefix += "/"
    key = f"{prefix}.keep"
    return upload_bytes(key, b"# oss folder marker\n", content_type="text/plain")


def download_url(key: str, expires: int = 3600) -> dict[str, str]:
    key = _normalize_key(key)
    if is_local_mode():
        from urllib.parse import quote

        q = quote(key, safe="")
        return {"key": key, "url": f"/api/oss/file?key={q}"}
    return {"key": key, "url": sign_key(key, expires=expires)}


def local_file_path(key: str) -> Path:
    from hmi.data_source import oss_key_path

    key = _normalize_key(key)
    path = oss_key_path(key)
    if not path.is_file():
        raise FileNotFoundError(key)
    return path


def _read_object_bytes(key: str, *, max_bytes: int) -> tuple[bytes, int]:
    if is_local_mode():
        path = local_file_path(key)
        size = path.stat().st_size
        with path.open("rb") as fh:
            return fh.read(max_bytes), size
    bucket = _bucket()
    meta = bucket.head_object(key)
    size = int(getattr(meta, "content_length", 0) or 0)
    if size <= max_bytes:
        return bucket.get_object(key).read(), size
    end = max(0, max_bytes - 1)
    return bucket.get_object(key, byte_range=(0, end)).read(), size


def preview_object(key: str) -> dict[str, Any]:
    key = _normalize_key(key)
    name = key.rsplit("/", 1)[-1]
    ext = Path(name).suffix.lower()
    if ext not in PREVIEW_TEXT_SUFFIXES:
        raise ValueError(f"preview not supported for {ext or 'this file type'}")

    raw, total_size = _read_object_bytes(key, max_bytes=PREVIEW_MAX_BYTES)
    truncated_bytes = total_size > len(raw)
    text = raw.decode("utf-8", errors="replace")
    content_type = mimetypes.guess_type(name)[0] or "text/plain"

    if ext == ".json":
        fmt = "json"
        try:
            preview = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            fmt = "text"
            preview = text
    elif ext == ".jsonl":
        fmt = "jsonl"
        lines = text.splitlines()
        parsed: list[Any] = []
        for line in lines[:PREVIEW_JSONL_MAX_LINES]:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                parsed.append(json.loads(stripped))
            except json.JSONDecodeError:
                parsed.append(stripped)
        preview = json.dumps(parsed, ensure_ascii=False, indent=2)
        truncated_lines = len(lines) > PREVIEW_JSONL_MAX_LINES
    else:
        fmt = "text"
        preview = text
        truncated_lines = False

    return {
        "key": key,
        "name": name,
        "size": total_size,
        "content_type": content_type,
        "format": fmt,
        "preview": preview,
        "truncated": truncated_bytes or (ext == ".jsonl" and truncated_lines),
        "preview_bytes": len(raw),
    }
