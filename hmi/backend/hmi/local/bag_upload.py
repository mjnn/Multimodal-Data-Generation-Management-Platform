"""Save uploaded rosbag into local runtime OSS mirror and register pending SDK run."""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from hmi.data_source import LOCAL_OSS_ROOT, oss_key_path
from hmi.local import pipeline_run as pr


def _utc_ds() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collection_dir_from_filename(filename: str) -> str:
    stem = Path(filename).name
    if stem.lower().endswith(".bag"):
        stem = stem[:-4]
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem).strip("_")
    return slug or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def save_uploaded_rosbag(
    filename: str,
    data: bytes,
    *,
    run_id: str | None = None,
    ds: str | None = None,
    execution_started_at: str | None = None,
) -> dict[str, str | int]:
    if not filename.lower().endswith(".bag"):
        raise ValueError("only .bag files are accepted")
    coll = collection_dir_from_filename(filename)
    dest_dir = LOCAL_OSS_ROOT / "rosbags" / coll
    dest_dir.mkdir(parents=True, exist_ok=True)
    bag_name = Path(filename).name
    bag_path = dest_dir / bag_name
    bag_path.write_bytes(data)

    clip_id = f"sha256:{sha256_file(bag_path)}"
    run_id = run_id or str(uuid.uuid4())
    ds = ds or _utc_ds()
    oss_key = f"rosbags/{coll}/{bag_name}"
    bag_oss_key = f"local://{oss_key}"

    pr.upsert_clip_row(
        clip_id=clip_id,
        clip_dir_name=coll,
        content_hash=clip_id.split(":", 1)[-1][:64],
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
        "size_bytes": len(data),
        "local_path": str(bag_path),
    }


def resolve_local_bag_path(bag_oss_key: str) -> Path | None:
    if not bag_oss_key.startswith("local://"):
        return None
    rel = bag_oss_key[len("local://") :]
    path = oss_key_path(rel)
    return path if path.is_file() else None
