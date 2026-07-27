#!/usr/bin/env python3
"""Build a dataset snapshot (assemble + OSS export)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH
PROJECT_ROOT = HMI_ROOT
BACKEND_ROOT = BACKEND
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import ensure_schema
from hmi.dataset.build import build_snapshot_sync, enqueue_build, is_build_running
from hmi.dataset_db import get_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dataset snapshot to OSS 特征/目标 artifacts")
    parser.add_argument("--snapshot-id", required=True, help="dataset_snapshot id")
    parser.add_argument(
        "--async",
        dest="run_async",
        action="store_true",
        help="enqueue background build instead of blocking",
    )
    parser.add_argument("--json", action="store_true", help="print result as JSON")
    args = parser.parse_args()

    ensure_schema()
    snapshot_id = args.snapshot_id.strip()
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        print(f"error: snapshot not found: {snapshot_id}", file=sys.stderr)
        return 1

    if args.run_async:
        try:
            enqueue_build(snapshot_id)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"snapshot_id": snapshot_id, "status": "building", "async": True}))
        else:
            print(f"enqueued\t{snapshot_id}")
        return 0

    try:
        result = build_snapshot_sync(snapshot_id)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    else:
        snap = result["snapshot"]
        print(
            f"ready\t{snapshot_id}\tclips={snap['clip_count']}\t"
            f"x={snap.get('oss_x_uri')}\ty={snap.get('oss_y_uri')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
