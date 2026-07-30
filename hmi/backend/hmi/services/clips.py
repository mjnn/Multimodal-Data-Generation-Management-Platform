"""Clip list / detail / runs / timeline."""

from __future__ import annotations

import re
from typing import Any

from cachetools import TTLCache

from hmi.clip_context import ClipContext, get_dim_clip, resolve_clip_context
from hmi.labels_sync import (
    build_sampled_timestamps_ns,
    detect_sample_sync_mode,
    enrich_label_entry,
)
from hmi.labels_util import has_label_content, labels_preview, parse_labels_json
from hmi.config import PIPELINE_STEP_ORDER, STEP_LABELS, get_settings, table_name
from hmi.db import normalize_pipeline_status, query, sql_quote
from hmi.oss_signer import sign_image

_label_map_cache: TTLCache = TTLCache(maxsize=32, ttl=600)
_frame_rows_cache: TTLCache = TTLCache(maxsize=16, ttl=600)
_timeline_meta_cache: TTLCache = TTLCache(maxsize=16, ttl=600)


def label_map_cache_clear() -> None:
    _label_map_cache.clear()
    _frame_rows_cache.clear()
    _timeline_meta_cache.clear()
    from hmi.services.overview_cache import overview_cache_clear

    overview_cache_clear()


def _or_triples(contexts: list[ClipContext]) -> str:
    if not contexts:
        return "1=0"
    return " OR ".join(
        f"(clip_id={sql_quote(c.clip_id)} AND run_id={sql_quote(c.run_id)} AND ds={sql_quote(c.ds)})"
        for c in contexts
    )


def _or_run_ds(contexts: list[ClipContext]) -> str:
    if not contexts:
        return "1=0"
    return " OR ".join(
        f"(run_id={sql_quote(c.run_id)} AND ds={sql_quote(c.ds)})" for c in contexts
    )


def _ctx_key(ctx: ClipContext) -> str:
    return f"{ctx.clip_id}|{ctx.run_id}|{ctx.ds}"


