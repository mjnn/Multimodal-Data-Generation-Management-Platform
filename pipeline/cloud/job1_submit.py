#!/usr/bin/env python3
"""Submit Job1 rosbag parse to MaxFrame custom DPE and write MC tables.

DEPRECATED for new cloud development — use dataworks/job1_parse_node.py +
job1_mc_write_node.py (MaxFrame UDF paste nodes). This script uses subprocess
to /app/... which is forbidden for new jobs per maxframe-dpe-cloud.mdc.
Kept for local ACR debugging only.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_running_options

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, REPO_ROOT / "hmi" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cloud.mc_writer import write_job1_to_mc
from cloud.odps_client import create_odps_client
from cloud_config import (
    format_clip_oss_prefix,
    load_cloud_env,
    oss_internal_url,
    require_job1_settings,
    resolve_cloud_settings,
)
from parse_rosbag import load_config


def _utc_ds() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def _build_job_row(
    *,
    clip_id: str,
    run_id: str,
    clip_dir_name: str,
    bag_relpath: str,
    output_relpath: str,
) -> dict[str, str]:
    return {
        "clip_id": clip_id,
        "run_id": run_id,
        "clip_dir_name": clip_dir_name,
        "bag_relpath": bag_relpath,
        "output_relpath": output_relpath,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Job1 parse on MaxFrame custom DPE.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--clip-dir-name", default="cloud")
    parser.add_argument("--run-id", help="Pipeline run id; generated when omitted.")
    parser.add_argument("--bag-file", default="output.bag", help="Bag file name under raw/")
    parser.add_argument("--ds", help="MC partition ds=yyyyMMdd; default today UTC.")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved settings and exit.")
    args = parser.parse_args()

    load_cloud_env()
    config = load_config(args.config.resolve())
    settings = require_job1_settings(resolve_cloud_settings(config))
    run_id = args.run_id or str(uuid.uuid4())
    ds = args.ds or _utc_ds()

    clip_prefix = format_clip_oss_prefix(settings, args.clip_id)
    oss_mount_url = oss_internal_url(settings["region"], settings["oss_bucket"], clip_prefix)
    bag_relpath = f"{settings['oss_raw_subdir'].rstrip('/')}/{args.bag_file}"
    output_relpath = (
        settings["oss_runs_subdir"].format(run_id=run_id).rstrip("/") + "/parsed"
    )
    mount_path = settings["dpe_mount_path"]
    dpe_image = settings["dpe_image"]
    dpe_cpu = int(settings["dpe_cpu"])
    dpe_memory = int(settings["dpe_memory_gb"])
    role_arn = settings["oss_ram_role_arn"]

    print(f"clip_id: {args.clip_id}")
    print(f"run_id: {run_id}")
    print(f"ds: {ds}")
    print(f"oss_mount: {oss_mount_url} -> {mount_path}")
    print(f"dpe_image: {dpe_image}")

    if args.dry_run:
        print("Dry run only; not submitting MaxFrame job.")
        return

    options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    options.sql.settings = {"odps.session.image": dpe_image}
    options.local_execution.enabled = False

    odps = create_odps_client(settings)
    session = new_session(odps)

    job_row = _build_job_row(
        clip_id=args.clip_id,
        run_id=run_id,
        clip_dir_name=args.clip_dir_name,
        bag_relpath=bag_relpath,
        output_relpath=output_relpath,
    )
    input_df = md.DataFrame(pd.DataFrame([job_row]))

    @with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)
    @with_fs_mount(
        oss_mount_url,
        mount_path,
        storage_options={"role_arn": role_arn},
    )
    def _parse_clip_row(row):
        python_executable = os.environ.get("MF_PYTHON_EXECUTABLE", "python3")
        bag_path = os.path.join(mount_path, row["bag_relpath"])
        output_dir = os.path.join(mount_path, row["output_relpath"])
        os.makedirs(output_dir, exist_ok=True)
        command = [
            python_executable,
            "/app/cloud/job1_worker.py",
            "--config",
            "/app/config.yaml",
            "--bag-path",
            bag_path,
            "--output-dir",
            output_dir,
            "--clip-dir-name",
            str(row["clip_dir_name"]),
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"job1_worker failed ({completed.returncode}): {completed.stderr or completed.stdout}"
            )
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
        return {
            "clip_id": payload["clip_id"],
            "run_id": row["run_id"],
            "clip_dir_name": payload["clip_dir_name"],
            "content_hash": payload["content_hash"],
            "bag_stem": payload["bag_stem"],
            "parse_result_json": json.dumps(payload["parse_result"], ensure_ascii=False),
        }

    try:
        print(f"Logview: {session.get_logview_address()}")
        result_df = input_df.apply(
            _parse_clip_row,
            axis=1,
            output_type="dataframe",
            result_type="expand",
        )
        result = result_df.execute().fetch()
        if result.empty:
            raise RuntimeError("Job1 DPE returned no rows")

        row = result.iloc[0]
        parse_result = json.loads(row["parse_result_json"])
        write_job1_to_mc(
            odps,
            table_prefix=settings["table_prefix"],
            ds=ds,
            clip_id=str(row["clip_id"]),
            clip_dir_name=str(row["clip_dir_name"]),
            content_hash=str(row["content_hash"]),
            run_id=str(row["run_id"]),
            bag_stem=str(row["bag_stem"]),
            parse_result=parse_result,
        )
        print(
            f"Job1 completed: clip_id={row['clip_id']} run_id={row['run_id']} "
            f"frames={len(parse_result['frames'])} audio_chunks={len(parse_result['audio_chunks'])}"
        )
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


if __name__ == "__main__":
    main()
