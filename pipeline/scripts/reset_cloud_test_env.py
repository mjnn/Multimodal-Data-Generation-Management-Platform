#!/usr/bin/env python3
"""Reset OSS + MaxCompute to a clean E2E test baseline.

OSS after reset (default):
  - rosbags/: **all objects kept** (every bag under scan prefix)
  - clips/: empty (optional layout .keep marker)
  - pipeline/: dispatch manifest cleared (e.g. pipeline/dispatch/latest.json)
  - config/: unchanged by default (keeps oms_label_taxonomy.yaml)

MC after reset:
  - All aig_rosbag__* tables remain; rows / partitions cleared.

Usage:
  python scripts/reset_cloud_test_env.py --dry-run
  python scripts/reset_cloud_test_env.py --yes
  python scripts/reset_cloud_test_env.py --yes --no-keep-taxonomy
  python scripts/reset_cloud_test_env.py --yes --purge-other-rosbags --keep-bag-key rosbags/foo/output.bag
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import oss2
from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from scripts.apply_mc_ddl import load_config

DEFAULT_KEEP_BAG_KEYS = [
    "rosbags/2026-06-05_13-27-07/output.bag",
]
DEFAULT_KEEP_CONFIG_KEYS = [
    "config/oms_label_taxonomy.yaml",
]
DEFAULT_PIPELINE_PREFIX = "pipeline"
MARKER_BODY = b"# rosbag pipeline layout marker\n"

MC_TABLE_SUFFIXES = [
    "dim_clip",
    "pipeline_run",
    "pipeline_step",
    "fact_message_timeline",
    "fact_frame",
    "fact_audio_chunk",
    "fact_event",
    "clip_parse_summary",
    "fact_sample_policy",
    "fact_sample_sync_group",
    "fact_audio_segment",
    "fact_image_label",
    "fact_embedding",
]


def _table_names(prefix: str) -> list[str]:
    return [f"{prefix}{suffix}" for suffix in MC_TABLE_SUFFIXES]


def _list_object_keys(bucket: oss2.Bucket, prefix: str) -> list[str]:
    normalized = prefix.strip("/")
    scan_prefix = f"{normalized}/" if normalized else ""
    return [obj.key for obj in oss2.ObjectIterator(bucket, prefix=scan_prefix)]


def _delete_keys(bucket: oss2.Bucket, keys: list[str], *, dry_run: bool, verbose: bool) -> int:
    if not keys:
        return 0
    if dry_run:
        if verbose:
            for key in keys:
                print(f"[dry-run] delete oss://{bucket.bucket_name}/{key}")
        return len(keys)

    deleted = 0
    batch_size = 1000
    for start in range(0, len(keys), batch_size):
        batch = keys[start : start + batch_size]
        result = bucket.batch_delete_objects(batch)
        deleted_keys = list(result.deleted_keys)
        deleted += len(deleted_keys)
        delete_errors = getattr(result, "delete_errors", None)
        if delete_errors:
            for error in delete_errors:
                print(
                    f"WARN: failed to delete {error.key}: {error.code} {error.message}",
                    file=sys.stderr,
                )
        elif len(deleted_keys) < len(batch):
            for key in sorted(set(batch) - set(deleted_keys)):
                print(f"WARN: failed to delete {key}", file=sys.stderr)
    return deleted


def reset_oss(
    bucket: oss2.Bucket,
    *,
    data_prefix: str,
    clips_zone_prefix: str,
    pipeline_prefix: str,
    keep_bag_keys: set[str],
    keep_config_keys: set[str],
    keep_all_rosbags: bool,
    keep_taxonomy: bool,
    recreate_markers: bool,
    dry_run: bool,
    verbose: bool,
) -> None:
    data_prefix = data_prefix.strip("/")
    clips_prefix = clips_zone_prefix.strip("/")
    pipeline_prefix = pipeline_prefix.strip("/")

    rosbag_keys = _list_object_keys(bucket, data_prefix)
    clips_keys = _list_object_keys(bucket, clips_prefix) if clips_prefix else []
    pipeline_keys = _list_object_keys(bucket, pipeline_prefix) if pipeline_prefix else []

    config_keys: list[str] = []
    if not keep_taxonomy:
        config_keys = _list_object_keys(bucket, "config")

    to_delete: list[str] = []
    for key in rosbag_keys:
        if keep_all_rosbags:
            continue
        if key in keep_bag_keys:
            continue
        to_delete.append(key)
    for key in clips_keys + pipeline_keys + config_keys:
        if key in keep_config_keys:
            continue
        to_delete.append(key)

    print(
        f"OSS: scan rosbags/*={len(rosbag_keys)} clips/*={len(clips_keys)} "
        f"pipeline/*={len(pipeline_keys)} delete={len(to_delete)}"
    )
    if keep_all_rosbags:
        print(f"OSS: keep all {len(rosbag_keys)} object(s) under {data_prefix}/")
    deleted = _delete_keys(bucket, to_delete, dry_run=dry_run, verbose=verbose)
    print(f"OSS: deleted {deleted} object(s)")

    if recreate_markers:
        markers = [
            f"{data_prefix}/.keep",
            f"{clips_prefix}/.keep" if clips_prefix else "",
        ]
        for key in markers:
            if not key:
                continue
            if dry_run:
                print(f"[dry-run] put marker oss://{bucket.bucket_name}/{key}")
            else:
                bucket.put_object(key, MARKER_BODY, headers={"Content-Type": "text/plain"})
                print(f"OSS: marker oss://{bucket.bucket_name}/{key}")

    if not keep_all_rosbags:
        for key in sorted(keep_bag_keys | (keep_config_keys if keep_taxonomy else set())):
            if dry_run:
                print(f"OSS: keep oss://{bucket.bucket_name}/{key}")
            elif bucket.object_exists(key):
                print(f"OSS: keep oss://{bucket.bucket_name}/{key}")
            else:
                print(f"OSS: MISSING keep key oss://{bucket.bucket_name}/{key}", file=sys.stderr)
    elif keep_taxonomy:
        for key in sorted(keep_config_keys):
            if bucket.object_exists(key):
                print(f"OSS: keep oss://{bucket.bucket_name}/{key}")
            else:
                print(f"OSS: MISSING config key oss://{bucket.bucket_name}/{key}", file=sys.stderr)

def _partition_spec_for_drop(part_name: str) -> str:
    part_name = part_name.strip()
    if part_name.count("=") != 1:
        return part_name
    key, value = part_name.split("=", 1)
    value = value.strip().strip("'").strip('"')
    safe_value = value.replace("'", "''")
    return f"{key}='{safe_value}'"


def reset_mc(odps: ODPS, table_names: list[str], *, dry_run: bool, verbose: bool) -> None:
    for table_name in table_names:
        if not odps.exist_table(table_name):
            print(f"MC: skip missing table {table_name}")
            continue

        table = odps.get_table(table_name)
        schema = table.table_schema
        if schema.partitions:
            parts = list(table.partitions)
            if not parts:
                print(f"MC: {table_name} (no partitions)")
                continue
            print(f"MC: {table_name} drop {len(parts)} partition(s)")
            for part in parts:
                drop_sql = (
                    f"ALTER TABLE {table_name} DROP IF EXISTS PARTITION ({_partition_spec_for_drop(part.name)})"
                )
                if dry_run and verbose:
                    print(f"[dry-run] {drop_sql}")
                elif dry_run:
                    pass
                else:
                    instance = odps.execute_sql(drop_sql)
                    instance.wait_for_success()
        else:
            sql = f"TRUNCATE TABLE {table_name}"
            if dry_run and verbose:
                print(f"[dry-run] {sql}")
            elif not dry_run:
                instance = odps.execute_sql(sql)
                instance.wait_for_success()
            action = "would truncate" if dry_run else "truncated"
            print(f"MC: {action} {table_name}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reset OSS pipeline artifacts and clear MaxCompute aig_rosbag__ table data."
    )
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    parser.add_argument(
        "--keep-bag-key",
        action="append",
        dest="keep_bag_keys",
        help="With --purge-other-rosbags: OSS bag keys to keep (repeatable)",
    )
    parser.add_argument(
        "--purge-other-rosbags",
        action="store_true",
        help="Delete rosbag objects not listed in --keep-bag-key (default: keep entire rosbags/ prefix)",
    )
    parser.add_argument(
        "--keep-taxonomy",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Keep config/oms_label_taxonomy.yaml (default: true)",
    )
    parser.add_argument("--oss-only", action="store_true", help="Only reset OSS")
    parser.add_argument("--mc-only", action="store_true", help="Only reset MaxCompute")
    parser.add_argument(
        "--no-markers",
        action="store_true",
        help="Do not recreate rosbags/.keep and clips/.keep markers",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print actions without executing")
    parser.add_argument("--verbose", action="store_true", help="Print every OSS/SQL action (dry-run)")
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    if args.oss_only and args.mc_only:
        raise SystemExit("Use at most one of --oss-only and --mc-only")

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    settings = require_odps_settings(resolve_cloud_settings(config))
    if not settings["oss_bucket"]:
        raise SystemExit("OSS_BUCKET is required")

    keep_all_rosbags = not args.purge_other_rosbags
    if args.purge_other_rosbags:
        keep_bag_keys = set(args.keep_bag_keys) if args.keep_bag_keys else set(DEFAULT_KEEP_BAG_KEYS)
    else:
        keep_bag_keys = set(args.keep_bag_keys or [])
    keep_config_keys = set(DEFAULT_KEEP_CONFIG_KEYS) if args.keep_taxonomy else set()

    data_prefix = settings["oss_data_prefix"].strip("/") or "rosbags"
    clips_zone = settings["oss_prefix_template"].format(clip_id="").strip("/") or "clips"
    pipeline_prefix = DEFAULT_PIPELINE_PREFIX
    table_prefix = settings["table_prefix"] or "aig_rosbag__"
    table_names = _table_names(table_prefix)

    print("=== Reset plan ===")
    print(f"project={settings['odps_project']} bucket={settings['oss_bucket']}")
    if not args.mc_only:
        if keep_all_rosbags:
            print(f"OSS delete: {clips_zone}/* + {pipeline_prefix}/* (keep all {data_prefix}/*)")
        else:
            print(f"OSS delete: {data_prefix}/* (except keep) + {clips_zone}/* + {pipeline_prefix}/*")
            print(f"OSS keep bags: {sorted(keep_bag_keys)}")
        if args.keep_taxonomy:
            print(f"OSS keep config: {sorted(keep_config_keys)}")
    if not args.oss_only:
        print(f"MC clear: {len(table_names)} tables")

    if not args.yes and not args.dry_run:
        answer = input("Type 'reset' to continue: ").strip()
        if answer != "reset":
            raise SystemExit("Aborted.")

    if not args.mc_only:
        auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
        bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])
        reset_oss(
            bucket,
            data_prefix=data_prefix,
            clips_zone_prefix=clips_zone,
            pipeline_prefix=pipeline_prefix,
            keep_bag_keys=keep_bag_keys,
            keep_config_keys=keep_config_keys,
            keep_all_rosbags=keep_all_rosbags,
            keep_taxonomy=args.keep_taxonomy,
            recreate_markers=not args.no_markers,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

    if not args.oss_only:
        odps = ODPS(
            settings["odps_access_id"],
            settings["odps_access_key"],
            project=settings["odps_project"],
            endpoint=settings["odps_endpoint"],
        )
        reset_mc(odps, table_names, dry_run=args.dry_run, verbose=args.verbose)

    print("Done. Next: Job0 discover -> full workflow (run_id empty on Job1).")


if __name__ == "__main__":
    main()
