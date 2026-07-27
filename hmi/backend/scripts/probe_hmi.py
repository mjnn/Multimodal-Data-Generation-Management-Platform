#!/usr/bin/env python3
"""Quick HMI backend data probe after full pipeline run."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(ROOT))

from hmi.db import cache_clear
from hmi.services import clips, search
from hmi.clip_context import get_dim_clip

CLIP = "sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b"


def main() -> None:
    cache_clear()
    dim = get_dim_clip(CLIP)
    print("dim_clip.active_run_id:", dim.get("active_run_id"))
    print("dim_clip.bag_oss_key:", dim.get("bag_oss_key"))
    runs = clips.list_clip_runs(CLIP)
    print("pipeline_run count:", len(runs))
    for r in runs:
        o = clips.get_clip_overview(CLIP, r["run_id"])
        steps = ", ".join(f"{s['step_id']}:{s['status']}" for s in o["steps"])
        print(
            f"  run {r['run_id'][:8]} active={r['is_active']} "
            f"frames={o['frame_count']} sampled={o['sampled_count']} "
            f"labeled={o['labeled_count']} asr={o['asr_segment_count']} "
            f"events={o['event_count']}"
        )
        print(f"    steps: {steps}")

    active = clips.get_clip_overview(CLIP)
    if active["start_time_ns"]:
        t = active["start_time_ns"] + 5_000_000_000
        snap = clips.get_timeline_at(CLIP, t)
        print("timeline@5s frames:", len(snap["frames"]))
        if snap["frames"]:
            f0 = snap["frames"][0]
            print("  sample frame:", f0["camera"], f0["is_sampled"], f0["has_label"])
            print("  image_url ok:", f0["image_url"].startswith("https://"))
        print("  asr:", bool(snap.get("audio_segment")))
        print("  events:", len(snap.get("events") or []))

    from hmi.db import query, sql_quote
    from hmi.config import table_name, get_settings
    from hmi.clip_context import resolve_clip_context

    ctx = resolve_clip_context(CLIP)
    s = get_settings()
    w = (
        f"clip_id={sql_quote(ctx.clip_id)} AND run_id={sql_quote(ctx.run_id)} "
        f"AND ds={sql_quote(ctx.ds)}"
    )
    label_samples = query(
        f"SELECT frame_id, labels_json FROM {table_name(s, 'fact_image_label')} "
        f"WHERE {w} LIMIT 2"
    )
    print("label samples:")
    for row in label_samples:
        txt = (row.get("labels_json") or "")[:120]
        print(f"  {row['frame_id']}: {txt}")

    for kw in ("", "疲劳", "driving", "mild", "困"):
        n = len(search.search_label_clusters(kw))
        print(f"search clusters ({kw!r}):", n)

    meta = clips.get_timeline_meta(CLIP)
    print("timeline-meta sampled_ts:", len(meta["sampled_timestamps_ns"]))

    if active["start_time_ns"]:
        t2 = active["start_time_ns"] + 4_500_000_000
        snap2 = clips.get_timeline_at(CLIP, t2)
        labeled = [f for f in snap2["frames"] if f.get("has_label")]
        if labeled:
            sim = search.find_similar(labeled[0]["composite_id"], top_k=5)
            print("similar count:", len(sim))
            if sim:
                print("  top score:", sim[0]["score"], sim[0]["camera"])


if __name__ == "__main__":
    main()
