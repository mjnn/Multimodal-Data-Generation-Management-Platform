#!/usr/bin/env python3
"""Re-encode local clip frame JPEGs for web preview (progressive, max width)."""

from __future__ import annotations

import argparse
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
BACKEND = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from hmi.data_source import artifacts_dir
from hmi.db import cache_clear
from hmi.local import store
from hmi.media.frame_encode import encode_frame_image


def main() -> None:
    parser = argparse.ArgumentParser(description="Encode clip frame images for HMI playback")
    parser.add_argument("--clip-id", help="Limit to one clip_id")
    parser.add_argument("--max-width", type=int, default=1280)
    parser.add_argument("--quality", type=int, default=85)
    args = parser.parse_args()

    store.ensure_db()
    sql = "SELECT clip_id, active_run_id FROM dim_clip WHERE active_run_id IS NOT NULL"
    params: tuple = ()
    if args.clip_id:
        sql += " AND clip_id=?"
        params = (args.clip_id,)
    rows = store.query(sql, params)
    total = 0
    encoded_paths: set[Path] = set()
    for row in rows:
        cid = str(row["clip_id"])
        rid = str(row["active_run_id"])
        root = artifacts_dir(cid, rid)
        frames = store.query(
            "SELECT image_path FROM fact_frame WHERE clip_id=? AND run_id=?",
            (cid, rid),
        )
        for fr in frames:
            rel = str(fr["image_path"])
            path = root / rel.replace("\\", "/")
            if path in encoded_paths:
                continue
            if encode_frame_image(path, max_width=args.max_width, quality=args.quality) is not None:
                encoded_paths.add(path)
                total += 1
        images_dir = root / "parsed" / "output" / "images"
        if images_dir.is_dir():
            for path in images_dir.rglob("*"):
                if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                    continue
                if path in encoded_paths:
                    continue
                if encode_frame_image(path, max_width=args.max_width, quality=args.quality) is not None:
                    encoded_paths.add(path)
                    total += 1
    cache_clear()
    print(f"Encoded {total} frame file(s)")


if __name__ == "__main__":
    main()
