#!/usr/bin/env python3
"""Tests for four-camera uniform_sync sampling."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "dataworks"))

from sample_sync import (  # noqa: E402
    group_manifest_by_sync,
    is_sync_sample_policy,
    sample_uniform_sync,
)


def _frame(camera: str, frame_idx: int, timestamp_ns: int) -> dict:
    return {
        "camera": camera,
        "frame_idx": frame_idx,
        "timestamp_ns": timestamp_ns,
        "image_path": f"output/images/{camera}/{frame_idx:06d}.jpg",
    }


def test_uniform_sync_emits_full_quads_only() -> None:
    frames: list[dict] = []
    base = 1_000_000_000
    for camera_idx in range(4):
        camera = f"camera{camera_idx}"
        for i in range(10):
            frames.append(_frame(camera, i, base + i * 100_000_000 + camera_idx * 5_000_000))

    flat, groups = sample_uniform_sync(
        frames,
        interval_sec=1.0,
        align_window_ms=200,
        start_time_ns=base,
        end_time_ns=base + 900_000_000,
    )

    assert flat, "expected sampled frames"
    assert groups, "expected sync groups"
    assert len(flat) == len(groups) * 4
    for group in groups:
        assert len(group["frames"]) == 4
        cameras = {str(item["camera"]) for item in group["frames"]}
        assert cameras == {"camera0", "camera1", "camera2", "camera3"}
        sync_id = group["sync_group_id"]
        for item in group["frames"]:
            assert item["sync_group_id"] == sync_id
            assert item["anchor_timestamp_ns"] == group["anchor_timestamp_ns"]


def test_group_manifest_by_sync() -> None:
    manifest = [
        {
            "camera": "camera0",
            "frame_idx": 1,
            "timestamp_ns": 100,
            "sync_group_id": "sg000001",
            "anchor_timestamp_ns": 95,
        },
        {
            "camera": "camera1",
            "frame_idx": 2,
            "timestamp_ns": 102,
            "sync_group_id": "sg000001",
            "anchor_timestamp_ns": 95,
        },
    ]
    groups = group_manifest_by_sync(manifest)
    assert len(groups) == 1
    assert groups[0]["sync_group_id"] == "sg000001"
    assert len(groups[0]["frames"]) == 2


def test_is_sync_sample_policy() -> None:
    assert is_sync_sample_policy({"type": "uniform_sync"})
    assert not is_sync_sample_policy({"type": "uniform"})


if __name__ == "__main__":
    test_uniform_sync_emits_full_quads_only()
    test_group_manifest_by_sync()
    test_is_sync_sample_policy()
    print("test_sample_sync: ok")
