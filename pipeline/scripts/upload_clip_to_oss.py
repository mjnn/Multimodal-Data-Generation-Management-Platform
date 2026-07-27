#!/usr/bin/env python3
"""Upload a local clip rosbag to OSS using the cloud path layout."""

from __future__ import annotations

import argparse
import mimetypes
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

from clip_id import compute_clip_id, write_rosbag_manifest
from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from parse_rosbag import discover_bags, load_config, resolve_path


def upload_file(bucket: oss2.Bucket, local_path: Path, object_key: str) -> None:
    content_type = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
    bucket.put_object_from_file(object_key, str(local_path), headers={"Content-Type": content_type})
    print(f"Uploaded {local_path} -> oss://{bucket.bucket_name}/{object_key}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload local clip rosbag files to OSS.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--clip", required=True, help="Local clip directory name under clips/")
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    project_root = resolve_path(args.config.parent, config.get("project_root", "."))
    settings = require_odps_settings(resolve_cloud_settings(config))
    if not settings["oss_bucket"]:
        raise SystemExit("OSS_BUCKET is required")

    paths_config = config["paths"]
    clips_dir = resolve_path(project_root, paths_config["clips_dir"])
    clip_dir = clips_dir / args.clip
    rosbag_dir = clip_dir / paths_config["rosbag_subdir"]
    if not rosbag_dir.is_dir():
        raise SystemExit(f"Rosbag directory not found: {rosbag_dir}")

    manifest_path = write_rosbag_manifest(rosbag_dir, config["bag"])
    clip_id = compute_clip_id(rosbag_dir, config)
    bag_paths = discover_bags(rosbag_dir, config["bag"])
    if not bag_paths:
        raise SystemExit(f"No bag files found in: {rosbag_dir}")

    auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
    bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])
    data_prefix = settings["oss_data_prefix"].strip("/")
    bag_prefix = f"{data_prefix}/{args.clip}"

    for bag_path in bag_paths:
        object_key = f"{bag_prefix}/{bag_path.name}"
        upload_file(bucket, bag_path, object_key)
        print(f"bag_oss_key={object_key}")

    upload_file(bucket, manifest_path, f"{bag_prefix}/manifest.json")
    print(f"clip_id={clip_id}")
    print(f"Job0 scan_prefix=oss://{settings['oss_bucket']}/{data_prefix}/")


if __name__ == "__main__":
    main()
