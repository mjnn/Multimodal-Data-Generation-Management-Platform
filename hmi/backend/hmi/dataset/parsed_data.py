"""Fetch Job1 parsed artifacts for dataset export."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from hmi.data_source import artifact_path, safe_clip_dir
from hmi.frame_paths import normalize_image_path, strip_run_prefix
from hmi.local import store
from hmi.local.clip_context import resolve_clip_context
from hmi.oss_paths import clip_run_prefix
from hmi.services.clips_local import _parse_event

PARSED_JSONL_NAME = "解析数据.jsonl"

# Text/JSON parsed artifacts copied into dataset.zip (when present locally or on OSS).
PARSED_ARTIFACT_RELS: tuple[str, ...] = (
    "parsed/manifest.json",
    "parsed/events.jsonl",
    "parsed/job1_mc_payload.json",
    "parsed/output/audio/chunks.jsonl",
    "parsed/output/audio/audio_info.json",
    "aligned/timeline.json",
    "aligned/sync_manifest.jsonl",
)

# Binary parsed artifacts (images/audio) included when available under run root.
PARSED_BINARY_PREFIXES: tuple[str, ...] = (
    "parsed/output/images/",
    "parsed/output/audio/",
)


def _parse_summary(clip_id: str, run_id: str, ds: str) -> dict[str, Any] | None:
    row = store.query_one(
        "SELECT start_time_ns, end_time_ns, duration_sec FROM clip_parse_summary "
        "WHERE clip_id=? AND run_id=? AND ds=? LIMIT 1",
        (clip_id, run_id, ds),
    )
    if not row:
        return None
    return {
        "start_time_ns": int(row["start_time_ns"] or 0),
        "end_time_ns": int(row["end_time_ns"] or 0),
        "duration_sec": float(row["duration_sec"] or 0.0),
    }


def _fetch_frames(clip_id: str, run_id: str, ds: str) -> list[dict[str, Any]]:
    rows = store.query(
        "SELECT camera, frame_idx, timestamp_ns, image_path FROM fact_frame "
        "WHERE clip_id=? AND run_id=? AND ds=? ORDER BY timestamp_ns ASC, camera ASC, frame_idx ASC",
        (clip_id, run_id, ds),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        image_path = normalize_image_path(str(row.get("image_path") or ""))
        out.append(
            {
                "camera": str(row.get("camera") or ""),
                "frame_idx": int(row["frame_idx"]),
                "timestamp_ns": int(row["timestamp_ns"]),
                "image_path": image_path,
                "artifact_relpath": strip_run_prefix(clip_id, run_id, image_path),
            }
        )
    return out


def _fetch_events(clip_id: str, run_id: str, ds: str) -> list[dict[str, Any]]:
    rows = store.query(
        "SELECT timestamp_ns, event_data FROM fact_event "
        "WHERE clip_id=? AND run_id=? AND ds=? ORDER BY timestamp_ns",
        (clip_id, run_id, ds),
    )
    return [_parse_event(r) for r in rows]


def _fetch_audio_segments(clip_id: str, run_id: str, ds: str) -> list[dict[str, Any]]:
    rows = store.query(
        "SELECT segment_id, start_ns, end_ns, asr_text, confidence, audio_relpath "
        "FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=? ORDER BY start_ns",
        (clip_id, run_id, ds),
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        rel = normalize_image_path(str(row.get("audio_relpath") or ""))
        seg: dict[str, Any] = {
            "segment_id": int(row["segment_id"]),
            "start_ns": int(row["start_ns"]),
            "end_ns": int(row["end_ns"]),
            "asr_text": str(row.get("asr_text") or ""),
            "confidence": float(row.get("confidence") or 0),
        }
        if rel:
            seg["audio_relpath"] = rel
            seg["artifact_relpath"] = strip_run_prefix(clip_id, run_id, rel)
        out.append(seg)
    return out


def _read_local_json(rel_path: Path) -> Any | None:
    if not rel_path.is_file():
        return None
    try:
        return json.loads(rel_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def fetch_clip_parsed_json(clip_id: str, run_id: str) -> dict[str, Any]:
    """Structured parsed payload for one clip/run (frames, events, audio, summary)."""
    ctx = resolve_clip_context(clip_id, run_id)
    cid, rid, ds = ctx.clip_id, ctx.run_id, ctx.ds
    run_root = artifact_path(cid, rid, "")

    aligned_timeline = _read_local_json(run_root / "aligned" / "timeline.json")
    manifest = _read_local_json(run_root / "parsed" / "manifest.json")

    return {
        "clip_id": cid,
        "run_id": rid,
        "ds": ds,
        "parse_summary": _parse_summary(cid, rid, ds),
        "manifest": manifest,
        "frames": _fetch_frames(cid, rid, ds),
        "events": _fetch_events(cid, rid, ds),
        "audio_segments": _fetch_audio_segments(cid, rid, ds),
        "aligned": {"timeline": aligned_timeline},
    }


def clip_zip_prefix(clip_id: str, run_id: str) -> str:
    return f"clips/{safe_clip_dir(clip_id)}/runs/{run_id}/"


def _oss_text_fallback(clip_id: str, run_id: str, rel: str) -> bytes | None:
    try:
        from hmi.oss_signer import get_object_text

        key = f"{clip_run_prefix(clip_id, run_id)}{rel.lstrip('/')}"
        text = get_object_text(key)
        if text is None:
            return None
        return text.encode("utf-8")
    except Exception:
        return None


def iter_parsed_artifact_entries(clip_id: str, run_id: str) -> Iterator[tuple[str, bytes]]:
    """Yield (zip_path, payload) for parsed/aligned artifacts of one clip."""
    prefix = clip_zip_prefix(clip_id, run_id)
    run_root = artifact_path(clip_id, run_id, "")
    seen: set[str] = set()

    for rel in PARSED_ARTIFACT_RELS:
        local_path = run_root / rel.replace("/", Path.sep)
        if local_path.is_file():
            payload = local_path.read_bytes()
        else:
            payload = _oss_text_fallback(clip_id, run_id, rel)
        if payload is None:
            continue
        zip_path = f"{prefix}{rel.replace(chr(92), '/')}"
        seen.add(rel)
        yield zip_path, payload

    for bin_prefix in PARSED_BINARY_PREFIXES:
        local_dir = run_root / bin_prefix.replace("/", Path.sep)
        if not local_dir.is_dir():
            continue
        for path in sorted(local_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(run_root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            yield f"{prefix}{rel}", path.read_bytes()


def render_parsed_jsonl(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    lines = [
        json.dumps(row["parsed_json"], ensure_ascii=False)
        for row in rows
        if row.get("parsed_json") is not None
    ]
    return "\n".join(lines) + ("\n" if lines else "")


def attach_parsed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        clip_id = str(row["clip_id"])
        run_id = str(row["run_id"])
        try:
            parsed_json = fetch_clip_parsed_json(clip_id, run_id)
        except Exception:
            parsed_json = {
                "clip_id": clip_id,
                "run_id": run_id,
                "parse_summary": None,
                "manifest": None,
                "frames": [],
                "events": [],
                "audio_segments": [],
                "aligned": {"timeline": None},
            }
        enriched = dict(row)
        enriched["parsed_json"] = parsed_json
        out.append(enriched)
    return out


def collect_parsed_zip_entries(rows: list[dict[str, Any]]) -> list[tuple[str, bytes]]:
    entries: list[tuple[str, bytes]] = []
    seen_paths: set[str] = set()
    for row in rows:
        clip_id = str(row["clip_id"])
        run_id = str(row["run_id"])
        try:
            for zip_path, payload in iter_parsed_artifact_entries(clip_id, run_id):
                if zip_path in seen_paths:
                    continue
                seen_paths.add(zip_path)
                entries.append((zip_path, payload))
        except Exception:
            continue
    return entries
