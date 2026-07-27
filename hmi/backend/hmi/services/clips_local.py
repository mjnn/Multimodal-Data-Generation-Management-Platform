"""Clip list / timeline — local SQLite + files."""

from __future__ import annotations

import re
from typing import Any

from cachetools import TTLCache

from hmi.clip_facts import clip_label_stats, get_clip_label_view
from hmi.config import PIPELINE_STEP_ORDER, SDK_PIPELINE_STEP_ORDER, STEP_LABELS
from hmi.db import normalize_pipeline_status
from hmi.labels_sync import (
    build_sampled_timestamps_ns,
    detect_sample_sync_mode,
    enrich_label_entry,
)
from hmi.labels_util import has_label_content, labels_preview, parse_labels_json
from hmi.local import assets, store
from hmi.media.preview_manifest import (
    load_preview_manifest,
    manifest_for_api,
    sampled_timestamps_from_manifest,
)
from hmi.local.clip_context import LocalClipContext, get_dim_clip, resolve_clip_context
from hmi.services.clips import composite_id

_label_map_cache: TTLCache = TTLCache(maxsize=32, ttl=300)


def label_map_cache_clear() -> None:
    _label_map_cache.clear()
    from hmi.services.overview_cache import overview_cache_clear

    overview_cache_clear()


def _ctx_key(ctx: LocalClipContext) -> str:
    return f"{ctx.clip_id}|{ctx.run_id}|{ctx.ds}"


def _w_params(ctx: LocalClipContext) -> tuple[str, str, str]:
    return ctx.clip_id, ctx.run_id, ctx.ds


def _step_order_for_ids(step_ids: set[str]) -> tuple[str, ...]:
    if step_ids & set(SDK_PIPELINE_STEP_ORDER):
        return SDK_PIPELINE_STEP_ORDER
    return PIPELINE_STEP_ORDER


def _pending_steps(step_ids: set[str] | None = None) -> list[dict[str, Any]]:
    order = _step_order_for_ids(step_ids or set())
    return [
        {"step_id": sid, "label": STEP_LABELS.get(sid, sid), "status": "pending"}
        for sid in order
        if sid != "job0_discover" and sid != "sdk_discover"
    ]


def _clip_counts(ctx: LocalClipContext) -> dict[str, Any]:
    cid, rid, ds = _w_params(ctx)
    row = store.query_one(
        "SELECT "
        "(SELECT COUNT(*) FROM fact_frame WHERE clip_id=? AND run_id=? AND ds=?) AS frame_count, "
        "(SELECT COUNT(*) FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=?) AS asr_count, "
        "(SELECT COUNT(*) FROM fact_event WHERE clip_id=? AND run_id=? AND ds=?) AS event_count",
        (cid, rid, ds, cid, rid, ds, cid, rid, ds),
    )
    assert row is not None
    label_stats = clip_label_stats(cid, rid, ds=ds)
    return {
        "frame_count": int(row["frame_count"]),
        "sampled_count": int(label_stats["sampled_count"]),
        "labeled_count": int(label_stats["labeled_count"]),
        "asr_segment_count": int(row["asr_count"]),
        "event_count": int(row["event_count"]),
        "label_granularity": label_stats["label_granularity"],
        "clip_label_ready": label_stats["clip_label_ready"],
        "clip_label_preview": label_stats["clip_label_preview"],
    }


def get_clip_stats(clip_id: str, run_id: str | None = None) -> dict[str, int]:
    ctx = resolve_clip_context(clip_id, run_id)
    return _clip_counts(ctx)


def batch_all_clip_stats(*, refresh: bool = False) -> dict[str, dict[str, int]]:
    from hmi.services.overview_cache import cached_overview_stats

    return cached_overview_stats("local", refresh=refresh, build=_batch_all_clip_stats_impl)


