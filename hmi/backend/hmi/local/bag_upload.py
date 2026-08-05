"""Save uploaded rosbag into local runtime OSS mirror and register pending SDK run.

设计要点（多 bag / 文件夹上传）：
1. ``clip_id = sha256:{content}`` — 按文件内容哈希，同名不同内容会得到不同 clip。
2. 磁盘路径 ``rosbags/{collection}__{hash12}/{basename}.bag`` — 避免浏览器只给
   basename（如多个 ``output.bag``）时互相覆盖；否则会出现「clip_id 不同但 SDK
   读到的是同一个被覆盖的 bag」。
3. ``clip_dir_name`` 仍用短展示名（嵌套路径取父目录，如时间戳文件夹名），供 UI 显示。
4. 同一执行批次可共用 ``run_id``（见 ``pipeline_execution.enqueue_rosbags_batch``）。
"""

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
    """Stream-hash a bag on disk (large files friendly)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collection_dir_from_filename(filename: str) -> str:
    """Derive a short display / storage stem from an upload name.

    Nested paths from folder upload (e.g. ``0804caiji/20250804_120000/output.bag``)
    use the **parent folder** name so timestamp directories stay distinguishable when
    every bag is named ``output.bag``.
    Flat uploads (``output.bag``) still use the file stem.
    """
    normalized = filename.replace("\\", "/").strip("/")
    parts = [p for p in normalized.split("/") if p and p not in (".", "..")]
    label = ""
    if len(parts) >= 2:
        # .../<parent>/<file.bag> → parent (采集时间戳目录)
        label = parts[-2]
    elif parts:
        label = parts[-1]
        if label.lower().endswith(".bag"):
            label = label[:-4]
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", label).strip("_")
    return slug or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def bag_storage_dir_name(filename: str, content_sha256: str) -> str:
    """Unique OSS folder per bag content: ``{collection}__{sha256[:12]}``.

    Browser multi-upload only exposes basename (e.g. many ``output.bag``). Storing
    under ``rosbags/{stem}/`` alone overwrites earlier files so later SDK jobs all
    read the last bag while clip_ids (hashed at upload) stay distinct.
    """
    coll = collection_dir_from_filename(filename)
    digest = content_sha256.strip().lower()
    if len(digest) < 12:
        raise ValueError("content_sha256 too short")
    return f"{coll}__{digest[:12]}"


def save_uploaded_rosbag(
    filename: str,
    data: bytes,
    *,
    run_id: str | None = None,
    ds: str | None = None,
    execution_started_at: str | None = None,
) -> dict[str, str | int]:
    """Write bag bytes under unique local OSS path and enqueue SDK pipeline rows.

    ``filename`` may be a basename or a relative path from folder upload
    (``root/ts_dir/xxx.bag``); only the basename is kept on disk, uniqueness comes
    from ``storage_dir``.
    """
    if not filename.lower().endswith(".bag"):
        raise ValueError("only .bag files are accepted")
    # 磁盘上的文件名只用 basename；相对路径仅用于 collection / 展示命名
    bag_name = Path(filename).name
    digest = hashlib.sha256(data).hexdigest()
    clip_id = f"sha256:{digest}"
    coll = collection_dir_from_filename(filename)
    storage_dir = bag_storage_dir_name(filename, digest)
    dest_dir = LOCAL_OSS_ROOT / "rosbags" / storage_dir
    dest_dir.mkdir(parents=True, exist_ok=True)
    bag_path = dest_dir / bag_name
    bag_path.write_bytes(data)

    run_id = run_id or str(uuid.uuid4())
    ds = ds or _utc_ds()
    oss_key = f"rosbags/{storage_dir}/{bag_name}"
    # local:// 前缀供 resolve_local_bag_path / SDK worker 解析到磁盘
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
    # 上传落盘即视为 discover 完成，后续由 local_sdk_worker 认领 sdk_infer
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
    """Map ``local://rosbags/...`` to an absolute file under LOCAL_OSS_ROOT."""
    if not bag_oss_key.startswith("local://"):
        return None
    rel = bag_oss_key[len("local://") :]
    path = oss_key_path(rel)
    return path if path.is_file() else None
