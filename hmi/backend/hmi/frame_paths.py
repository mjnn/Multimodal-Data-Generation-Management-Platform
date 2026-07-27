"""Normalize fact_frame.image_path (bucket-root or run-relative)."""

from __future__ import annotations


def normalize_image_path(raw: str) -> str:
    return str(raw or "").strip().lstrip("/").replace("\\", "/")


def strip_run_prefix(clip_id: str, run_id: str, image_path: str) -> str:
    """MC Job1 stores bucket-root keys; local artifacts are under run root."""
    rel = normalize_image_path(image_path)
    for clip in (clip_id, clip_id.replace(":", "__")):
        prefix = f"clips/{clip}/runs/{run_id}/"
        if rel.startswith(prefix):
            return rel[len(prefix) :]
    return rel


def to_oss_object_key(
    settings: dict[str, str], clip_id: str, run_id: str, image_path: str
) -> str:
    rel = normalize_image_path(image_path)
    if rel.startswith("clips/"):
        return rel
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    prefix = f"{clip_prefix}/{runs_subdir}".strip("/")
    return f"{prefix}/{rel}"
