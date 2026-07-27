#!/usr/bin/env python3
"""Publish pipeline/dispatch/latest.json for SDK v1 auto-sync."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, resolve_cloud_settings
from hmi.config import SDK_PIPELINE_VERSION
from hmi.local import store
from hmi.oss_layout import SDK_LAYOUT_VERSION
from hmi.services.pipeline_status import DISPATCH_MANIFEST_KEY

REAL_DATA_BAG_OSS_PREFIX = "local://real_data/"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _run_prefix(settings: dict[str, str], clip_id: str, run_id: str) -> str:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs_subdir}/"


def main() -> int:
    load_cloud_env()
    settings = resolve_cloud_settings()

    parser = argparse.ArgumentParser(description="Publish SDK dispatch manifest to OSS")
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ds", default=None, help="yyyyMMdd partition (default from app_meta last_ds)")
    parser.add_argument("--bag-oss-key", default="", help="rosbags/... key (default from dim_clip)")
    args = parser.parse_args()

    clip_id = args.clip_id.strip()
    run_id = args.run_id.strip()
    ds = (args.ds or store.get_meta("last_ds") or datetime.now(timezone.utc).strftime("%Y%m%d")).strip()

    row = store.query_one(
        "SELECT bag_oss_key FROM dim_clip WHERE clip_id=? LIMIT 1",
        (clip_id,),
    )
    bag_oss_key = (args.bag_oss_key or (str(row["bag_oss_key"]) if row else "") or "").strip()
    if not bag_oss_key:
        bag_oss_key = f"rosbags/{clip_id.split(':', 1)[-1][:16]}.bag"

    manifest = {
        "action": "run",
        "layout_version": SDK_LAYOUT_VERSION,
        "pipeline_version": SDK_PIPELINE_VERSION,
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": ds,
        "bag_oss_key": bag_oss_key,
        "run_oss_prefix": _run_prefix(settings, clip_id, run_id),
        "dispatched_at": _utc_now(),
    }

    from hmi.oss_signer import put_object_text

    body = json.dumps(manifest, ensure_ascii=False, indent=2)
    put_object_text(DISPATCH_MANIFEST_KEY, body, content_type="application/json")
    print(f"Published {DISPATCH_MANIFEST_KEY}")
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
