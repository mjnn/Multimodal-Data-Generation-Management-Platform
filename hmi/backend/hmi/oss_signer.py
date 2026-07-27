"""OSS presigned URL helpers."""

from __future__ import annotations

from functools import lru_cache

import oss2

from hmi.config import get_settings
from hmi.frame_paths import to_oss_object_key


@lru_cache
def _bucket() -> oss2.Bucket:
    s = get_settings()
    auth = oss2.Auth(s["odps_access_id"], s["odps_access_key"])
    return oss2.Bucket(auth, s["oss_endpoint"], s["oss_bucket"])


def run_prefix(settings: dict[str, str], clip_id: str, run_id: str) -> str:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs_subdir}/"


def image_object_key(settings: dict[str, str], clip_id: str, run_id: str, image_path: str) -> str:
    """Job1 fact_frame.image_path is bucket-root or run-relative; normalize before sign."""
    return to_oss_object_key(settings, clip_id, run_id, image_path)


def sign_key(
    object_key: str,
    expires: int = 3600,
    *,
    params: dict[str, str] | None = None,
) -> str:
    return _bucket().sign_url("GET", object_key.lstrip("/"), expires, params=params or None)


def sign_image(
    settings: dict[str, str],
    clip_id: str,
    run_id: str,
    image_path: str,
    expires: int = 3600,
) -> str:
    return sign_key(image_object_key(settings, clip_id, run_id, image_path), expires)


def upload_rosbag_bytes(filename: str, data: bytes) -> str:
    s = get_settings()
    stem = filename
    if stem.lower().endswith(".bag"):
        stem = stem[:-4]
    # rosbags/{collection_dir}/output.bag — use filename stem as folder
    object_key = f"{s['oss_data_prefix'].strip('/')}/{stem}/{filename}"
    bucket = _bucket()
    bucket.put_object(object_key, data, headers={"Content-Type": "application/octet-stream"})
    return object_key


def put_object_text(
    object_key: str,
    text: str,
    *,
    content_type: str = "application/json",
) -> None:
    put_object_bytes(
        object_key,
        text.encode("utf-8"),
        content_type=content_type,
    )


def put_object_bytes(
    object_key: str,
    data: bytes,
    *,
    content_type: str = "application/octet-stream",
) -> None:
    key = object_key.lstrip("/")
    _bucket().put_object(
        key,
        data,
        headers={"Content-Type": content_type},
    )


def object_exists(object_key: str) -> bool:
    key = object_key.lstrip("/")
    return bool(_bucket().object_exists(key))


def get_object_text(object_key: str) -> str | None:
    key = object_key.lstrip("/")
    try:
        return _bucket().get_object(key).read().decode("utf-8")
    except oss2.exceptions.NoSuchKey:
        return None
    except oss2.exceptions.NotFound:
        return None


def get_object_json(object_key: str) -> dict | None:
    import json

    raw = get_object_text(object_key)
    if raw is None:
        return None
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return loaded if isinstance(loaded, dict) else None
