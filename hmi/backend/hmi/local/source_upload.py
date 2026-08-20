"""Save uploaded raw video / audio / text as a local source package for SDK ingest.

Layout under LOCAL_OSS_ROOT::

    sources/{collection}__{hash12}/
      video.mp4 | audio.wav | text.txt
      source_manifest.json

``bag_oss_key`` is ``local://sources/.../source_manifest.json`` so the local SDK
worker can discover modality packages the same way it discovers bags.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hmi.data_source import LOCAL_OSS_ROOT, oss_key_path
from hmi.local import pipeline_run as pr
from hmi.local.bag_upload import collection_dir_from_filename

VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv", ".avi"}
AUDIO_EXTS = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".dat"}
TEXT_EXTS = {".txt", ".json", ".md", ".csv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def classify_source_filename(filename: str) -> str | None:
    """Return modality kind: video | audio | text | image | bag | None."""
    name = Path(filename.replace("\\", "/")).name.lower()
    if name.endswith(".bag"):
        return "bag"
    suffix = Path(name).suffix
    if suffix in VIDEO_EXTS:
        return "video"
    if suffix in AUDIO_EXTS:
        return "audio"
    if suffix in TEXT_EXTS:
        return "text"
    if suffix in IMAGE_EXTS:
        return "image"
    return None


def _utc_ds() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _storage_dir_name(label: str, content_sha256: str) -> str:
    coll = re.sub(r"[^a-zA-Z0-9_-]+", "_", label).strip("_") or "sources"
    digest = content_sha256.strip().lower()
    if len(digest) < 12:
        raise ValueError("content_sha256 too short")
    return f"{coll}__{digest[:12]}"


def save_uploaded_sources(
    files: list[tuple[str, bytes]],
    *,
    run_id: str | None = None,
    ds: str | None = None,
    execution_started_at: str | None = None,
) -> dict[str, Any]:
    """Persist one modality package (video and/or audio and/or text) and enqueue SDK run."""
    if not files:
        raise ValueError("at least one media file required")

    by_kind: dict[str, tuple[str, bytes]] = {}
    for filename, data in files:
        kind = classify_source_filename(filename)
        if kind is None or kind == "bag":
            raise ValueError(f"unsupported source file: {filename}")
        if kind in by_kind:
            raise ValueError(f"duplicate {kind} file in one source package (got {filename})")
        by_kind[kind] = (filename, data)

    hasher = hashlib.sha256()
    for kind in sorted(by_kind):
        hasher.update(kind.encode("utf-8"))
        hasher.update(by_kind[kind][1])
    digest = hasher.hexdigest()
    clip_id = f"sha256:{digest}"

    first_name = next(iter(by_kind.values()))[0]
    coll = collection_dir_from_filename(first_name)
    storage_dir = _storage_dir_name(coll, digest)
    dest_dir = LOCAL_OSS_ROOT / "sources" / storage_dir
    dest_dir.mkdir(parents=True, exist_ok=True)

    modalities: list[str] = []
    rel_paths: dict[str, str] = {}
    for kind, (filename, data) in by_kind.items():
        ext = Path(filename).suffix.lower() or {
            "video": ".mp4",
            "audio": ".wav",
            "text": ".txt",
        }.get(kind, "")
        dest_name = f"{kind}{ext}"
        (dest_dir / dest_name).write_bytes(data)
        modalities.append(kind)
        rel_paths[kind] = dest_name

    manifest = {
        "clip_id": clip_id,
        "source_name": coll,
        "modalities": modalities,
        "has_preencoded_video": "video" in modalities,
        "video": rel_paths.get("video"),
        "audio": rel_paths.get("audio"),
        "text": rel_paths.get("text"),
        "video_path": rel_paths.get("video"),
        "audio_path": rel_paths.get("audio"),
        "text_path": rel_paths.get("text"),
    }
    manifest_path = dest_dir / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    run_id = run_id or str(uuid.uuid4())
    ds = ds or _utc_ds()
    oss_key = f"sources/{storage_dir}/source_manifest.json"
    bag_oss_key = f"local://{oss_key}"

    pr.upsert_clip_row(
        clip_id=clip_id,
        clip_dir_name=coll,
        content_hash=digest[:64],
        bag_oss_key=bag_oss_key,
        active_run_id=run_id,
    )
    pr.upsert_run(
        run_id=run_id,
        clip_id=clip_id,
        ds=ds,
        status="pending",
        started_at=execution_started_at,
        reset_started_at=bool(execution_started_at),
    )
    pr.init_sdk_steps(run_id=run_id, clip_id=clip_id, ds=ds)
    pr.set_step(
        run_id=run_id,
        clip_id=clip_id,
        ds=ds,
        step_id="sdk_discover",
        status="success",
    )

    return {
        "oss_key": oss_key,
        "bag_oss_key": bag_oss_key,
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": ds,
        "size_bytes": sum(len(d) for _, d in by_kind.values()),
        "local_path": str(manifest_path),
        "modalities": modalities,
        "source_kind": "raw_media",
    }


def resolve_local_source_manifest(bag_oss_key: str) -> Path | None:
    """Map ``local://sources/...`` or ``local://platform_runs/...`` to a manifest path."""
    if not bag_oss_key.startswith("local://"):
        return None
    rel = bag_oss_key[len("local://") :]
    if not (rel.startswith("sources/") or rel.startswith("platform_runs/")):
        return None
    path = oss_key_path(rel)
    return path if path.is_file() else None


