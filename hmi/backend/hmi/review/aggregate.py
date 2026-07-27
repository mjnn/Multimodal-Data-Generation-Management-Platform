"""R4: aggregate fact_image_label rows to clip-level labels for review queue."""

from __future__ import annotations

from typing import Any

from hmi.labels_sync import label_row_sync_fields
from hmi.labels_util import (
    has_label_content,
    labels_preview,
    labels_to_clip_dict,
    parse_labels_json,
)
from hmi.local import store
from hmi.local.clip_context import resolve_ds_for_run


def fetch_image_label_rows(
    clip_id: str,
    run_id: str,
    *,
    ds: str | None = None,
) -> list[dict[str, Any]]:
    resolved_ds = ds or resolve_ds_for_run(clip_id, run_id)
    return store.query(
        """
        SELECT frame_id, timestamp_ns, labels_json, sync_group_id,
               anchor_timestamp_ns, label_scope
        FROM fact_image_label
        WHERE clip_id=? AND run_id=? AND ds=?
        ORDER BY timestamp_ns ASC
        """,
        (clip_id, run_id, resolved_ds),
    )


def _row_has_labels(row: dict[str, Any]) -> bool:
    return has_label_content(parse_labels_json(row.get("labels_json")))


def select_representative_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Pick representative label rows and return (rows, aggregation mode)."""
    labeled = [r for r in rows if _row_has_labels(r)]
    if not labeled:
        return [], "empty"

    sync_rows = [r for r in labeled if label_row_sync_fields(r)["is_sync_group"]]
    if sync_rows:
        groups: dict[str, list[dict[str, Any]]] = {}
        for row in sync_rows:
            sg = str(row.get("sync_group_id") or "").strip()
            if sg:
                groups.setdefault(sg, []).append(row)

        reps: list[dict[str, Any]] = []
        for _sg_id, group_rows in sorted(groups.items()):
            scope_rows = [
                r
                for r in group_rows
                if str(r.get("label_scope") or "").strip().lower() == "sync_group"
            ]
            if scope_rows:
                pick = scope_rows[0]
            else:
                pick = min(group_rows, key=lambda r: int(r["timestamp_ns"]))
            reps.append(pick)
        reps.sort(key=lambda r: int(r.get("anchor_timestamp_ns") or r["timestamp_ns"]))
        return reps, "sync_group"

    seen_frames: set[str] = set()
    reps = []
    for row in labeled:
        frame_id = str(row.get("frame_id") or "")
        if frame_id in seen_frames:
            continue
        seen_frames.add(frame_id)
        reps.append(row)
    return reps, "frame_first"


def aggregate_clip_labels(
    clip_id: str,
    run_id: str,
    *,
    ds: str | None = None,
) -> dict[str, Any]:
    """Aggregate frame/sync_group labels into clip-level review payload."""
    rows = fetch_image_label_rows(clip_id, run_id, ds=ds)
    reps, mode = select_representative_rows(rows)
    if not reps:
        raise ValueError(f"no labeled rows for {clip_id}/{run_id}")

    primary = reps[0]
    parsed_primary = parse_labels_json(primary.get("labels_json"))
    labels_json = labels_to_clip_dict(primary.get("labels_json"))
    meta = label_row_sync_fields(primary)

    summary: dict[str, Any] = {
        "source": "fact_image_label",
        "aggregation": mode,
        "total_rows": len(rows),
        "labeled_rows": sum(1 for r in rows if _row_has_labels(r)),
        "representative_count": len(reps),
        "label_preview": labels_preview(parsed_primary),
        "anchor_timestamp_ns": int(primary.get("anchor_timestamp_ns") or primary["timestamp_ns"]),
    }
    if mode == "sync_group":
        summary["sync_group_count"] = len(reps)
        summary["selected_sync_group_id"] = meta.get("sync_group_id")
    else:
        summary["selected_frame_id"] = str(primary.get("frame_id") or "")

    return {
        "labels_json": labels_json,
        "ai_source_summary_json": summary,
        "aggregation": mode,
    }
