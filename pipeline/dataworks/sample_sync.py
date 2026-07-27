"""Four-camera time-aligned sampling and sync-group helpers (Job2/Job3)."""

from __future__ import annotations

from typing import Any

DEFAULT_ALIGN_WINDOW_MS = 200


def align_window_ns_from_ms(window_ms: float | int) -> int:
    return int(float(window_ms) * 1_000_000)


def resolve_required_cameras(
    frames: list[dict[str, Any]],
    cameras: Any,
) -> list[str]:
    if cameras not in (None, "all", "*"):
        if isinstance(cameras, str):
            return sorted(item.strip() for item in cameras.split(",") if item.strip())
        return sorted(str(item) for item in cameras)
    return sorted({str(frame["camera"]) for frame in frames})


def _nearest_frame_in_window(
    camera_frames: list[dict[str, Any]],
    anchor_ns: int,
    window_ns: int,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_dist: int | None = None
    for frame in camera_frames:
        ts = int(frame["timestamp_ns"])
        dist = abs(ts - anchor_ns)
        if dist > window_ns:
            continue
        if best_dist is None or dist < best_dist:
            best = frame
            best_dist = dist
    return best


def sample_uniform_sync(
    frames: list[dict[str, Any]],
    *,
    interval_sec: float,
    align_window_ms: float | int = DEFAULT_ALIGN_WINDOW_MS,
    cameras: Any = "all",
    start_time_ns: int | None = None,
    end_time_ns: int | None = None,
    min_cameras: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (flat sampled_frames with sync_group_id, sample_groups metadata).

    Each sync group only emitted when all required cameras have a frame within
    ±align_window_ms of the anchor timestamp.
    """
    if not frames:
        return [], []

    interval_ns = int(float(interval_sec) * 1_000_000_000)
    window_ns = align_window_ns_from_ms(align_window_ms)
    required = resolve_required_cameras(frames, cameras)
    if not required:
        return [], []

    need = min_cameras if min_cameras is not None else len(required)
    need = max(1, min(need, len(required)))

    by_camera: dict[str, list[dict[str, Any]]] = {}
    for frame in frames:
        if str(frame["camera"]) not in required:
            continue
        by_camera.setdefault(str(frame["camera"]), []).append(frame)
    for camera_frames in by_camera.values():
        camera_frames.sort(key=lambda item: int(item["timestamp_ns"]))

    all_ts = [int(frame["timestamp_ns"]) for frame in frames]
    range_start = int(start_time_ns if start_time_ns is not None else min(all_ts))
    range_end = int(end_time_ns if end_time_ns is not None else max(all_ts))
    if interval_ns <= 0:
        raise ValueError("interval_sec must be positive")

    flat: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    group_idx = 0
    anchor = range_start
    while anchor <= range_end:
        picked: list[dict[str, Any]] = []
        for camera in required:
            match = _nearest_frame_in_window(by_camera.get(camera, []), anchor, window_ns)
            if match is not None:
                picked.append(match)
        if len(picked) >= need and len(picked) == len(required):
            group_idx += 1
            sync_group_id = f"sg{group_idx:06d}"
            group_frames: list[dict[str, Any]] = []
            for frame in sorted(picked, key=lambda item: str(item["camera"])):
                row = dict(frame)
                row["sync_group_id"] = sync_group_id
                row["anchor_timestamp_ns"] = anchor
                group_frames.append(row)
                flat.append(row)
            groups.append(
                {
                    "sync_group_id": sync_group_id,
                    "anchor_timestamp_ns": anchor,
                    "cameras": [str(item["camera"]) for item in group_frames],
                    "frames": group_frames,
                }
            )
        anchor += interval_ns
    return flat, groups


def is_sync_sample_policy(policy: dict[str, Any] | None) -> bool:
    if not policy:
        return False
    return str(policy.get("type") or "") == "uniform_sync"


def group_manifest_by_sync(manifest_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not any(str(row.get("sync_group_id") or "").strip() for row in manifest_rows):
        return []
    grouped: dict[str, dict[str, Any]] = {}
    for row in manifest_rows:
        sync_group_id = str(row.get("sync_group_id") or "").strip()
        if not sync_group_id:
            continue
        bucket = grouped.setdefault(
            sync_group_id,
            {
                "sync_group_id": sync_group_id,
                "anchor_timestamp_ns": int(row.get("anchor_timestamp_ns") or row["timestamp_ns"]),
                "frames": [],
            },
        )
        bucket["frames"].append(row)
    return sorted(grouped.values(), key=lambda item: int(item["anchor_timestamp_ns"]))
