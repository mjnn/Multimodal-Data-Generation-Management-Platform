#!/usr/bin/env python3
"""Create OSS prefix markers for clip-centric HMI staging bucket layout."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import oss2

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, REPO_ROOT / "hmi" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from hmi.oss_layout import OSS_LAYOUT_MARKERS
from scripts.apply_mc_ddl import load_config


def put_marker(bucket: oss2.Bucket, key: str, body: str) -> None:
    bucket.put_object(key, body.encode("utf-8"), headers={"Content-Type": "text/plain; charset=utf-8"})
    print(f"Created oss://{bucket.bucket_name}/{key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create OSS directory layout markers (staging bucket).")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    settings = require_odps_settings(resolve_cloud_settings(config))
    if not settings["oss_bucket"]:
        raise SystemExit("OSS_BUCKET is required")

    auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
    bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])

    for key, body in OSS_LAYOUT_MARKERS:
        put_marker(bucket, key, body)

    print(f"Layout ready in oss://{settings['oss_bucket']}/ ({len(OSS_LAYOUT_MARKERS)} markers)")


if __name__ == "__main__":
    main()
