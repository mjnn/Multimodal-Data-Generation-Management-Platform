"""Load / write bboxes.jsonl for Clip Explorer overlay and detail panel."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from hmi.data_source import artifact_path, oss_key_path

# Fields persisted to disk (API-only keys like display_label are omitted).
_BOX_WRITE_KEYS = (
    "x1",
    "y1",
    "x2",
    "y2",
    "element",
    "score",
    "class_id",
    "gender",
    "age_range",
    "age_approx",
    "gender_score",
    "age_score",
)


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


def _probe_image_size(path: Path) -> tuple[int, int] | None:
    try:
        from PIL import Image

        with Image.open(path) as im:
            w, h = im.size
            if w > 0 and h > 0:
                return int(w), int(h)
    except Exception:
        pass
    try:
        import cv2

        mat = cv2.imread(str(path))
        if mat is not None and mat.shape[0] > 0 and mat.shape[1] > 0:
            return int(mat.shape[1]), int(mat.shape[0])
    except Exception:
        pass
    return None


def _resolve_frame_image(clip_id: str, run_id: str, image_path: str) -> Path | None:
    raw = (image_path or "").strip()
    if not raw:
        return None
    p = Path(raw)
    if p.is_file():
        return p
    # relative under run artifacts
    cand = artifact_path(clip_id, run_id, raw.replace("\\", "/"))
    if cand.is_file():
        return cand
    # basename search under frames/
    name = Path(raw).name
    frames_root = artifact_path(clip_id, run_id, "frames")
    if frames_root.is_dir() and name:
        for hit in frames_root.rglob(name):
            if hit.is_file():
                return hit
    return None


_size_cache: dict[str, tuple[int, int] | None] = {}


def _frame_image_size(clip_id: str, run_id: str, row: dict[str, Any]) -> tuple[int | None, int | None]:
    try:
        iw = int(row["image_width"]) if row.get("image_width") is not None else None
        ih = int(row["image_height"]) if row.get("image_height") is not None else None
    except (TypeError, ValueError):
        iw, ih = None, None
    if iw and ih:
        return iw, ih
    image_path = str(row.get("image_path") or row.get("annotated_image_path") or "")
    cache_key = f"{clip_id}|{run_id}|{image_path}"
    if cache_key in _size_cache:
        sized = _size_cache[cache_key]
        return (sized[0], sized[1]) if sized else (None, None)
    resolved = _resolve_frame_image(clip_id, run_id, image_path)
    sized = _probe_image_size(resolved) if resolved is not None else None
    _size_cache[cache_key] = sized
    if sized:
        return sized[0], sized[1]
    return None, None


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
        iw, ih = _frame_image_size(clip_id, run_id, row)
        frames.append(
            {
                "clip_id": str(row.get("clip_id") or clip_id),
                "topic": topic,
                "camera": _camera_from_topic(topic),
                "timestamp_ns": ts,
                "image_path": str(row.get("image_path") or ""),
                "image_width": iw,
                "image_height": ih,
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


def resolve_bboxes_write_path(clip_id: str, run_id: str) -> Path:
    """Existing jsonl path, or default artifact path when creating a new file."""
    existing = find_bboxes_jsonl(clip_id, run_id)
    if existing is not None:
        return existing
    return artifact_path(clip_id, run_id, "bboxes.jsonl")


def _serialize_box(raw: dict[str, Any]) -> dict[str, Any]:
    """Strip API-only fields; keep SDK-compatible box dict."""
    out: dict[str, Any] = {}
    element = str(raw.get("element") or raw.get("label") or "").strip() or "element"
    out["element"] = element
    for key in ("x1", "y1", "x2", "y2"):
        try:
            out[key] = float(raw.get(key) or 0)
        except (TypeError, ValueError):
            out[key] = 0.0
    for key in _BOX_WRITE_KEYS:
        if key in ("x1", "y1", "x2", "y2", "element"):
            continue
        if key not in raw or raw[key] is None:
            continue
        val = raw[key]
        if key in ("score", "gender_score", "age_score"):
            try:
                out[key] = float(val)
            except (TypeError, ValueError):
                continue
        elif key in ("class_id", "age_approx"):
            try:
                out[key] = int(val)
            except (TypeError, ValueError):
                continue
        elif key in ("gender", "age_range"):
            out[key] = str(val).strip()
        else:
            out[key] = val
    return out


def _frame_match_key(topic: str, camera: str | None, timestamp_ns: int) -> tuple[str, int]:
    cam = (camera or "").strip() or _camera_from_topic(topic)
    return (cam, int(timestamp_ns))


def _topic_for_camera(camera: str, topic: str | None = None) -> str:
    t = (topic or "").strip()
    if t:
        return t
    cam = (camera or "camera0").strip() or "camera0"
    return f"/{cam}/image_raw/compressed"


def write_bboxes_jsonl(clip_id: str, run_id: str, rows: list[dict[str, Any]]) -> Path:
    """Atomically rewrite bboxes.jsonl from raw row dicts (preserves extra keys)."""
    path = resolve_bboxes_write_path(clip_id, run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
    payload = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix="bboxes_", suffix=".jsonl", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return path


def _load_raw_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def upsert_frame_boxes(
    clip_id: str,
    run_id: str,
    *,
    timestamp_ns: int,
    boxes: list[dict[str, Any]],
    topic: str | None = None,
    camera: str | None = None,
) -> dict[str, Any]:
    """Replace boxes for one (camera, timestamp_ns) frame; preserve other rows as-is."""
    path = resolve_bboxes_write_path(clip_id, run_id)
    rows = _load_raw_rows(path) if path.is_file() else []
    cam = (camera or "").strip() or _camera_from_topic(topic or "")
    if not cam:
        cam = "camera0"
    topic_resolved = _topic_for_camera(cam, topic)
    target_key = _frame_match_key(topic_resolved, cam, int(timestamp_ns))
    serialized_boxes = [_serialize_box(b) for b in boxes if isinstance(b, dict)]

    matched = False
    new_rows: list[dict[str, Any]] = []
    for row in rows:
        row_topic = str(row.get("topic") or "")
        try:
            row_ts = int(row.get("timestamp_ns") or 0)
        except (TypeError, ValueError):
            new_rows.append(row)
            continue
        row_cam = str(row.get("camera") or "") or _camera_from_topic(row_topic)
        if _frame_match_key(row_topic, row_cam, row_ts) == target_key:
            updated = dict(row)
            updated["clip_id"] = str(row.get("clip_id") or clip_id)
            updated["topic"] = row_topic or topic_resolved
            updated["timestamp_ns"] = int(timestamp_ns)
            updated["boxes"] = serialized_boxes
            if "elements" in updated:
                del updated["elements"]
            new_rows.append(updated)
            matched = True
        else:
            new_rows.append(row)

    if not matched:
        new_rows.append(
            {
                "clip_id": clip_id,
                "topic": topic_resolved,
                "timestamp_ns": int(timestamp_ns),
                "boxes": serialized_boxes,
            }
        )

    write_bboxes_jsonl(clip_id, run_id, new_rows)
    frames = load_bbox_frames(clip_id, run_id)
    frame_out: dict[str, Any] | None = None
    for fr in frames:
        if _frame_match_key(str(fr["topic"]), str(fr["camera"]), int(fr["timestamp_ns"])) == target_key:
            frame_out = fr
            break
    return {
        "clip_id": clip_id,
        "run_id": run_id,
        "has_bboxes": bool(frames),
        "frame_count": len(frames),
        "frame": frame_out
        or {
            "clip_id": clip_id,
            "topic": topic_resolved,
            "camera": cam,
            "timestamp_ns": int(timestamp_ns),
            "boxes": [_normalize_box(b) for b in serialized_boxes],
            "box_count": len(serialized_boxes),
        },
    }
