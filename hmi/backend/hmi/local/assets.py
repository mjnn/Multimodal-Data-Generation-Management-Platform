"""Local artifact URL helpers."""

from __future__ import annotations

import os
from urllib.parse import quote

from hmi.data_source import artifact_path
from hmi.frame_paths import strip_run_prefix


def _public_api_base() -> str:
    """Public API prefix as seen by the browser (supports Nginx subpath)."""
    base = (os.getenv("HMI_PUBLIC_API_BASE") or "/api").strip().rstrip("/")
    return base or "/api"


def local_file_url(clip_id: str, run_id: str, rel_path: str) -> str:
    rel = rel_path.lstrip("/").replace("\\", "/")
    clip_q = quote(clip_id, safe="")
    return f"{_public_api_base()}/local-files/clips/{clip_q}/runs/{run_id}/{rel}"


def local_image_url(clip_id: str, run_id: str, image_path: str) -> str:
    return local_file_url(clip_id, run_id, strip_run_prefix(clip_id, run_id, image_path))


def local_audio_url(clip_id: str, run_id: str, audio_relpath: str) -> str:
    return local_file_url(clip_id, run_id, audio_relpath)


def file_exists(clip_id: str, run_id: str, rel_path: str) -> bool:
    rel = strip_run_prefix(clip_id, run_id, rel_path)
    return artifact_path(clip_id, run_id, rel).is_file()