def _batch_all_clip_stats_impl() -> dict[str, dict[str, int]]:
    rows = store.query("SELECT clip_id, active_run_id FROM dim_clip")
    out: dict[str, dict[str, int]] = {}
    clip_runs: list[tuple[str, str]] = []
    for row in rows:
        clip_id = str(row["clip_id"])
        run_id = str(row.get("active_run_id") or "")
        if not run_id:
            continue
        try:
            out[clip_id] = get_clip_stats(clip_id, run_id)
            clip_runs.append((clip_id, run_id))
        except Exception:
            continue

    if clip_runs:
        from hmi.review.clip_review_summary import batch_clip_review_summaries

        review_map = batch_clip_review_summaries(clip_runs)
        for clip_id, review in review_map.items():
            if clip_id in out:
                out[clip_id] = {**out[clip_id], **review}
    return out


def list_demo_clips() -> list[dict[str, Any]]:
    """Return demo clip rows only (not real_data imports)."""
    rows = store.query(
        "SELECT clip_id FROM dim_clip WHERE clip_id LIKE 'sha256:demo_%' "
        "ORDER BY clip_dir_name ASC"
    )
    out: list[dict[str, Any]] = []
    for row in rows:
        clip_id = str(row["clip_id"])
        try:
            out.append(get_clip_overview(clip_id))
        except Exception:
            continue
    return out


def _latest_run_ds_map(pairs: list[tuple[str, str]]) -> dict[tuple[str, str], str]:
    if not pairs:
        return {}
    out: dict[tuple[str, str], str] = {}
    for clip_id, run_id in pairs:
        row = store.query_one(
            "SELECT ds FROM pipeline_run WHERE clip_id=? AND run_id=? ORDER BY ds DESC LIMIT 1",
            (clip_id, run_id),
        )
        if row and row.get("ds"):
            out[(clip_id, run_id)] = str(row["ds"])
    return out


def _batch_steps_by_run(run_ids: list[str]) -> dict[str, dict[str, str]]:
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    rows = store.query(
        f"SELECT run_id, ds, step_id, status FROM pipeline_step WHERE run_id IN ({placeholders})",
        tuple(run_ids),
    )
    by_run: dict[str, dict[str, str]] = {}
    for r in rows:
        rid = str(r["run_id"])
        sid = str(r["step_id"])
        by_run.setdefault(rid, {})[sid] = normalize_pipeline_status(str(r["status"]))
    return by_run


def _light_label_fields(labels_json_raw: str | None) -> tuple[bool, str, str]:
    if not labels_json_raw or not has_label_content(parse_labels_json(labels_json_raw)):
        return False, "", "frame"
    parsed = parse_labels_json(labels_json_raw)
    return True, labels_preview(parsed), "clip"


def list_clips_light(*, refresh: bool = False) -> list[dict[str, Any]]:
    from hmi.services.overview_cache import cached_overview_list

    return cached_overview_list("local", refresh=refresh, build=_list_clips_light_impl)


