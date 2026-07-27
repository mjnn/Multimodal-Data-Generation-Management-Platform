#!/usr/bin/env python3
"""Add bag_oss_key column to aig_rosbag__dim_clip if missing."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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

TABLE = "aig_rosbag__dim_clip"
ALTER_SQL = (
    "ALTER TABLE aig_rosbag__dim_clip ADD COLUMNS "
    "(bag_oss_key STRING COMMENT 'bag OSS object key; Job0/Job1 same path')"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    settings = require_odps_settings(resolve_cloud_settings(config))

    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )

    table = odps.get_table(TABLE)
    columns = {col.name for col in table.table_schema.columns}
    print(f"Project: {settings['odps_project']}")
    print(f"Table {TABLE} columns: {sorted(columns)}")

    if "bag_oss_key" in columns:
        print("bag_oss_key already exists; nothing to do.")
        return

    if args.dry_run:
        print(f"Would execute: {ALTER_SQL}")
        return

    print(f"Executing: {ALTER_SQL}")
    instance = odps.execute_sql(ALTER_SQL)
    instance.wait_for_success()
    table = odps.get_table(TABLE)
    columns = [col.name for col in table.table_schema.columns]
    print(f"Done. Columns now: {columns}")


if __name__ == "__main__":
    main()
