#!/usr/bin/env python3
"""Local pre-checks before DataWorks E2E (Job0+)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import oss2
import yaml
from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings

TEST_CLIP_ID = "sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b"
TEST_BAG_KEY = "rosbags/2026-06-05_13-27-07/output.bag"
TAXONOMY_KEY = "config/oms_label_taxonomy.yaml"


def main() -> None:
    parser = argparse.ArgumentParser(description="E2E pre-check: OSS + MC dim_clip")
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    with args.config.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    settings = require_odps_settings(resolve_cloud_settings(config))

    print("=== ODPS ===")
    print(f"project={settings['odps_project']} endpoint={settings['odps_endpoint']}")
    o = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        settings["odps_project"],
        settings["odps_endpoint"],
    )
    o.get_project()

    print("\n=== OSS ===")
    auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
    bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])
    for key in (TEST_BAG_KEY, TAXONOMY_KEY):
        ok = bucket.object_exists(key)
        line = f"{'OK' if ok else 'MISSING'} oss://{settings['oss_bucket']}/{key}"
        if ok:
            meta = bucket.head_object(key)
            line += f" size={meta.content_length}"
        print(line)

    print("\n=== MC dim_clip ===")
    sql = (
        f"SELECT clip_id, clip_dir_name, active_run_id, bag_oss_key "
        f"FROM aig_rosbag__dim_clip WHERE clip_id = '{TEST_CLIP_ID}'"
    )
    with o.execute_sql(sql).open_reader() as reader:
        rows = list(reader)
    if not rows:
        print(f"clip NOT in dim_clip -> Job0 should discover and insert")
        print(f"expected clip_id={TEST_CLIP_ID}")
    else:
        for row in rows:
            print(
                f"clip_id={row[0]} dir={row[1]} active_run_id={row[2]!r} bag={row[3]}"
            )
        if rows[0][2] is None:
            print("active_run_id IS NULL -> Job0 done, ready for Job1")
        else:
            print(f"active_run_id set -> Job1+ may have run (run_id={rows[0][2]})")

    with o.execute_sql("SELECT COUNT(*) FROM aig_rosbag__dim_clip").open_reader() as reader:
        print(f"dim_clip total rows: {list(reader)[0][0]}")


if __name__ == "__main__":
    main()