def _list_clips_light_impl() -> list[dict[str, Any]]:
    rows = store.query(
        "SELECT clip_id, clip_dir_name, bag_oss_key, active_run_id FROM dim_clip "
        "ORDER BY CASE WHEN clip_dir_name LIKE 'demo_%' OR clip_dir_name LIKE '[演示]%' "
        "OR clip_dir_name LIKE '[真实]%' THEN 0 ELSE 1 END, clip_dir_name ASC"
    )
    pairs: list[tuple[str, str]] = []
    for row in rows:
        rid = str(row.get("active_run_id") or "")
        if rid:
            pairs.append((str(row["clip_id"]), rid))

    ds_map = _latest_run_ds_map(pairs)
    run_ids = sorted({rid for _, rid in pairs})
    step_map = _batch_steps_by_run(run_ids)

    parse_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    for clip_id, run_id in pairs:
        ds = ds_map.get((clip_id, run_id))
        if not ds:
            continue
        key = (clip_id, run_id, ds)
        if key not in parse_cache:
            summary = store.query_one(
                "SELECT start_time_ns, end_time_ns, duration_sec FROM clip_parse_summary "
                "WHERE clip_id=? AND run_id=? AND ds=? LIMIT 1",
                (clip_id, run_id, ds),
            )
            parse_cache[key] = dict(summary) if summary else {}

    counts_cache: dict[tuple[str, str, str], dict[str, int]] = {}
    for clip_id, run_id in pairs:
        ds = ds_map.get((clip_id, run_id))
        if not ds:
            continue
        key = (clip_id, run_id, ds)
        if key in counts_cache:
            continue
        row = store.query_one(
            "SELECT "
            "(SELECT COUNT(*) FROM fact_frame WHERE clip_id=? AND run_id=? AND ds=?) AS frame_count, "
            "(SELECT COUNT(*) FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=?) AS asr_count, "
            "(SELECT COUNT(*) FROM fact_event WHERE clip_id=? AND run_id=? AND ds=?) AS event_count",
            (clip_id, run_id, ds, clip_id, run_id, ds, clip_id, run_id, ds),
        )
        counts_cache[key] = {
            "frame_count": int(row["frame_count"]) if row else 0,
            "asr_segment_count": int(row["asr_count"]) if row else 0,
            "event_count": int(row["event_count"]) if row else 0,
        }

    label_cache: dict[tuple[str, str, str], tuple[bool, str, str]] = {}
    for clip_id, run_id in pairs:
        ds = ds_map.get((clip_id, run_id))
        if not ds:
            continue
        key = (clip_id, run_id, ds)
        if key in label_cache:
            continue
        lab = store.query_one(
            "SELECT labels_json FROM fact_clip_label WHERE clip_id=? AND run_id=? AND ds=? LIMIT 1",
            (clip_id, run_id, ds),
        )
        raw = str(lab["labels_json"]) if lab and lab.get("labels_json") else None
        label_cache[key] = _light_label_fields(raw)

    status_cache: dict[tuple[str, str, str], str] = {}
    for clip_id, run_id in pairs:
        ds = ds_map.get((clip_id, run_id))
        if not ds:
            continue
        key = (clip_id, run_id, ds)
        if key in status_cache:
            continue
        run_row = store.query_one(
            "SELECT status FROM pipeline_run WHERE clip_id=? AND run_id=? AND ds=? LIMIT 1",
            (clip_id, run_id, ds),
        )
        status_cache[key] = str(run_row["status"]) if run_row else "pending"

    out: list[dict[str, Any]] = []
    for row in rows:
        clip_id = str(row["clip_id"])
        run_id = str(row.get("active_run_id") or "")
        item: dict[str, Any] = {
            "clip_id": clip_id,
            "clip_dir_name": str(row.get("clip_dir_name") or clip_id[:24]),
            "bag_oss_key": str(row.get("bag_oss_key") or ""),
            "active_run_id": run_id,
            "duration_sec": 0.0,
            "start_time_ns": 0,
            "end_time_ns": 0,
            "pipeline_status": "pending",
            "steps": _pending_steps(),
            "frame_count": 0,
            "sampled_count": 1,
            "labeled_count": 0,
            "asr_segment_count": 0,
            "event_count": 0,
            "label_granularity": "frame",
            "clip_label_ready": False,
            "clip_label_preview": "",
        }
        if not run_id:
            out.append(item)
            continue
        ds = ds_map.get((clip_id, run_id))
        if not ds:
            out.append(item)
            continue
        key = (clip_id, run_id, ds)
        summary = parse_cache.get(key) or {}
        if summary:
            item["start_time_ns"] = int(summary.get("start_time_ns") or 0)
            item["end_time_ns"] = int(summary.get("end_time_ns") or 0)
            item["duration_sec"] = float(summary.get("duration_sec") or 0.0)
        item["pipeline_status"] = status_cache.get(key, "pending")
        steps_for_run = step_map.get(run_id, {})
        step_order = _step_order_for_ids(set(steps_for_run.keys()))
        item["steps"] = [
            {
                "step_id": sid,
                "label": STEP_LABELS.get(sid, sid),
                "status": steps_for_run.get(sid, "pending"),
            }
            for sid in step_order
            if sid not in ("job0_discover", "sdk_discover")
        ]
        counts = counts_cache.get(key) or {}
        item["frame_count"] = counts.get("frame_count", 0)
        item["asr_segment_count"] = counts.get("asr_segment_count", 0)
        item["event_count"] = counts.get("event_count", 0)
        ready, preview, gran = label_cache.get(key, (False, "", "frame"))
        item["clip_label_ready"] = ready
        item["clip_label_preview"] = preview
        item["label_granularity"] = gran
        item["labeled_count"] = 1 if ready else 0
        out.append(item)
    return out


