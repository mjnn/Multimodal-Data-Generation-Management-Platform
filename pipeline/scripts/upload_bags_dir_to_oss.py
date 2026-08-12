#!/usr/bin/env python3
"""Upload local rosbag folders to OSS under rosbags/{dir_name}/output.bag.

Example:
  py -3.11 pipeline/scripts/upload_bags_dir_to_oss.py \\
    --src C:\\Users\\svw\\Downloads\\0804caiji --limit 4 --prefix rosbags/
"""

from __future__ import annotations

import argparse
import hashlib
import mimetypes
import os
import sys
from pathlib import Path

import oss2

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from clip_id import compute_clip_id, format_clip_id  # noqa: E402
from cloud_config import load_cloud_env  # noqa: E402
from parse_rosbag import load_config  # noqa: E402
from repo_paths import CONFIG_PATH, ENV_PATH  # noqa: E402


def _resolve_cred() -> tuple[str, str]:
    ak = (
        os.environ.get("OSS_ACCESS_KEY_ID")
        or os.environ.get("OSS_VL_ACCESS_KEY_ID")
        or os.environ.get("ODPS_ACCESS_ID")
        or ""
    ).strip()
    sk = (
        os.environ.get("OSS_ACCESS_KEY_SECRET")
        or os.environ.get("OSS_VL_ACCESS_KEY_SECRET")
        or os.environ.get("ODPS_ACCESS_KEY")
        or ""
    ).strip()
    if not ak or not sk:
        raise SystemExit(
            "Missing OSS/ODPS credentials in env "
            "(ODPS_ACCESS_ID/ODPS_ACCESS_KEY or OSS_*/OSS_VL_*)"
        )
    return ak, sk


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.name.encode("utf-8"))
    with path.open("rb") as fh:
        while True:
            block = fh.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)
    return hasher.hexdigest()


def discover_bag_dirs(src: Path) -> list[tuple[Path, Path]]:
    """Return (clip_dir, bag_path) sorted by folder name ascending."""
    found: list[tuple[Path, Path]] = []
    for child in sorted(src.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        bag = child / "output.bag"
        if bag.is_file():
            found.append((child, bag))
    return found


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload local bag folders to OSS rosbags/{dir}/output.bag"
    )
    parser.add_argument("--src", type=Path, required=True, help="Parent dir of bag folders")
    parser.add_argument("--limit", type=int, default=0, help="Max bags (0=all)")
    parser.add_argument("--prefix", default="rosbags/", help="OSS key prefix")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing keys (default: skip if same size)",
    )
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--bag-name", default="output.bag")
    args = parser.parse_args()

    env_path = args.env_file or ENV_PATH
    alt = PIPELINE_ROOT / "local_sdk_mc_test" / ".env"
    load_cloud_env(env_path if env_path.is_file() else None)
    if alt.is_file() and not os.environ.get("OSS_BUCKET"):
        load_cloud_env(alt)

    bucket_name = (os.environ.get("OSS_BUCKET") or os.environ.get("MC_OSS_BUCKET") or "").strip()
    endpoint = (
        os.environ.get("OSS_ENDPOINT")
        or os.environ.get("MC_OSS_ENDPOINT")
        or "https://oss-cn-shanghai.aliyuncs.com"
    ).strip()
    if not bucket_name:
        raise SystemExit("OSS_BUCKET is required in .env")

    src = args.src.resolve()
    if not src.is_dir():
        raise SystemExit(f"Source dir not found: {src}")

    prefix = args.prefix.strip().strip("/")
    bags = discover_bag_dirs(src)
    if args.limit and args.limit > 0:
        bags = bags[: args.limit]
    if not bags:
        raise SystemExit(f"No {args.bag_name} found under {src}")

    config = load_config(args.config.resolve()) if args.config.is_file() else {"cloud": {"clip_id": {}}, "bag": {}}
    ak, sk = _resolve_cred()
    auth = oss2.Auth(ak, sk)
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    print(f"bucket={bucket_name}")
    print(f"endpoint={endpoint}")
    print(f"src={src}")
    print(f"prefix={prefix}/  count={len(bags)}")
    print("-" * 88)
    print(f"{'local_dir':<24} {'bag_oss_key':<48} {'size_mb':>8}  clip_id")
    print("-" * 88)

    results: list[dict[str, str]] = []
    for clip_dir, bag_path in bags:
        key = f"{prefix}/{clip_dir.name}/{args.bag_name}"
        size = bag_path.stat().st_size
        size_mb = size / (1024 * 1024)
        try:
            clip_id = compute_clip_id(clip_dir, config)
        except Exception:
            clip_id = format_clip_id(_sha256_file(bag_path), config.get("cloud", {}).get("clip_id", {}))

        action = "upload"
        if bucket.object_exists(key):
            meta = bucket.get_object_meta(key)
            remote_size = int(meta.headers.get("Content-Length") or 0)
            if not args.overwrite and remote_size == size:
                action = "skip_same_size"
            else:
                action = "overwrite" if args.overwrite or remote_size != size else "skip_same_size"

        if action.startswith("skip"):
            print(
                f"{clip_dir.name:<24} {key:<48} {size_mb:8.2f}  {clip_id}  [{action}]"
            )
        else:
            content_type = mimetypes.guess_type(bag_path.name)[0] or "application/octet-stream"
            bucket.put_object_from_file(
                key, str(bag_path), headers={"Content-Type": content_type}
            )
            print(
                f"{clip_dir.name:<24} {key:<48} {size_mb:8.2f}  {clip_id}  [{action}]"
            )

        # Verify head
        if not bucket.object_exists(key):
            raise SystemExit(f"VERIFY_FAIL missing after upload: {key}")
        meta = bucket.get_object_meta(key)
        remote_size = int(meta.headers.get("Content-Length") or 0)
        if remote_size != size:
            raise SystemExit(
                f"VERIFY_FAIL size mismatch key={key} local={size} remote={remote_size}"
            )

        results.append(
            {
                "local_dir": clip_dir.name,
                "bag_oss_key": key,
                "size_bytes": str(size),
                "size_mb": f"{size_mb:.2f}",
                "clip_id": clip_id,
                "action": action,
            }
        )

    print("-" * 88)
    print(f"OK uploaded_or_verified={len(results)} bucket={bucket_name}")
    for r in results:
        print(
            f"VERIFY_OK key={r['bag_oss_key']} size_mb={r['size_mb']} clip_id={r['clip_id']}"
        )


if __name__ == "__main__":
    main()