def _fmt_ts(ns: int, start_ns: int) -> str:
    rel = (ns - start_ns) / 1e9
    m = int(rel // 60)
    s = rel % 60
    return f"{m}:{s:05.2f}"


def composite_id(clip_id: str, run_id: str, camera: str, frame_idx: int) -> str:
    return f"f|{clip_id}|{run_id}|{camera}|{frame_idx}"


def parse_composite_id(cid: str) -> tuple[str, str, str, int]:
    parts = cid.split("|")
    if len(parts) != 5 or parts[0] != "f":
        raise ValueError(f"invalid composite id: {cid}")
    return parts[1], parts[2], parts[3], int(parts[4])


def _fact_where(ctx: ClipContext) -> str:
    return (
        f"clip_id={sql_quote(ctx.clip_id)} AND run_id={sql_quote(ctx.run_id)} "
        f"AND ds={sql_quote(ctx.ds)}"
    )


def _step_where(ctx: ClipContext) -> str:
    return f"run_id={sql_quote(ctx.run_id)} AND ds={sql_quote(ctx.ds)}"


def _run_where(ctx: ClipContext) -> str:
    return _fact_where(ctx)


def _pending_steps() -> list[dict[str, Any]]:
    return [
        {
            "step_id": sid,
            "label": STEP_LABELS.get(sid, sid),
            "status": "pending",
        }
        for sid in PIPELINE_STEP_ORDER
        if sid != "job0_discover"
    ]


def _clip_counts(ctx: ClipContext) -> dict[str, Any]:
    settings = get_settings()
    w = _fact_where(ctx)
    frame_tbl = table_name(settings, "fact_frame")
    clip_label_tbl = table_name(settings, "fact_clip_label")
    label_tbl = table_name(settings, "fact_image_label")
    asr_tbl = table_name(settings, "fact_audio_segment")
    event_tbl = table_name(settings, "fact_event")
    counts = query(
        f"SELECT "
        f"(SELECT COUNT(*) FROM {frame_tbl} WHERE {w}) AS frame_count, "
        f"(SELECT COUNT(*) FROM {clip_label_tbl} WHERE {w} AND labels_json IS NOT NULL "
        f"AND labels_json != '{{}}' AND labels_json != '') AS clip_labeled_count, "
        f"(SELECT COUNT(*) FROM {label_tbl} WHERE {w} AND labels_json IS NOT NULL "
        f"AND labels_json != '{{}}' AND labels_json != '') AS frame_labeled_count, "
        f"(SELECT COUNT(*) FROM {asr_tbl} WHERE {w}) AS asr_count, "
        f"(SELECT COUNT(*) FROM {event_tbl} WHERE {w}) AS event_count"
    )[0]
    clip_labeled = int(counts["clip_labeled_count"])
    frame_labeled = int(counts["frame_labeled_count"])
    if clip_labeled > 0:
        granularity = "clip"
        labeled_count = 1
        preview_row = query(
            f"SELECT labels_json FROM {clip_label_tbl} WHERE {w} "
            f"AND labels_json IS NOT NULL AND labels_json != '{{}}' AND labels_json != '' LIMIT 1"
        )
        preview = (
            labels_preview(parse_labels_json(preview_row[0].get("labels_json")))
            if preview_row
            else ""
        )
    elif frame_labeled > 0:
        granularity = "frame"
        labeled_count = 1
        preview_row = query(
            f"SELECT labels_json FROM {label_tbl} WHERE {w} "
            f"AND labels_json IS NOT NULL AND labels_json != '{{}}' AND labels_json != '' LIMIT 1"
        )
        preview = (
            labels_preview(parse_labels_json(preview_row[0].get("labels_json")))
            if preview_row
            else ""
        )
    else:
        granularity = "frame"
        labeled_count = 0
        preview = ""
    return {
        "frame_count": int(counts["frame_count"]),
        "sampled_count": 1,
        "labeled_count": labeled_count,
        "asr_segment_count": int(counts["asr_count"]),
        "event_count": int(counts["event_count"]),
        "label_granularity": granularity,
        "clip_label_ready": labeled_count > 0,
        "clip_label_preview": preview,
    }


def get_clip_stats(clip_id: str, run_id: str | None = None) -> dict[str, int]:
    ctx = resolve_clip_context(clip_id, run_id)
    return _clip_counts(ctx)


def list_clips_light(*, refresh: bool = False) -> list[dict[str, Any]]:
    from hmi.services.overview_cache import cached_overview_list

    return cached_overview_list("cloud", refresh=refresh, build=_list_clips_light_impl)


def _list_clips_light_impl() -> list[dict[str, Any]]:
    settings = get_settings()
    dim_table = table_name(settings, "dim_clip")
    rows = query(f"SELECT clip_id, clip_dir_name, bag_oss_key, active_run_id FROM {dim_table}")
    contexts: list[ClipContext] = []
    for row in rows:
        clip_id = str(row["clip_id"])
        run_id = str(row.get("active_run_id") or "")
        if not run_id:
            continue
        try:
            contexts.append(resolve_clip_context(clip_id, run_id))
        except Exception:
            continue

    summary_by: dict[tuple[str, str], dict[str, Any]] = {}
    run_status_by: dict[tuple[str, str], str] = {}
    steps_by: dict[tuple[str, str, str], dict[str, str]] = {}
    taxonomy_id_by: dict[tuple[str, str], str] = {}

    if contexts:
        triple_where = _or_triples(contexts)
        for s in query(
            f"SELECT clip_id, run_id, start_time_ns, end_time_ns, duration_sec FROM "
            f"{table_name(settings, 'clip_parse_summary')} WHERE {triple_where}"
        ):
            summary_by[(str(s["clip_id"]), str(s["run_id"]))] = s
        for r in query(
            f"SELECT clip_id, run_id, status FROM {table_name(settings, 'pipeline_run')} "
            f"WHERE {triple_where}"
        ):
            run_status_by[(str(r["clip_id"]), str(r["run_id"]))] = str(r["status"])
        for lab in query(
            f"SELECT clip_id, run_id, taxonomy_version_id FROM "
            f"{table_name(settings, 'fact_clip_label')} WHERE {triple_where}"
        ):
            tid = str(lab.get("taxonomy_version_id") or "").strip()
            if tid:
                taxonomy_id_by[(str(lab["clip_id"]), str(lab["run_id"]))] = tid
        run_ds_where = _or_run_ds(contexts)
        for st in query(
            f"SELECT run_id, ds, step_id, status FROM "
            f"{table_name(settings, 'pipeline_step')} WHERE {run_ds_where}"
        ):
            steps_by[(str(st["run_id"]), str(st["ds"]), str(st["step_id"]))] = str(st["status"])

    from hmi.taxonomy_db import version_codes_by_ids

    code_by_id = version_codes_by_ids(set(taxonomy_id_by.values()))

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
            "sampled_count": 0,
            "labeled_count": 0,
            "asr_segment_count": 0,
            "event_count": 0,
            "taxonomy_version_id": None,
            "taxonomy_version_code": None,
        }
        if run_id:
            tid = taxonomy_id_by.get((clip_id, run_id))
            if tid:
                item["taxonomy_version_id"] = tid
                item["taxonomy_version_code"] = code_by_id.get(tid)
            summary = summary_by.get((clip_id, run_id))
            if summary:
                item["start_time_ns"] = int(summary["start_time_ns"])
                item["end_time_ns"] = int(summary["end_time_ns"])
                item["duration_sec"] = float(summary["duration_sec"])
            if (clip_id, run_id) in run_status_by:
                item["pipeline_status"] = run_status_by[(clip_id, run_id)]
            try:
                ctx = next((c for c in contexts if c.clip_id == clip_id and c.run_id == run_id), None)
                if ctx is None:
                    ctx = resolve_clip_context(clip_id, run_id)
                step_map = {
                    sid: normalize_pipeline_status(st)
                    for (rid, ds, sid), st in steps_by.items()
                    if rid == ctx.run_id and ds == ctx.ds
                }
                item["steps"] = [
                    {
                        "step_id": sid,
                        "label": STEP_LABELS.get(sid, sid),
                        "status": step_map.get(sid, "pending"),
                    }
                    for sid in PIPELINE_STEP_ORDER
                    if sid != "job0_discover"
                ]
            except Exception:
                pass
        out.append(item)
    return out