def list_clips() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in store.query("SELECT clip_id FROM dim_clip"):
        clip_id = str(row["clip_id"])
        try:
            out.append(get_clip_overview(clip_id))
        except Exception:
            continue
    return out


def get_clip_overview(
    clip_id: str, run_id: str | None = None, *, ctx: LocalClipContext | None = None
) -> dict[str, Any]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    stats = _clip_counts(ctx)
    cid, rid, ds = _w_params(ctx)
    run_row = store.query_one(
        "SELECT status FROM pipeline_run WHERE clip_id=? AND run_id=? AND ds=? LIMIT 1",
        (cid, rid, ds),
    )
    pipeline_status = str(run_row["status"]) if run_row else "pending"
    step_rows = store.query(
        "SELECT step_id, status FROM pipeline_step WHERE run_id=? AND ds=?", (rid, ds)
    )
    step_map = {str(r["step_id"]): normalize_pipeline_status(str(r["status"])) for r in step_rows}
    step_order = _step_order_for_ids(set(step_map.keys()))
    steps = [
        {
            "step_id": sid,
            "label": STEP_LABELS.get(sid, sid),
            "status": step_map.get(sid, "pending"),
        }
        for sid in step_order
        if sid not in ("job0_discover", "sdk_discover")
    ]
    return {
        "clip_id": ctx.clip_id,
        "clip_dir_name": ctx.clip_dir_name,
        "bag_oss_key": ctx.bag_oss_key,
        "active_run_id": ctx.run_id,
        "duration_sec": ctx.duration_sec,
        "start_time_ns": ctx.start_time_ns,
        "end_time_ns": ctx.end_time_ns,
        "pipeline_status": pipeline_status,
        "steps": steps,
        "frame_count": stats["frame_count"],
        "sampled_count": stats["sampled_count"],
        "labeled_count": stats["labeled_count"],
        "asr_segment_count": stats["asr_segment_count"],
        "event_count": stats["event_count"],
        "label_granularity": stats["label_granularity"],
        "clip_label_ready": stats["clip_label_ready"],
        "clip_label_preview": stats["clip_label_preview"],
    }


def list_clip_runs(clip_id: str) -> list[dict[str, Any]]:
    dim = get_dim_clip(clip_id)
    active = str(dim.get("active_run_id") or "")
    rows = store.query(
        "SELECT run_id, status, started_at FROM pipeline_run WHERE clip_id=? "
        "ORDER BY started_at DESC",
        (clip_id,),
    )
    seen: set[str] = set()
    runs: list[dict[str, Any]] = []
    for r in rows:
        rid = str(r["run_id"])
        if rid in seen:
            continue
        seen.add(rid)
        runs.append(
            {
                "run_id": rid,
                "status": str(r["status"]),
                "is_active": rid == active,
                "started_at": str(r.get("started_at") or ""),
            }
        )
    return runs


def get_explorer_bootstrap(clip_id: str, run_id: str | None = None) -> dict[str, Any]:
    ctx = resolve_clip_context(clip_id, run_id)
    _label_map(ctx)
    return {
        "clip": get_clip_overview(clip_id, ctx.run_id, ctx=ctx),
        "runs": list_clip_runs(clip_id),
        "meta": get_timeline_meta(clip_id, ctx.run_id, ctx=ctx),
    }


def _cameras_for_clip(clip_id: str, run_id: str, ds: str) -> list[str]:
    rows = store.query(
        "SELECT DISTINCT camera FROM fact_frame WHERE clip_id=? AND run_id=? AND ds=? ORDER BY camera",
        (clip_id, run_id, ds),
    )
    return [str(r["camera"]) for r in rows]


