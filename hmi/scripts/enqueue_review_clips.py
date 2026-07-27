#!/usr/bin/env python3
"""Enqueue clips into review queue from clip-level or legacy frame labels."""

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
from hmi.review.enqueue import enqueue_clip, enqueue_clips, list_enqueue_candidates


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enqueue clip(s) into clip_label_review from AI labels"
    )
    parser.add_argument(
        "--clip-id",
        action="append",
        dest="clip_ids",
        help="Clip ID to enqueue (repeatable)",
    )
    parser.add_argument(
        "--run-id",
        help="Run ID (with single --clip-id; default: active_run_id)",
    )
    parser.add_argument(
        "--scan",
        action="store_true",
        help="Scan all labeled clips without review row and enqueue",
    )
    parser.add_argument(
        "--list-candidates",
        action="store_true",
        help="List enqueue candidates without creating reviews",
    )
    parser.add_argument(
        "--no-require-job3",
        action="store_true",
        help="Skip job2_clip_omni success check (still requires labeled rows)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print results as JSON",
    )
    args = parser.parse_args()

    ensure_schema()
    require_job3 = not args.no_require_job3

    if args.list_candidates:
        candidates = list_enqueue_candidates(require_job3=require_job3)
        if args.json:
            print(json.dumps(candidates, ensure_ascii=False, indent=2))
        else:
            for item in candidates:
                print(f"{item['clip_id']}\t{item['run_id']}")
        return 0

    if args.scan:
        results = enqueue_clips(scan_unqueued=True, require_job3=require_job3)
    elif args.clip_ids:
        if len(args.clip_ids) == 1 and args.run_id:
            results = [
                enqueue_clip(
                    args.clip_ids[0],
                    args.run_id,
                    require_job3=require_job3,
                )
            ]
        else:
            results = enqueue_clips(
                clip_ids=args.clip_ids,
                require_job3=require_job3,
            )
    else:
        parser.error("Specify --clip-id, --scan, or --list-candidates")

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        for result in results:
            status = result.get("status")
            if status == "created":
                review = result["review"]
                print(
                    f"created\t{review['clip_id']}\t{review['run_id']}\t"
                    f"agg={result.get('aggregation')}"
                )
            elif status == "skipped":
                review = result["review"]
                print(f"skipped\t{review['clip_id']}\t{review['run_id']}\t{result.get('reason')}")
            else:
                print(
                    f"error\t{result.get('clip_id')}\t{result.get('run_id')}\t"
                    f"{result.get('error')}"
                )

    errors = sum(1 for r in results if r.get("status") == "error")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