def batch_all_clip_stats(*, refresh: bool = False) -> dict[str, dict[str, int]]:
    from hmi.services.overview_cache import cached_overview_stats

    return cached_overview_stats("cloud", refresh=refresh, build=_batch_all_clip_stats_impl)


def _batch_all_clip_stats_impl() -> dict[str, dict[str, int]]:
    """One GROUP BY pass per fact table for all active clips."""
    settings = get_settings()
    dim_rows = query(
        f"SELECT clip_id, active_run_id FROM {table_name(settings, 'dim_clip')}"
    )
    contexts: list[ClipContext] = []
    for row in dim_rows:
        clip_id = str(row["clip_id"])
        run_id = str(row.get("active_run_id") or "")
        if not run_id:
            continue
        try:
            contexts.append(resolve_clip_context(clip_id, run_id))
        except Exception:
            continue
    if not contexts:
        return {}

    where = _or_triples(contexts)
    key_of = lambda r: str(r["clip_id"])

    def grouped(table_suffix: str, extra: str = "") -> dict[str, int]:
        tbl = table_name(settings, table_suffix)
        cond = f" AND {extra}" if extra else ""
        rows = query(
            f"SELECT clip_id, run_id, ds, COUNT(*) AS cnt FROM {tbl} "
            f"WHERE ({where}){cond} GROUP BY clip_id, run_id, ds"
        )
        out: dict[str, int] = {}
        ctx_by = {(c.clip_id, c.run_id, c.ds): c for c in contexts}
        for r in rows:
            ctx = ctx_by.get((str(r["clip_id"]), str(r["run_id"]), str(r["ds"])))
            if ctx:
                out[ctx.clip_id] = int(r["cnt"])
        return out

    frames = grouped("fact_frame")
    clip_labeled = grouped(
        "fact_clip_label",
        "labels_json IS NOT NULL AND labels_json != '{}' AND labels_json != ''",
    )
    frame_labeled = grouped(
        "fact_image_label",
        "labels_json IS NOT NULL AND labels_json != '{}' AND labels_json != ''",
    )
    asr = grouped("fact_audio_segment")
    events = grouped("fact_event")

    result: dict[str, dict[str, Any]] = {}
    for ctx in contexts:
        cid = ctx.clip_id
        if clip_labeled.get(cid, 0) > 0:
            granularity = "clip"
            labeled_count = 1
        elif frame_labeled.get(cid, 0) > 0:
            granularity = "frame"
            labeled_count = 1
        else:
            granularity = "frame"
            labeled_count = 0
        result[cid] = {
            "frame_count": frames.get(cid, 0),
            "sampled_count": 1,
            "labeled_count": labeled_count,
            "asr_segment_count": asr.get(cid, 0),
            "event_count": events.get(cid, 0),
            "label_granularity": granularity,
            "clip_label_ready": labeled_count > 0,
            "clip_label_preview": "",
        }

    if contexts:
        from hmi.review.clip_review_summary import batch_clip_review_summaries

        clip_runs = [(c.clip_id, c.run_id) for c in contexts]
        review_map = batch_clip_review_summaries(clip_runs)
        for cid, review in review_map.items():
            if cid in result:
                result[cid] = {**result[cid], **review}
    return result