def get_timeline_meta(
    clip_id: str, run_id: str | None = None, *, ctx: LocalClipContext | None = None
) -> dict[str, Any]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    cid, rid, ds = _w_params(ctx)
    clip_view = get_clip_label_view(cid, rid, ds=ds)
    preview_doc = load_preview_manifest(cid, rid)
    preview_api = manifest_for_api(cid, rid, preview_doc) if preview_doc else None
    label_rows = store.query(
        "SELECT frame_id, timestamp_ns, sync_group_id, anchor_timestamp_ns, label_scope "
        "FROM fact_image_label WHERE clip_id=? AND run_id=? AND ds=?",
        (cid, rid, ds),
    )
    if clip_view.get("label_granularity") == "clip" and clip_view.get("clip_label_ready"):
        if preview_doc:
            sampled_ts = sampled_timestamps_from_manifest(preview_doc)
        else:
            frame_ts_rows = store.query(
                "SELECT DISTINCT timestamp_ns FROM fact_frame "
                "WHERE clip_id=? AND run_id=? AND ds=? ORDER BY timestamp_ns",
                (cid, rid, ds),
            )
            if frame_ts_rows:
                sampled_ts = [int(r["timestamp_ns"]) for r in frame_ts_rows]
            elif clip_view.get("anchor_timestamp_ns") is not None:
                sampled_ts = [int(clip_view["anchor_timestamp_ns"])]
            else:
                sampled_ts = []
        sync_mode = "clip"
    elif preview_doc:
        sampled_ts = sampled_timestamps_from_manifest(preview_doc)
        sync_mode = "clip"
    else:
        sampled_ts = build_sampled_timestamps_ns(label_rows)
        sync_mode = detect_sample_sync_mode(label_rows)
    cameras = _cameras_for_clip(cid, rid, ds)
    if preview_doc and isinstance(preview_doc.get("cameras"), dict):
        cameras = sorted(preview_doc["cameras"].keys()) or cameras
    return {
        "sampled_timestamps_ns": sampled_ts,
        "sample_sync_mode": sync_mode,
        "cameras": cameras,
        "preview": preview_api,
        "events": get_events(clip_id, ctx.run_id, ctx=ctx),
        "asr_segments": get_audio_segments(clip_id, ctx.run_id, ctx=ctx),
        "clip_label": clip_view if clip_view.get("clip_label_ready") else None,
    }


