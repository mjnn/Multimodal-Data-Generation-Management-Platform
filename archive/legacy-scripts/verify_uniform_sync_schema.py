#!/usr/bin/env python3
"""Verify uniform_sync MC schema (fact_sample_sync_group + fact_image_label columns)."""

from __future__ import annotations

import sys
from pathlib import Path

from odps import ODPS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from scripts.apply_mc_ddl import load_config

REQUIRED_SYNC_GROUP_COLS = {
    "clip_id",
    "run_id",
    "sync_group_id",
    "anchor_timestamp_ns",
    "sample_policy",
    "align_window_ms",
    "frame_ids_json",
    "created_at",
    "ds",
}
REQUIRED_LABEL_COLS = {
    "sync_group_id",
    "anchor_timestamp_ns",
    "label_scope",
}


def main() -> int:
    load_cloud_env()
    settings = require_odps_settings(resolve_cloud_settings(load_config(PROJECT_ROOT / "config.yaml")))
    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )
    prefix = settings["table_prefix"] or "aig_rosbag__"

    sync_table = f"{prefix}fact_sample_sync_group"
    label_table = f"{prefix}fact_image_label"
    failures: list[str] = []

    if not odps.exist_table(sync_table):
        failures.append(f"missing table {sync_table}")
    else:
        cols = {c.name for c in odps.get_table(sync_table).table_schema.columns}
        missing = REQUIRED_SYNC_GROUP_COLS - cols
        if missing:
            failures.append(f"{sync_table} missing columns: {sorted(missing)}")
        else:
            print(f"OK: {sync_table} columns present")

    if not odps.exist_table(label_table):
        failures.append(f"missing table {label_table}")
    else:
        cols = {c.name for c in odps.get_table(label_table).table_schema.columns}
        missing = REQUIRED_LABEL_COLS - cols
        if missing:
            failures.append(f"{label_table} missing columns: {sorted(missing)}")
        else:
            print(f"OK: {label_table} sync columns present")

    if failures:
        for item in failures:
            print(f"FAIL: {item}", file=sys.stderr)
        return 1
    print("uniform_sync MC schema verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
