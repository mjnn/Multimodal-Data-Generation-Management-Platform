"""uniform_sync: sync_group label scope helpers for HMI."""

from __future__ import annotations

from typing import Any


def is_sync_group_scope(label_scope: str | None, sync_group_id: str | None) -> bool:
    scope = (label_scope or "").strip().lower()
    sg = (sync_group_id or "").strip()
    if scope == "sync_group":
        return bool(sg)
    return bool(sg)


def label_row_sync_fields(row: dict[str, Any]) -> dict[str, Any]:
    sync_group_id = str(row.get("sync_group_id") or "").strip() or None
    label_scope = str(row.get("label_scope") or "").strip() or None
    anchor_raw = row.get("anchor_timestamp_ns")
    anchor_ts = int(anchor_raw) if anchor_raw not in (None, "") else None
    is_group = is_sync_group_scope(label_scope, sync_group_id)
    if is_group and not label_scope:
        label_scope = "sync_group"
    return {
        "sync_group_id": sync_group_id,
        "anchor_timestamp_ns": anchor_ts,
        "label_scope": label_scope or ("sync_group" if is_group else "frame"),
        "is_sync_group": is_group,
    }


def scene_timestamp_ns(row: dict[str, Any]) -> int:
    """Group-level scene time (anchor) or per-frame timestamp."""
    meta = label_row_sync_fields(row)
    if meta["is_sync_group"] and meta["anchor_timestamp_ns"] is not None:
        return int(meta["anchor_timestamp_ns"])
    return int(row["timestamp_ns"])


def enrich_label_entry(row: dict[str, Any], *, labels_json: Any, preview: str, has_label: bool) -> dict[str, Any]:
    meta = label_row_sync_fields(row)
    return {
        "timestamp_ns": int(row["timestamp_ns"]),
        "labels_json": labels_json,
        "label_preview": preview,
        "has_label": has_label,
        **meta,
    }


def build_sampled_timestamps_ns(rows: list[dict[str, Any]]) -> list[int]:
    """Dedupe: one anchor per sync_group; one ts per frame-scope row."""
    seen_groups: set[str] = set()
    seen_frames: set[str] = set()
    out: list[int] = []
    for row in rows:
        meta = label_row_sync_fields(row)
        if meta["is_sync_group"] and meta["sync_group_id"]:
            sg = meta["sync_group_id"]
            if sg in seen_groups:
                continue
            seen_groups.add(sg)
            out.append(scene_timestamp_ns(row))
        else:
            fid = str(row.get("frame_id") or "")
            if fid in seen_frames:
                continue
            seen_frames.add(fid)
            out.append(int(row["timestamp_ns"]))
    return sorted(out)


def detect_sample_sync_mode(rows: list[dict[str, Any]]) -> str:
    if any(label_row_sync_fields(r)["is_sync_group"] for r in rows):
        return "uniform_sync"
    return "uniform"


def dedupe_search_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        clip_id = str(row["clip_id"])
        run_id = str(row.get("run_id") or "")
        meta = label_row_sync_fields(row)
        if meta["is_sync_group"] and meta["sync_group_id"]:
            key = (clip_id, run_id, "sg", meta["sync_group_id"])
        else:
            key = (clip_id, run_id, "f", str(row.get("frame_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def aggregate_cluster_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge sync_group hits (4 cameras) into one cluster row per group."""
    if not hits:
        return []
    sync_buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    frame_hits: list[dict[str, Any]] = []
    for h in hits:
        sg = str(h.get("sync_group_id") or "").strip()
        if h.get("is_sync_group") and sg:
            key = (str(h["clip_id"]), sg)
            sync_buckets.setdefault(key, []).append(h)
        else:
            frame_hits.append(h)

    clusters: list[dict[str, Any]] = []
    for (clip_id, sg_id), group_hits in sync_buckets.items():
        first = group_hits[0]
        clusters.append(
            {
                "cluster_id": f"sg|{clip_id}|{sg_id}",
                "clip_id": clip_id,
                "timestamp_ns": int(first["timestamp_ns"]),
                "timestamp_end_ns": int(first["timestamp_ns"]),
                "label_texts": list({h["label_text"] for h in group_hits if h.get("label_text")}),
                "cameras": sorted({str(h["camera"]) for h in group_hits}),
                "preview_url": first["preview_url"],
                "hit_count": 1,
                "sync_group_id": sg_id,
                "is_sync_group": True,
            }
        )

    frame_hits.sort(key=lambda x: (x["clip_id"], x["timestamp_ns"]))
    bucket: list[dict[str, Any]] = []

    def flush_frames() -> None:
        if not bucket:
            return
        clusters.append(
            {
                "cluster_id": f"c|{bucket[0]['clip_id']}|{bucket[0]['timestamp_ns']}",
                "clip_id": bucket[0]["clip_id"],
                "timestamp_ns": int(bucket[0]["timestamp_ns"]),
                "timestamp_end_ns": int(bucket[-1]["timestamp_ns"]),
                "label_texts": list({b["label_text"] for b in bucket if b.get("label_text")}),
                "cameras": sorted({str(b["camera"]) for b in bucket}),
                "preview_url": bucket[0]["preview_url"],
                "hit_count": len(bucket),
                "sync_group_id": None,
                "is_sync_group": False,
            }
        )
        bucket.clear()

    for h in frame_hits:
        if not bucket or h["timestamp_ns"] - bucket[0]["timestamp_ns"] <= 2_000_000_000:
            bucket.append(h)
        else:
            flush_frames()
            bucket.append(h)
    flush_frames()
    clusters.sort(key=lambda x: (x["clip_id"], x["timestamp_ns"]))
    return clusters