def _label_map(ctx: LocalClipContext) -> dict[str, dict[str, Any]]:
    key = _ctx_key(ctx)
    if key in _label_map_cache:
        return _label_map_cache[key]
    cid, rid, ds = _w_params(ctx)
    clip_view = get_clip_label_view(cid, rid, ds=ds)
    if clip_view.get("label_granularity") == "clip":
        _label_map_cache[key] = {}
        return _label_map_cache[key]
    rows = store.query(
        "SELECT frame_id, timestamp_ns, labels_json, sync_group_id, "
        "anchor_timestamp_ns, label_scope FROM fact_image_label "
        "WHERE clip_id=? AND run_id=? AND ds=?",
        (cid, rid, ds),
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        frame_id = str(r["frame_id"])
        labels_json = parse_labels_json(r.get("labels_json"))
        preview = labels_preview(labels_json)
        out[frame_id] = enrich_label_entry(
            r,
            labels_json=labels_json,
            preview=preview,
            has_label=has_label_content(labels_json),
        )
    _label_map_cache[key] = out
    return out


def _frames_at_timestamp(
    cid: str,
    rid: str,
    ds: str,
    timestamp_ns: int,
    window_ns: int,
) -> list[dict[str, Any]]:
    lo = timestamp_ns - window_ns
    hi = timestamp_ns + window_ns
    in_window = store.query(
        "SELECT camera, frame_idx, timestamp_ns, image_path FROM fact_frame "
        "WHERE clip_id=? AND run_id=? AND ds=? AND timestamp_ns>=? AND timestamp_ns<=?",
        (cid, rid, ds, lo, hi),
    )
    if in_window:
        return in_window
    all_rows = store.query(
        "SELECT camera, frame_idx, timestamp_ns, image_path FROM fact_frame "
        "WHERE clip_id=? AND run_id=? AND ds=?",
        (cid, rid, ds),
    )
    if not all_rows:
        return []
    best: dict[str, dict[str, Any]] = {}
    for r in all_rows:
        cam = str(r["camera"])
        ts = int(r["timestamp_ns"])
        dist = abs(ts - timestamp_ns)
        prev = best.get(cam)
        if prev is None or dist < int(prev["_dist"]):
            best[cam] = {**dict(r), "_dist": dist}
    return [{k: v for k, v in row.items() if k != "_dist"} for row in best.values()]


def get_timeline_at(
    clip_id: str,
    timestamp_ns: int,
    window_ms: int = 200,
    run_id: str | None = None,
) -> dict[str, Any]:
    ctx = resolve_clip_context(clip_id, run_id)
    cid, rid, ds = _w_params(ctx)
    clip_view = get_clip_label_view(cid, rid, ds=ds)
    preview_doc = load_preview_manifest(cid, rid)
    if preview_doc:
        window_ns = window_ms * 1_000_000
        asr_row = store.query_one(
            "SELECT segment_id, start_ns, end_ns, asr_text, confidence, audio_relpath "
            "FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=? "
            "AND start_ns<=? AND end_ns>=? LIMIT 1",
            (cid, rid, ds, timestamp_ns, timestamp_ns),
        )
        audio_segment = None
        if asr_row:
            audio_segment = {
                "segment_id": int(asr_row["segment_id"]),
                "start_ns": int(asr_row["start_ns"]),
                "end_ns": int(asr_row["end_ns"]),
                "asr_text": str(asr_row.get("asr_text") or ""),
                "confidence": float(asr_row.get("confidence") or 0),
            }
            rel = str(asr_row.get("audio_relpath") or "")
            if rel:
                audio_segment["audio_url"] = assets.local_audio_url(ctx.clip_id, ctx.run_id, rel)
        event_rows = store.query(
            "SELECT timestamp_ns, event_data FROM fact_event "
            "WHERE clip_id=? AND run_id=? AND ds=? AND timestamp_ns>=? AND timestamp_ns<=?",
            (cid, rid, ds, timestamp_ns - window_ns * 5, timestamp_ns + window_ns * 5),
        )
        clip_native = clip_view.get("label_granularity") == "clip" and clip_view.get(
            "clip_label_ready"
        )
        return {
            "timestamp_ns": timestamp_ns,
            "frames": [],
            "audio_segment": audio_segment,
            "events": [_parse_event(r) for r in event_rows],
            "clip_label": clip_view if clip_native else None,
            "preview_mode": "mp4",
        }
    window_ns = window_ms * 1_000_000
    frame_rows = _frames_at_timestamp(cid, rid, ds, timestamp_ns, window_ns)
    labels = _label_map(ctx)
    clip_native = clip_view.get("label_granularity") == "clip" and clip_view.get("clip_label_ready")
    anchor_ns = clip_view.get("anchor_timestamp_ns")
    frames: list[dict[str, Any]] = []
    for r in frame_rows:
        camera = str(r["camera"])
        frame_idx = int(r["frame_idx"])
        frame_id = f"{camera}:{frame_idx}"
        label_info = labels.get(frame_id, {})
        image_path = str(r["image_path"])
        ts = int(r["timestamp_ns"])
        frame_out: dict[str, Any] = {
            "composite_id": composite_id(ctx.clip_id, ctx.run_id, camera, frame_idx),
            "clip_id": ctx.clip_id,
            "run_id": ctx.run_id,
            "camera": camera,
            "frame_idx": frame_idx,
            "timestamp_ns": ts,
            "image_url": assets.local_image_url(ctx.clip_id, ctx.run_id, image_path),
            "is_sampled": frame_id in labels if not clip_native else False,
            "has_label": label_info.get("has_label", False),
            "label_preview": label_info.get("label_preview"),
            "labels_json": label_info.get("labels_json"),
        }
        if clip_native:
            near_anchor = (
                anchor_ns is not None and abs(ts - int(anchor_ns)) <= window_ns
            )
            if near_anchor:
                frame_out["has_label"] = True
                frame_out["label_preview"] = clip_view.get("label_preview")
                frame_out["labels_json"] = clip_view.get("labels_json")
                frame_out["anchor_timestamp_ns"] = anchor_ns
                frame_out["label_scope"] = "clip"
                frame_out["is_sync_group"] = False
        elif label_info:
            for k in (
                "sync_group_id",
                "anchor_timestamp_ns",
                "label_scope",
                "is_sync_group",
            ):
                if k in label_info:
                    frame_out[k] = label_info[k]
        frames.append(frame_out)
    asr_row = store.query_one(
        "SELECT segment_id, start_ns, end_ns, asr_text, confidence, audio_relpath "
        "FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=? "
        "AND start_ns<=? AND end_ns>=? LIMIT 1",
        (cid, rid, ds, timestamp_ns, timestamp_ns),
    )
    audio_segment = None
    if asr_row:
        audio_segment = {
            "segment_id": int(asr_row["segment_id"]),
            "start_ns": int(asr_row["start_ns"]),
            "end_ns": int(asr_row["end_ns"]),
            "asr_text": str(asr_row.get("asr_text") or ""),
            "confidence": float(asr_row.get("confidence") or 0),
        }
        rel = str(asr_row.get("audio_relpath") or "")
        if rel:
            audio_segment["audio_url"] = assets.local_audio_url(ctx.clip_id, ctx.run_id, rel)
    event_rows = store.query(
        "SELECT timestamp_ns, event_data FROM fact_event "
        "WHERE clip_id=? AND run_id=? AND ds=? AND timestamp_ns>=? AND timestamp_ns<=?",
        (cid, rid, ds, timestamp_ns - window_ns * 5, timestamp_ns + window_ns * 5),
    )
    return {
        "timestamp_ns": timestamp_ns,
        "frames": frames,
        "audio_segment": audio_segment,
        "events": [_parse_event(r) for r in event_rows],
        "clip_label": clip_view if clip_native else None,
    }


def _parse_event(row: dict[str, Any]) -> dict[str, Any]:
    data = str(row.get("event_data") or "")
    parsed = None
    m = re.search(r"_(?:event_)?([^_]+)$", data)
    if m:
        parsed = m.group(1)
    return {
        "timestamp_ns": int(row["timestamp_ns"]),
        "event_data": data,
        "parsed_label": parsed,
    }


def get_events(
    clip_id: str, run_id: str | None = None, *, ctx: LocalClipContext | None = None
) -> list[dict[str, Any]]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    cid, rid, ds = _w_params(ctx)
    rows = store.query(
        "SELECT timestamp_ns, event_data FROM fact_event "
        "WHERE clip_id=? AND run_id=? AND ds=? ORDER BY timestamp_ns",
        (cid, rid, ds),
    )
    return [_parse_event(r) for r in rows]


def get_audio_segments(
    clip_id: str, run_id: str | None = None, *, ctx: LocalClipContext | None = None
) -> list[dict[str, Any]]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    cid, rid, ds = _w_params(ctx)
    rows = store.query(
        "SELECT segment_id, start_ns, end_ns, asr_text, confidence, audio_relpath "
        "FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=? ORDER BY start_ns",
        (cid, rid, ds),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        seg: dict[str, Any] = {
            "segment_id": int(r["segment_id"]),
            "start_ns": int(r["start_ns"]),
            "end_ns": int(r["end_ns"]),
            "asr_text": str(r.get("asr_text") or ""),
            "confidence": float(r.get("confidence") or 0),
        }
        rel = str(r.get("audio_relpath") or "")
        if rel:
            seg["audio_url"] = assets.local_audio_url(ctx.clip_id, ctx.run_id, rel)
        out.append(seg)
    return out
