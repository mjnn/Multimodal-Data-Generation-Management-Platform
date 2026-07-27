#!/usr/bin/env python3
"""Job1 rosbag parse worker for MaxFrame custom DPE (no maxframe SDK)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, REPO_ROOT / "hmi" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from clip_id import compute_clip_id, compute_content_hash
from parse_rosbag import discover_bags, load_config, parse_bag


def _serialize_parse_result(parse_result: Any) -> dict[str, Any]:
    if hasattr(parse_result, "metadata"):
        return {
            "metadata": parse_result.metadata,
            "timeline_messages": parse_result.timeline_messages,
            "frames": parse_result.frames,
            "audio_chunks": parse_result.audio_chunks,
            "events": parse_result.events,
        }
    if is_dataclass(parse_result):
        return asdict(parse_result)
    raise TypeError(f"Unsupported parse result type: {type(parse_result)}")


def run_job1_parse(
    *,
    config: dict[str, Any],
    bag_path: Path,
    output_dir: Path,
    clip_dir_name: str,
) -> dict[str, Any]:
    bag_paths = discover_bags(bag_path.parent if bag_path.is_file() else bag_path, config["bag"])
    if not bag_paths:
        raise FileNotFoundError(f"No rosbag files found near: {bag_path}")

    bag_file = bag_paths[0]
    rosbag_dir = bag_file.parent
    clip_id = compute_clip_id(rosbag_dir, config)
    content_hash = compute_content_hash(rosbag_dir, config["bag"])
    parse_result = parse_bag(bag_file, output_dir, config)
    payload = _serialize_parse_result(parse_result)
    return {
        "clip_id": clip_id,
        "clip_dir_name": clip_dir_name,
        "content_hash": content_hash,
        "bag_stem": bag_file.stem,
        "parse_result": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse one rosbag inside Job1 DPE.")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--bag-path", type=Path, required=True, help="Path to .bag file or rosbag dir")
    parser.add_argument("--output-dir", type=Path, required=True, help="Parsed output directory")
    parser.add_argument("--clip-dir-name", default="cloud")
    args = parser.parse_args()

    config = load_config(args.config.resolve())
    result = run_job1_parse(
        config=config,
        bag_path=args.bag_path,
        output_dir=args.output_dir,
        clip_dir_name=args.clip_dir_name,
    )
    json.dump(result, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
