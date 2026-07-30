"""Create local test runtime dirs + empty SQLite (OSS/MC simulation on disk)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Init HMI local runtime (SQLite + oss/ mirror)")
    parser.add_argument(
        "--force-root",
        type=Path,
        default=None,
        help="Override HMI_RUNTIME_ROOT for this run only",
    )
    args = parser.parse_args()
    if args.force_root:
        os.environ["HMI_RUNTIME_ROOT"] = str(args.force_root.resolve())

    repo = Path(__file__).resolve().parents[2]
    for entry in (repo / "shared", repo / "hmi" / "backend"):
        text = str(entry)
        if text not in sys.path:
            sys.path.insert(0, text)

    from hmi.data_source import (  # noqa: E402
        LOCAL_CONFIG_PATH,
        LOCAL_ROOT,
        ensure_runtime_layout,
        set_data_source,
    )
    from hmi.local.store import ensure_db  # noqa: E402

    root = ensure_runtime_layout()
    ensure_db()
    marker = root / ".initialized"
    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    mode = set_data_source("local")
    payload: dict = {}
    if LOCAL_CONFIG_PATH.is_file():
        payload = json.loads(LOCAL_CONFIG_PATH.read_text(encoding="utf-8"))
    payload["initialized_at"] = datetime.now(timezone.utc).isoformat()
    LOCAL_CONFIG_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Local runtime ready: {LOCAL_ROOT}")
    print(f"  SQLite: {LOCAL_ROOT / 'hmi.db'}")
    print(f"  OSS mirror: {LOCAL_ROOT / 'oss'}")
    print(f"  data_source={mode}")
    print("Next: py -3 scripts/seed_demo_clip_data.py --reset  OR  import_real_data_clips.py")


if __name__ == "__main__":
    main()
