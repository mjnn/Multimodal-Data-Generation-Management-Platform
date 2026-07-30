"""Sync simulated local OSS clip run → runtime artifacts + SQLite ingest."""

from __future__ import annotations

import shutil
from pathlib import Path

from hmi.data_source import artifacts_dir
from hmi.db import cache_clear
from hmi.local.oss_publish import clip_run_oss_dir, read_local_dispatch_manifest
from hmi.local import store
from hmi.sdk_ingest import ingest_sdk_run_local, sdk_bundle_present


def sync_runtime_from_local_oss(clip_id: str, run_id: str, *, ds: str | None = None) -> dict[str, int | bool]:
    """Copy oss/clips/.../runs/{run_id}/ into artifacts and ingest SDK bundle into hmi.db."""
    store.ensure_db()
    src = clip_run_oss_dir(clip_id, run_id)
    if not src.is_dir():
        raise FileNotFoundError(f"local OSS run missing: {src}")

    dest = artifacts_dir(clip_id, run_id)
    if dest.is_dir():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)

    copied = 0
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        copied += 1

    if ds is None:
        row = store.query_one(
            "SELECT ds FROM pipeline_run WHERE clip_id=? AND run_id=? ORDER BY ds DESC LIMIT 1",
            (clip_id, run_id),
        )
        ds = str(row["ds"]) if row and row.get("ds") else None
    if not ds:
        manifest = read_local_dispatch_manifest()
        if manifest and str(manifest.get("run_id")) == run_id:
            raw_ds = manifest.get("ds")
            if raw_ds:
                ds = str(raw_ds)
    if not ds:
        from datetime import datetime, timezone

        ds = datetime.now(timezone.utc).strftime("%Y%m%d")

    ingested: dict[str, bool] = {}
    if sdk_bundle_present(clip_id, run_id):
        ingested = ingest_sdk_run_local(clip_id, run_id, ds)

    store.set_meta("last_clip_id", clip_id)
    store.set_meta("last_run_id", run_id)
    store.set_meta("last_ds", ds)
    store.set_meta("last_sync_oss_files", str(copied))
    cache_clear()
    return {"files": copied, **ingested}