def persist_local_media_source(
    *,
    filename: str,
    data: bytes,
    text_schema_id: str | None = None,
) -> dict[str, Any]:
    """Write one local lake source without creating any pipeline rows."""
    kind = classify_source_filename(filename)
    if kind is None or kind == "bag":
        raise ValueError(f"unsupported source file: {filename}")
    if kind == "text" and not (text_schema_id or "").strip():
        raise ValueError("text source requires text_schema_id")

    digest = hashlib.sha256(data).hexdigest()
    source_id = f"sha256:{digest}"
    coll = collection_dir_from_filename(filename)
    storage_dir = _storage_dir_name(coll, digest)
    ext = Path(filename).suffix.lower() or {
        "video": ".mp4",
        "audio": ".wav",
        "text": ".txt",
        "image": ".jpg",
    }.get(kind, "")

    if kind in {"video", "audio", "text"}:
        dest_dir = LOCAL_OSS_ROOT / "sources" / storage_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"{kind}{ext}"
        dest_path = dest_dir / dest_name
        extra_manifest: dict[str, Any] = {}
        if kind == "audio" and ext == ".dat":
            from hmi.local.head_dat import is_head_dat, persist_head_dat_package

            if is_head_dat(data):
                meta = persist_head_dat_package(dest_dir, filename, data)
                dest_name = "audio.wav"
                extra_manifest = {
                    "audio_format": "head_acoustics_hdf_v4",
                    "head_meta": "head_meta.json",
                    "pcm_pa": meta.get("pcm_pa"),
                    "channels": meta.get("channels"),
                }
            else:
                dest_path.write_bytes(data)
        else:
            dest_path.write_bytes(data)
        manifest = {
            "clip_id": source_id,
            "source_name": coll,
            "modalities": [kind],
            "has_preencoded_video": kind == "video",
            "video": dest_name if kind == "video" else None,
            "audio": dest_name if kind == "audio" else None,
            "text": dest_name if kind == "text" else None,
            "video_path": dest_name if kind == "video" else None,
            "audio_path": dest_name if kind == "audio" else None,
            "text_path": dest_name if kind == "text" else None,
            **extra_manifest,
        }
        manifest_path = dest_dir / "source_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        oss_key = f"sources/{storage_dir}/source_manifest.json"
        return {
            "source_id": source_id,
            "kind": kind,
            "filename": filename,
            "text_schema_id": text_schema_id,
            "content_hash": digest,
            "local_oss_key": f"local://{oss_key}",
            "local_path": str(manifest_path),
            "size_bytes": len(data),
        }

    dest_dir = LOCAL_OSS_ROOT / "lake_images" / storage_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"image{ext}"
    dest_path = dest_dir / dest_name
    dest_path.write_bytes(data)
    oss_key = f"lake_images/{storage_dir}/{dest_name}"
    return {
        "source_id": source_id,
        "kind": kind,
        "filename": filename,
        "text_schema_id": text_schema_id,
        "content_hash": digest,
        "local_oss_key": f"local://{oss_key}",
        "local_path": str(dest_path),
        "size_bytes": len(data),
    }