def list_clips() -> list[dict[str, Any]]:
    settings = get_settings()
    dim_table = table_name(settings, "dim_clip")
    rows = query(f"SELECT clip_id, clip_dir_name, bag_oss_key, active_run_id FROM {dim_table}")
    out: list[dict[str, Any]] = []
    for row in rows:
        clip_id = str(row["clip_id"])
        try:
            out.append(get_clip_overview(clip_id))
        except Exception:
            continue
    return out


def get_clip_overview(
    clip_id: str,
    run_id: str | None = None,
    *,
    ctx: ClipContext | None = None,
    include_counts: bool = True,
) -> dict[str, Any]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    settings = get_settings()
    w = _fact_where(ctx)

    if include_counts:
        stats = _clip_counts(ctx)
    else:
        stats = {
            "frame_count": 0,
            "sampled_count": 1,
            "labeled_count": 0,
            "asr_segment_count": 0,
            "event_count": 0,
            "label_granularity": "frame",
            "clip_label_ready": False,
            "clip_label_preview": "",
        }

    run_rows = query(
        f"SELECT status FROM {table_name(settings, 'pipeline_run')} WHERE {w} LIMIT 1"
    )
    pipeline_status = str(run_rows[0]["status"]) if run_rows else "pending"

    step_rows = query(
        f"SELECT step_id, status FROM {table_name(settings, 'pipeline_step')} "
        f"WHERE {_step_where(ctx)}"
    )
    step_map = {str(r["step_id"]): normalize_pipeline_status(str(r["status"])) for r in step_rows}
    steps = [
        {
            "step_id": sid,
            "label": STEP_LABELS.get(sid, sid),
            "status": step_map.get(sid, "pending"),
        }
        for sid in PIPELINE_STEP_ORDER
        if sid != "job0_discover"
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
    settings = get_settings()
    dim = get_dim_clip(clip_id)
    active = str(dim.get("active_run_id") or "")
    tbl = table_name(settings, "pipeline_run")
    from hmi.clip_context import list_ds_partitions

    rows: list[dict[str, Any]] = []
    for ds in list_ds_partitions("pipeline_run"):
        rows.extend(
            query(
                f"SELECT run_id, status, started_at FROM {tbl} "
                f"WHERE ds={sql_quote(ds)} AND clip_id={sql_quote(clip_id)}"
            )
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


def _cloud_clip_label_view(ctx: ClipContext) -> dict[str, Any]:
    settings = get_settings()
    w = _fact_where(ctx)
    clip_tbl = table_name(settings, "fact_clip_label")
    rows = query(
        f"SELECT labels_json, anchor_timestamp_ns FROM {clip_tbl} WHERE {w} "
        f"AND labels_json IS NOT NULL AND labels_json != '{{}}' AND labels_json != '' LIMIT 1"
    )
    if rows:
        from hmi.labels_util import labels_to_clip_dict

        parsed = parse_labels_json(rows[0].get("labels_json"))
        anchor = rows[0].get("anchor_timestamp_ns")
        return {
            "label_granularity": "clip",
            "clip_label_ready": True,
            "labels_json": labels_to_clip_dict(rows[0].get("labels_json")),
            "label_preview": labels_preview(parsed),
            "anchor_timestamp_ns": int(anchor) if anchor is not None else None,
            "source": "fact_clip_label",
            "aggregation": "clip_native",
        }
    label_tbl = table_name(settings, "fact_image_label")
    frame_rows = query(
        f"SELECT labels_json, anchor_timestamp_ns, timestamp_ns FROM {label_tbl} WHERE {w} "
        f"AND labels_json IS NOT NULL AND labels_json != '{{}}' AND labels_json != '' "
        f"ORDER BY timestamp_ns ASC LIMIT 1"
    )
    if frame_rows:
        from hmi.labels_util import labels_to_clip_dict

        parsed = parse_labels_json(frame_rows[0].get("labels_json"))
        anchor = frame_rows[0].get("anchor_timestamp_ns") or frame_rows[0].get("timestamp_ns")
        return {
            "label_granularity": "frame",
            "clip_label_ready": True,
            "labels_json": labels_to_clip_dict(frame_rows[0].get("labels_json")),
            "label_preview": labels_preview(parsed),
            "anchor_timestamp_ns": int(anchor) if anchor is not None else None,
            "source": "fact_image_label",
            "aggregation": "frame_legacy",
        }
    return {
        "label_granularity": "frame",
        "clip_label_ready": False,
        "labels_json": {},
        "label_preview": "",
        "anchor_timestamp_ns": None,
        "source": None,
        "aggregation": None,
    }


def get_explorer_bootstrap(clip_id: str, run_id: str | None = None) -> dict[str, Any]:
    ctx = resolve_clip_context(clip_id, run_id)
    _label_map(ctx)
    return {
        "clip": get_clip_overview(clip_id, ctx.run_id, ctx=ctx),
        "runs": list_clip_runs(clip_id),
        "meta": get_timeline_meta(clip_id, ctx.run_id, ctx=ctx),
    }


def _load_frame_rows(ctx: ClipContext) -> list[dict[str, Any]]:
    key = _ctx_key(ctx)
    if key in _frame_rows_cache:
        return _frame_rows_cache[key]
    settings = get_settings()
    rows = query(
        f"SELECT camera, frame_idx, timestamp_ns, image_path FROM "
        f"{table_name(settings, 'fact_frame')} WHERE {_run_where(ctx)}"
    )
    _frame_rows_cache[key] = rows
    return rows


def get_timeline_meta(
    clip_id: str, run_id: str | None = None, *, ctx: ClipContext | None = None
) -> dict[str, Any]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    key = _ctx_key(ctx)
    if key in _timeline_meta_cache:
        return _timeline_meta_cache[key]

    settings = get_settings()
    w = _run_where(ctx)
    clip_view = _cloud_clip_label_view(ctx)
    label_rows = query(
        f"SELECT frame_id, timestamp_ns, sync_group_id, anchor_timestamp_ns, label_scope "
        f"FROM {table_name(settings, 'fact_image_label')} WHERE {w}"
    )
    event_rows = query(
        f"SELECT timestamp_ns, event_data FROM {table_name(settings, 'fact_event')} "
        f"WHERE {w} ORDER BY timestamp_ns"
    )
    asr_rows = query(
        f"SELECT segment_id, start_ns, end_ns, asr_text, confidence FROM "
        f"{table_name(settings, 'fact_audio_segment')} WHERE {w} ORDER BY start_ns"
    )
    if clip_view.get("label_granularity") == "clip" and clip_view.get("anchor_timestamp_ns"):
        sampled_ts = [int(clip_view["anchor_timestamp_ns"])]
        sync_mode = "clip"
    else:
        sampled_ts = build_sampled_timestamps_ns(label_rows)
        sync_mode = detect_sample_sync_mode(label_rows)
    meta = {
        "sampled_timestamps_ns": sampled_ts,
        "sample_sync_mode": sync_mode,
        "events": [_parse_event(r) for r in event_rows],
        "asr_segments": [
            {
                "segment_id": int(r["segment_id"]),
                "start_ns": int(r["start_ns"]),
                "end_ns": int(r["end_ns"]),
                "asr_text": str(r.get("asr_text") or ""),
                "confidence": float(r.get("confidence") or 0),
            }
            for r in asr_rows
        ],
        "clip_label": clip_view if clip_view.get("clip_label_ready") else None,
    }
    _timeline_meta_cache[key] = meta
    return meta


def _label_map(ctx: ClipContext) -> dict[str, dict[str, Any]]:
    key = _ctx_key(ctx)
    if key in _label_map_cache:
        return _label_map_cache[key]

    settings = get_settings()
    if _cloud_clip_label_view(ctx).get("label_granularity") == "clip":
        _label_map_cache[key] = {}
        return _label_map_cache[key]
    rows = query(
        f"SELECT frame_id, timestamp_ns, labels_json, sync_group_id, "
        f"anchor_timestamp_ns, label_scope FROM "
        f"{table_name(settings, 'fact_image_label')} WHERE {_run_where(ctx)}"
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


def get_timeline_at(
    clip_id: str,
    timestamp_ns: int,
    window_ms: int = 200,
    run_id: str | None = None,
) -> dict[str, Any]:
    ctx = resolve_clip_context(clip_id, run_id)
    settings = get_settings()
    window_ns = window_ms * 1_000_000
    lo = timestamp_ns - window_ns
    hi = timestamp_ns + window_ns
    meta = get_timeline_meta(clip_id, ctx.run_id, ctx=ctx)
    clip_view = meta.get("clip_label") or _cloud_clip_label_view(ctx)
    labels = _label_map(ctx)
    clip_native = clip_view.get("label_granularity") == "clip" and clip_view.get("clip_label_ready")
    anchor_ns = clip_view.get("anchor_timestamp_ns")

    frame_rows = [
        r for r in _load_frame_rows(ctx) if lo <= int(r["timestamp_ns"]) <= hi
    ]
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
            "image_url": sign_image(settings, ctx.clip_id, ctx.run_id, image_path),
            "is_sampled": frame_id in labels if not clip_native else False,
            "has_label": label_info.get("has_label", False),
            "label_preview": label_info.get("label_preview"),
            "labels_json": label_info.get("labels_json"),
        }
        if clip_native:
            if anchor_ns is not None and abs(ts - int(anchor_ns)) <= window_ns:
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

    audio_segment = None
    for seg in meta["asr_segments"]:
        if int(seg["start_ns"]) <= timestamp_ns <= int(seg["end_ns"]):
            audio_segment = seg
            break

    ev_lo = timestamp_ns - window_ns * 5
    ev_hi = timestamp_ns + window_ns * 5
    events = [
        e for e in meta["events"] if ev_lo <= int(e["timestamp_ns"]) <= ev_hi
    ]

    return {
        "timestamp_ns": timestamp_ns,
        "frames": frames,
        "audio_segment": audio_segment,
        "events": events,
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
    clip_id: str, run_id: str | None = None, *, ctx: ClipContext | None = None
) -> list[dict[str, Any]]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    return get_timeline_meta(clip_id, ctx.run_id, ctx=ctx)["events"]


def get_audio_segments(
    clip_id: str, run_id: str | None = None, *, ctx: ClipContext | None = None
) -> list[dict[str, Any]]:
    ctx = ctx or resolve_clip_context(clip_id, run_id)
    return get_timeline_meta(clip_id, ctx.run_id, ctx=ctx)["asr_segments"]


# attach formatter used by API
format_timestamp_ns = _fmt_ts
