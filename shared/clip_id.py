"""Compute content-addressed clip_id from rosbag files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def discover_bag_files(rosbag_dir: Path, bag_config: dict[str, Any]) -> list[Path]:
    """Return bag file paths in deterministic sorted order."""
    ros1_glob = str(bag_config.get("ros1_glob", "*.bag"))
    bags = sorted(rosbag_dir.glob(ros1_glob))
    if bags:
        return bags

    metadata_name = str(bag_config.get("ros2_metadata_file", "metadata.yaml"))
    return sorted(
        path
        for path in rosbag_dir.iterdir()
        if path.is_dir() and (path / metadata_name).exists()
    )


def _hash_path(hasher: hashlib._Hash, path: Path) -> None:
    if path.is_dir():
        for child in sorted(path.rglob("*")):
            if child.is_file():
                _hash_file(hasher, child)
        return
    _hash_file(hasher, path)


def _hash_file(hasher: hashlib._Hash, path: Path) -> None:
    hasher.update(path.name.encode("utf-8"))
    with path.open("rb") as bag_file:
        while True:
            block = bag_file.read(1024 * 1024)
            if not block:
                break
            hasher.update(block)


def write_rosbag_manifest(rosbag_dir: Path, bag_config: dict[str, Any]) -> Path:
    """Write a small JSON manifest so tooling can discover bags without indexing .bag binaries."""
    bag_paths = discover_bag_files(rosbag_dir, bag_config)
    bags: list[dict[str, Any]] = []
    for bag_path in bag_paths:
        if bag_path.is_file():
            bags.append(
                {
                    "name": bag_path.name,
                    "path": str(bag_path),
                    "size_bytes": bag_path.stat().st_size,
                    "kind": "ros1_bag",
                }
            )
        else:
            bags.append(
                {
                    "name": bag_path.name,
                    "path": str(bag_path),
                    "kind": "ros2_bag_dir",
                }
            )

    manifest_path = rosbag_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps({"rosbag_dir": str(rosbag_dir), "bags": bags}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest_path


def compute_content_hash(rosbag_dir: Path, bag_config: dict[str, Any]) -> str:
    bag_paths = discover_bag_files(rosbag_dir, bag_config)
    if not bag_paths:
        raise FileNotFoundError(f"No rosbag files found in: {rosbag_dir}")

    hasher = hashlib.sha256()
    for bag_path in bag_paths:
        _hash_path(hasher, bag_path)
    return hasher.hexdigest()


def format_clip_id(content_hash: str, clip_id_config: dict[str, Any]) -> str:
    algorithm = str(clip_id_config.get("algorithm", "sha256"))
    if algorithm != "sha256":
        raise ValueError(f"Unsupported clip_id algorithm: {algorithm}")

    fmt = str(clip_id_config.get("format", "sha256:{hex}"))
    return fmt.format(hex=content_hash)


def compute_clip_id(rosbag_dir: Path, config: dict[str, Any]) -> str:
    cloud_config = config.get("cloud", {})
    clip_id_config = cloud_config.get("clip_id", {})
    content_hash = compute_content_hash(rosbag_dir, config.get("bag", {}))
    return format_clip_id(content_hash, clip_id_config)
