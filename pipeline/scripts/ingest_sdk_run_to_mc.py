#!/usr/bin/env python3
"""Push SDK jsonl facts from local artifacts into MaxCompute aig_sdk__ tables.

Requires MC tables from sql/maxcompute/aig_sdk__ddl.sql and ODPS credentials in .env.

Usage:
  py -3 scripts/ingest_sdk_run_to_mc.py --clip-id sha256:... --run-id <uuid> --ds 20260727
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
DATAWORKS_ROOT = PIPELINE_ROOT / "dataworks"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, DATAWORKS_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from hmi.data_source import artifact_path
from sdk_mc_ingest import ingest_sdk_run


def _prefix(settings: dict[str, str]) -> str:
    return settings.get("sdk_table_prefix") or settings.get("table_prefix") or "aig_sdk__"


def main() -> int:
    load_cloud_env()
    import yaml

    with (CONFIG_PATH).open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    settings = require_odps_settings(resolve_cloud_settings(config))
    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )

    parser = argparse.ArgumentParser(description="Ingest local SDK bundle into MaxCompute")
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ds", required=True, help="yyyyMMdd partition")
    args = parser.parse_args()

    clip_id = args.clip_id.strip()
    run_id = args.run_id.strip()
    ds = args.ds.strip()
    root = artifact_path(clip_id, run_id, "")
    ingest_sdk_run(
        odps,
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        run_dir=root,
        table_prefix=_prefix(settings),
    )

    print(f"Ingested SDK run clip_id={clip_id[:24]}… ds={ds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
