#!/usr/bin/env python3
"""Upload SDK v1 clip run bundle to OSS (jsonl + preview/, no v2 parsed/aligned/ai).

Usage:
  py -3 scripts/upload_clip_preview_to_oss.py --clip-id sha256:... --run-id <uuid>
  py -3 scripts/upload_clip_preview_to_oss.py --all-real
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import oss2

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, resolve_cloud_settings
from hmi.data_source import artifacts_dir
from hmi.local import store
from hmi.media.preview_manifest import MANIFEST_REL
from hmi.oss_layout import (
    SDK_EMBEDDINGS_JSONL,
    SDK_LABELS_JSONL,
    SDK_RUN_JSON_KEY,
    SDK_VIDEOS_JSONL,
)

REAL_DATA_BAG_OSS_PREFIX = "local://real_data/"

UPLOAD_PREFIXES = (
    SDK_RUN_JSON_KEY,
    SDK_LABELS_JSONL,
    SDK_EMBEDDINGS_JSONL,
    SDK_VIDEOS_JSONL,
    "preview/",
)


def _run_prefix(settings: dict[str, str], clip_id: str, run_id: str) -> str:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs_subdir}/"


def _upload_tree(bucket: oss2.Bucket, local_run: Path, oss_prefix: str) -> int:
    count = 0
    for rel_prefix in UPLOAD_PREFIXES:
        base = local_run / rel_prefix
        if rel_prefix.endswith("/"):
            if not base.is_dir():
                continue
            for path in base.rglob("*"):
                if not path.is_file():
                    continue
                rel = path.relative_to(local_run).as_posix()
                key = f"{oss_prefix}{rel}"
                bucket.put_object_from_file(key, str(path))
                count += 1
        else:
            if base.is_file():
                key = f"{oss_prefix}{rel_prefix}"
                bucket.put_object_from_file(key, str(base))
                count += 1
    return count


def main() -> int:
    load_cloud_env()
    settings = resolve_cloud_settings()
    auth = oss2.Auth(settings["oss_access_key_id"], settings["oss_access_key_secret"])
    bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])

    parser = argparse.ArgumentParser(description="Upload SDK v1 clip bundle to OSS")
    parser.add_argument("--clip-id")
    parser.add_argument("--run-id")
    parser.add_argument(
        "--all-real",
        action="store_true",
        help="All dim_clip rows with bag_oss_key under local://real_data/",
    )
    args = parser.parse_args()

    targets: list[tuple[str, str]] = []
    if args.all_real:
        for row in store.query(
            "SELECT clip_id, active_run_id FROM dim_clip WHERE bag_oss_key LIKE ?",
            (f"{REAL_DATA_BAG_OSS_PREFIX}%",),
        ):
            cid = str(row["clip_id"])
            rid = str(row.get("active_run_id") or "")
            if rid:
                targets.append((cid, rid))
    elif args.clip_id and args.run_id:
        targets.append((args.clip_id.strip(), args.run_id.strip()))
    else:
        parser.error("provide --clip-id and --run-id, or --all-real")

    total = 0
    for clip_id, run_id in targets:
        local_run = artifacts_dir(clip_id, run_id)
        manifest = local_run / MANIFEST_REL
        if not manifest.is_file():
            print(f"SKIP {clip_id}: no {MANIFEST_REL} (re-import with --preview-mode mp4)")
            continue
        prefix = _run_prefix(settings, clip_id, run_id)
        n = _upload_tree(bucket, local_run, prefix)
        print(f"OK {clip_id} run={run_id[:8]}… files={n} → oss://{settings['oss_bucket']}/{prefix}")
        total += n
    print(f"Uploaded {total} object(s)")
    return 0 if total else 1


if __name__ == "__main__":
    raise SystemExit(main())
