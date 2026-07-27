#!/usr/bin/env python3
"""Upload config/oms_label_taxonomy.yaml to OSS bucket root."""

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

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from parse_rosbag import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload OMS label taxonomy YAML to OSS.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    parser.add_argument(
        "--object-key",
        default="config/oms_label_taxonomy.yaml",
        help="OSS object key relative to bucket root",
    )
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    settings = require_odps_settings(resolve_cloud_settings(config))
    if not settings["oss_bucket"]:
        raise SystemExit("OSS_BUCKET is required")

    local_path = PROJECT_ROOT / "config" / "oms_label_taxonomy.yaml"
    if not local_path.is_file():
        raise SystemExit(f"Local file not found: {local_path}")

    auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
    bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])
    bucket.put_object_from_file(
        args.object_key,
        str(local_path),
        headers={"Content-Type": "application/x-yaml"},
    )
    meta = bucket.head_object(args.object_key)
    print(f"Uploaded {local_path} -> oss://{settings['oss_bucket']}/{args.object_key}")
    print(f"OK size={meta.content_length} bytes etag={meta.etag}")


if __name__ == "__main__":
    main()
