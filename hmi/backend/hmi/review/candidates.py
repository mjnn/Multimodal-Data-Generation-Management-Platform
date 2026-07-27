"""Label-centric review task candidates from AI clip labels."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from hmi.app_db import db_conn
from hmi.clip_facts import get_clip_label_view, list_clip_label_candidates
from hmi.labels_util import labels_preview, match_label_filters, parse_labels_json
from hmi.local import store
from hmi.local.clip_context import get_dim_clip, resolve_ds_for_run
from hmi.review_db import _review_row
REVIEW_SCOPES = frozenset({"all", "pending_review", "reviewed", "unreviewed"})


def _parse_label_filters(raw: str | None) -> dict[str, Any] | None:
    if not raw or not raw.strip():
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid label_filters JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("label_filters must be a JSON object")
    cleaned = {
        str(k).strip(): v
        for k, v in parsed.items()
        if str(k).strip() and v is not None and v != ""
    }
    return cleaned or None


def _clip_dir_name(clip_id: str) -> str:
    row = store.query_one(
        "SELECT clip_dir_name FROM dim_clip WHERE clip_id=? LIMIT 1",
        (clip_id,),
    )
    if row and row.get("clip_dir_name"):
        return str(row["clip_dir_name"])
    return clip_id[:24]


def _review_index() -> dict[tuple[str, str], dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM clip_label_review").fetchall()
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        review = _review_row(row)
        out[(str(review["clip_id"]), str(review["run_id"]))] = review
    return out


def _active_run_id(clip_id: str) -> str:
    try:
        return str(get_dim_clip(clip_id).get("active_run_id") or "").strip()
    except ValueError:
        return ""


def _run_preference_key(item: dict[str, Any], active_run: str) -> tuple[Any, ...]:
    run = str(item.get("run_id") or "")
    in_queue = bool(item.get("in_queue"))
    review_status = item.get("review_status")
    return (
        1 if run == active_run else 0,
        1 if in_queue else 0,
        1 if review_status == "pending_review" else 0,
        run,
    )


def _dedupe_candidates_by_clip(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per clip_id: prefer active_run, then in-queue pending review."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        groups[str(item["clip_id"])].append(item)
    out: list[dict[str, Any]] = []
    for clip_id, group in groups.items():
        active = _active_run_id(clip_id)
        out.append(max(group, key=lambda item: _run_preference_key(item, active)))
    return out

def list_review_task_candidates(
    *,
    label_filters: dict[str, Any] | None,
    review_scope: str = "all",
    disputes_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Return AI-labeled clips matching label_filters for taxonomy-centric review tasks."""
    if review_scope not in REVIEW_SCOPES:
        raise ValueError(f"invalid review_scope: {review_scope}")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    if not label_filters:
        return [], 0

    reviews = _review_index()
    matched: list[dict[str, Any]] = []

    for pair in list_clip_label_candidates():
        clip_id = str(pair["clip_id"])
        run_id = str(pair["run_id"])
        try:
            ds = resolve_ds_for_run(clip_id, run_id)
        except ValueError:
            continue
        view = get_clip_label_view(clip_id, run_id, ds=ds)
        if not view.get("clip_label_ready"):
            continue
        labels_json = view.get("labels_json") or {}
        if not match_label_filters(labels_json, label_filters):
            continue

        review = reviews.get((clip_id, run_id))
        review_status = str(review["review_status"]) if review else None

        if review_scope == "pending_review" and review_status != "pending_review":
            continue
        if review_scope == "reviewed" and review_status != "reviewed":
            continue
        if review_scope == "unreviewed" and review_status == "reviewed":
            continue

        preview = str(view.get("label_preview") or "")
        if not preview and labels_json:
            preview = labels_preview(parse_labels_json(labels_json))

        disputed_ids = list(view.get("disputed_label_ids") or [])
        d_count = int(view.get("dispute_count") or 0)
        if d_count == 0 and disputed_ids:
            d_count = len(disputed_ids)

        if disputes_only and d_count == 0:
            continue

        matched.append(
            {
                "clip_id": clip_id,
                "run_id": run_id,
                "clip_dir_name": _clip_dir_name(clip_id),
                "labels_json": labels_json,
                "label_preview": preview,
                "label_granularity": view.get("label_granularity") or "clip",
                "review_status": review_status,
                "review_id": review["id"] if review else None,
                "in_queue": review is not None,
                "disputed_label_ids": disputed_ids,
                "dispute_count": d_count,
                "multi_ai_gate": view.get("multi_ai_gate"),
                "label_consensus": view.get("label_consensus") or {},
            }
        )

    matched = _dedupe_candidates_by_clip(matched)
    matched.sort(
        key=lambda r: (
            -int(r.get("dispute_count") or 0),
            r.get("clip_dir_name") or "",
            r["clip_id"],
        )
    )
    total = len(matched)
    return matched[offset : offset + limit], total


def parse_label_filters_param(raw: str | None) -> dict[str, Any] | None:
    return _parse_label_filters(raw)
