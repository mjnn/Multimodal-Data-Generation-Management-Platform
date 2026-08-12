"""Load bboxes.jsonl for Clip Explorer detail panel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.data_source import artifact_path, oss_key_path


def _candidate_bbox_paths(clip_id: str, run_id: str) -> list[Path]:
    paths = [
        artifact_path(clip_id, run_id, "bboxes.jsonl"),
        oss_key_path(f"clips/{clip_id}/runs/{run_id}/bboxes.jsonl"),
    ]
    # sha256: → sha256__ folder already handled by artifact_path; also try OSS-safe dir
    safe = clip_id.replace(":", "__")
    if safe != clip_id:
        paths.append(oss_key_path(f"clips/{safe}/runs/{run_id}/bboxes.jsonl"))
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        key = str(p.resolve()) if p.exists() else str(p)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def find_bboxes_jsonl(clip_id: str, run_id: str) -> Path | None:
    for path in _candidate_bbox_paths(clip_id, run_id):
        if path.is_file():
            return path
    return None


def _normalize_box(raw: dict[str, Any]) -> dict[str, Any]:
    element = str(raw.get("element") or raw.get("label") or "").strip() or "element"
    gender = raw.get("gender")
    age_range = raw.get("age_range")
    age_approx = raw.get("age_approx")
    label_parts = [element]
    if gender:
        label_parts.append(str(gender).strip().lower())
    if age_approx is not None:
        try:
            label_parts.append(f"~{int(age_approx)}y")
        except (TypeError, ValueError):
            if age_range:
                label_parts.append(str(age_range))
    elif age_range:
        label_parts.append(str(age_range))

    def _f(key: str) -> float | None:
        if raw.get(key) is None:
            return None
        try:
            return float(raw[key])
        except (TypeError, ValueError):
            return None

    score = _f("score")
    # YuNet historically wrote landmark coords as score; hide non-probabilities.
    if score is not None and not (0.0 <= score <= 1.0):
        score = None

    return {
        "x1": float(raw.get("x1") or 0),
        "y1": float(raw.get("y1") or 0),
        "x2": float(raw.get("x2") or 0),
        "y2": float(raw.get("y2") or 0),
        "element": element,
        "display_label": "/".join(label_parts),
        "score": score,
        "class_id": int(raw["class_id"]) if raw.get("class_id") is not None else None,
        "gender": str(gender).strip().lower() if gender is not None else None,
        "age_range": str(age_range) if age_range is not None else None,
        "age_approx": int(age_approx) if age_approx is not None else None,
        "gender_score": _f("gender_score"),
        "age_score": _f("age_score"),
    }


def _camera_from_topic(topic: str) -> str:
    t = (topic or "").strip().lower()
    for i in range(8):
        if f"camera{i}" in t:
            return f"camera{i}"
    parts = [p for p in t.strip("/").split("/") if p]
    return parts[0] if parts else "camera"


def load_bbox_frames(clip_id: str, run_id: str) -> list[dict[str, Any]]:
    path = find_bboxes_jsonl(clip_id, run_id)
    if path is None:
        return []
    frames: list[dict[str, Any]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        boxes_raw = row.get("boxes") or row.get("elements") or []
        if not isinstance(boxes_raw, list):
            boxes_raw = []
        topic = str(row.get("topic") or "")
        try:
            ts = int(row.get("timestamp_ns") or 0)
        except (TypeError, ValueError):
            continue
        frames.append(
            {
                "clip_id": str(row.get("clip_id") or clip_id),
                "topic": topic,
                "camera": _camera_from_topic(topic),
                "timestamp_ns": ts,
                "boxes": [_normalize_box(b) for b in boxes_raw if isinstance(b, dict)],
                "box_count": len([b for b in boxes_raw if isinstance(b, dict)]),
            }
        )
    frames.sort(key=lambda f: (f["timestamp_ns"], f["camera"]))
    return frames


def bboxes_at_timestamp(
    clip_id: str,
    run_id: str,
    timestamp_ns: int,
    *,
    window_ms: int = 200,
) -> dict[str, Any]:
    """Return detections near ``timestamp_ns`` (default ±200ms), one nearest frame per camera."""
    frames = load_bbox_frames(clip_id, run_id)
    window_ns = max(0, int(window_ms)) * 1_000_000
    by_cam: dict[str, dict[str, Any]] = {}
    for fr in frames:
        cam = str(fr["camera"])
        delta = abs(int(fr["timestamp_ns"]) - int(timestamp_ns))
        if delta > window_ns:
            continue
        prev = by_cam.get(cam)
        if prev is None or delta < abs(int(prev["timestamp_ns"]) - int(timestamp_ns)):
            by_cam[cam] = {**fr, "delta_ns": delta}
    selected = [by_cam[k] for k in sorted(by_cam.keys())]
    detections: list[dict[str, Any]] = []
    for fr in selected:
        for i, box in enumerate(fr.get("boxes") or []):
            detections.append(
                {
                    **box,
                    "camera": fr["camera"],
                    "topic": fr["topic"],
                    "timestamp_ns": fr["timestamp_ns"],
                    "delta_ns": fr.get("delta_ns"),
                    "box_index": i,
                }
            )
    return {
        "clip_id": clip_id,
        "run_id": run_id,
        "timestamp_ns": int(timestamp_ns),
        "window_ms": int(window_ms),
        "has_bboxes": bool(frames),
        "frame_count": len(frames),
        "frames_at_cursor": selected,
        "detections": detections,
    }
