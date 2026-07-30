"""SDK 存储后端：local（磁盘 + 可选 HMI runtime）| cloud（OSS）。"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Literal

StorageBackend = Literal["local", "cloud"]


def storage_backend_from_env() -> StorageBackend:
    raw = os.getenv("STORAGE_BACKEND", "local").strip().lower()
    return "cloud" if raw == "cloud" else "local"


def resolve_runtime_root() -> Path:
    env = os.getenv("HMI_RUNTIME_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    here = Path(__file__).resolve()
    # piplinesdk/oms_multimodal/storage_backend.py -> repo root
    repo = here.parents[3]
    return (repo / "hmi" / "data" / "hmi_runtime").resolve()


def ensure_local_oss_layout(root: Path) -> Path:
    oss = root / "oss"
    for sub in ("rosbags", "clips", "pipeline", "config"):
        (oss / sub).mkdir(parents=True, exist_ok=True)
    return oss


def mirror_outputs_to_local_runtime(
    *,
    run_dir: Path,
    clip_id: str,
    run_id: str,
) -> Path:
    """Copy SDK jsonl + work/ tree into hmi_runtime/oss/clips/…"""
    root = resolve_runtime_root()
    oss = ensure_local_oss_layout(root)
    dest = oss / "clips" / clip_id.replace(":", "__") / "runs" / run_id
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("labels.jsonl", "fusion_embeddings.jsonl", "clip_videos.jsonl"):
        src = run_dir / name
        if src.is_file():
            shutil.copy2(src, dest / name)
    work = run_dir / "work"
    if work.is_dir():
        target_work = dest / "work"
        if target_work.exists():
            shutil.rmtree(target_work)
        shutil.copytree(work, target_work)
    return dest


def upload_run_dir_to_oss(
    run_dir: Path,
    *,
    clip_id: str,
    run_id: str,
    bucket: str | None = None,
    endpoint: str | None = None,
) -> str:
    """Upload run artifacts to OSS (online storage backend)."""
    try:
        import oss2
    except ImportError as exc:
        raise RuntimeError("cloud storage requires oss2; pip install oss2") from exc

    bucket_name = bucket or os.getenv("OSS_BUCKET", "").strip()
    endpoint_url = endpoint or os.getenv("OSS_ENDPOINT", "").strip()
    access_id = os.getenv("ODPS_ACCESS_ID") or os.getenv("OSS_ACCESS_KEY_ID") or ""
    access_key = os.getenv("ODPS_ACCESS_KEY") or os.getenv("OSS_ACCESS_KEY_SECRET") or ""
    if not bucket_name or not endpoint_url or not access_id or not access_key:
        raise RuntimeError("OSS_BUCKET, OSS_ENDPOINT, and ODPS_ACCESS_ID/KEY required for STORAGE_BACKEND=cloud")

    auth = oss2.Auth(access_id, access_key)
    bucket_obj = oss2.Bucket(auth, endpoint_url, bucket_name)
    prefix = f"clips/{clip_id}/runs/{run_id}/"
    uploaded = 0
    for path in run_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(run_dir).as_posix()
        bucket_obj.put_object_from_file(prefix + rel, str(path))
        uploaded += 1
    return f"oss://{bucket_name}/{prefix} ({uploaded} objects)"
