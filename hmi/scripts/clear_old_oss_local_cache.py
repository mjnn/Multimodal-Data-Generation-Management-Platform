#!/usr/bin/env python3
"""Clear local HMI cache synced from legacy OSS bucket (rosbags/ keys)."""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH
PROJECT_ROOT = HMI_ROOT
BACKEND_ROOT = BACKEND
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from hmi.data_source import LOCAL_ARTIFACTS_ROOT, LOCAL_DB_PATH, safe_clip_dir
from hmi.services.pipeline_status import bag_pipeline_cache_clear

APP_DB_PATH = PROJECT_ROOT / "data" / "app.db"

# Keys written by sync_hmi_local.py and oss_sync_poller.py
SYNC_META_KEYS = (
    "last_clip_id",
    "last_run_id",
    "last_ds",
    "last_sync_rows",
    "last_sync_oss_files",
    "poll_last_fingerprint",
    "poll_last_sync_status",
    "poll_last_sync_at",
    "poll_last_error",
    "poll_last_clip_id",
    "poll_last_run_id",
)

FACT_TABLES = (
    "pipeline_run",
    "clip_parse_summary",
    "fact_frame",
    "fact_event",
    "fact_audio_segment",
    "fact_image_label",
    "fact_embedding",
    "fact_clip_label",
    "fact_clip_embedding",
    "fact_sample_sync_group",
    "fact_message_timeline",
    "fact_audio_chunk",
    "fact_sample_policy",
)


def _legacy_oss_clip_ids(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT clip_id, bag_oss_key FROM dim_clip WHERE bag_oss_key IS NOT NULL AND bag_oss_key != ''"
    ).fetchall()
    out: list[str] = []
    for clip_id, bag_key in rows:
        key = str(bag_key or "").strip()
        # Legacy bucket sync uses relative rosbags/... keys (not demo oss:// URIs).
        if key.startswith("rosbags/"):
            out.append(str(clip_id))
    return out


def _delete_clip_rows(conn: sqlite3.Connection, clip_id: str) -> None:
    run_rows = conn.execute(
        "SELECT run_id, ds FROM pipeline_run WHERE clip_id=?", (clip_id,)
    ).fetchall()
    for run_id, ds in run_rows:
        conn.execute("DELETE FROM pipeline_step WHERE run_id=? AND ds=?", (run_id, ds))
    for tbl in FACT_TABLES:
        try:
            conn.execute(f"DELETE FROM {tbl} WHERE clip_id=?", (clip_id,))
        except sqlite3.OperationalError:
            pass
    conn.execute("DELETE FROM dim_clip WHERE clip_id=?", (clip_id,))


def _delete_artifacts(clip_id: str) -> Path | None:
    clip_dir = LOCAL_ARTIFACTS_ROOT / "clips" / safe_clip_dir(clip_id)
    if clip_dir.is_dir():
        shutil.rmtree(clip_dir)
        return clip_dir
    return None


def _clear_sync_meta(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        f"DELETE FROM sync_meta WHERE key IN ({','.join('?' for _ in SYNC_META_KEYS)})",
        SYNC_META_KEYS,
    )
    return cur.rowcount


def _clear_app_db(clip_ids: list[str]) -> tuple[int, int]:
    if not APP_DB_PATH.is_file() or not clip_ids:
        return 0, 0
    conn = sqlite3.connect(APP_DB_PATH)
    try:
        placeholders = ",".join("?" for _ in clip_ids)
        review_cur = conn.execute(
            f"DELETE FROM clip_label_review WHERE clip_id IN ({placeholders})",
            clip_ids,
        )
        ds_cur = conn.execute(
            """
            UPDATE dataset_snapshot
            SET oss_x_uri = NULL, oss_y_uri = NULL, oss_manifest_uri = NULL
            WHERE oss_x_uri IS NOT NULL OR oss_y_uri IS NOT NULL OR oss_manifest_uri IS NOT NULL
            """
        )
        conn.commit()
        return review_cur.rowcount, ds_cur.rowcount
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear local cache from legacy OSS bucket sync.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not LOCAL_DB_PATH.is_file():
        print("No local HMI db; nothing to clear.")
        return 0

    conn = sqlite3.connect(LOCAL_DB_PATH)
    try:
        clip_ids = _legacy_oss_clip_ids(conn)
        if not clip_ids:
            print("No legacy OSS clips (rosbags/*) in local cache.")
            return 0

        print(f"Legacy OSS clips to remove: {len(clip_ids)}")
        for clip_id in clip_ids:
            row = conn.execute(
                "SELECT bag_oss_key FROM dim_clip WHERE clip_id=?", (clip_id,)
            ).fetchone()
            print(f"  - {clip_id}  ({row[0] if row else ''})")

        if args.dry_run:
            print("[dry-run] skipped deletions")
            return 0

        removed_dirs: list[Path] = []
        for clip_id in clip_ids:
            _delete_clip_rows(conn, clip_id)
            deleted = _delete_artifacts(clip_id)
            if deleted:
                removed_dirs.append(deleted)

        meta_deleted = _clear_sync_meta(conn)
        conn.commit()
    finally:
        conn.close()

    reviews_deleted, datasets_cleared = _clear_app_db(clip_ids)
    bag_pipeline_cache_clear()

    print(f"Removed {len(clip_ids)} clip(s) from hmi.db")
    print(f"Removed {len(removed_dirs)} artifact tree(s)")
    print(f"Cleared {meta_deleted} sync_meta key(s)")
    print(f"Deleted {reviews_deleted} review row(s) from app.db")
    print(f"Cleared OSS export URIs on {datasets_cleared} dataset snapshot(s)")
    print("Done. Restart HMI backend if it is running.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
