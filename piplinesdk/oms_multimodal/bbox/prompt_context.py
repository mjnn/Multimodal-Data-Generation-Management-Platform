"""Aggregate bbox detections into concise text for Omni labeling prompts."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def _element_name(box: dict[str, Any]) -> str:
    """Prompt key for a box — includes gender/age when present (``face/female/~28y``)."""
    from .face_attrs import box_prompt_name

    return box_prompt_name(box)


def _iter_bbox_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size <= 0:
        return []
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def summarize_bboxes_for_prompt(
    bboxes_path: Path | str,
    *,
    clip_id: str | None = None,
    max_classes: int = 32,
) -> str:
    """Build a compact ``element×count (max=score)`` summary from ``bboxes.jsonl``.

    Returns empty string when the file is missing or has no boxes for the clip.
    When ``clip_id`` is None, aggregates all rows in the file.
    """
    path = Path(bboxes_path)
    counts: dict[str, int] = defaultdict(int)
    max_scores: dict[str, float] = {}

    for row in _iter_bbox_rows(path):
        if clip_id is not None and str(row.get("clip_id") or "") != str(clip_id):
            continue
        boxes = row.get("boxes") or row.get("elements") or []
        if not isinstance(boxes, list):
            continue
        for box in boxes:
            if not isinstance(box, dict):
                continue
            name = _element_name(box)
            counts[name] += 1
            score = box.get("score")
            if score is None:
                continue
            try:
                sc = float(score)
            except (TypeError, ValueError):
                continue
            prev = max_scores.get(name)
            if prev is None or sc > prev:
                max_scores[name] = sc

    if not counts:
        return ""

    # Prefer higher counts, then higher max score, then name
    ranked = sorted(
        counts.items(),
        key=lambda kv: (-kv[1], -(max_scores.get(kv[0]) or 0.0), kv[0]),
    )[: max(1, int(max_classes))]

    parts: list[str] = []
    for name, cnt in ranked:
        sc = max_scores.get(name)
        if sc is not None:
            parts.append(f"{name}×{cnt} (max={sc:.2f})")
        else:
            parts.append(f"{name}×{cnt}")
    return ", ".join(parts)


def load_bbox_context_by_clip(
    bboxes_path: Path | str,
    *,
    max_classes: int = 32,
) -> dict[str, str]:
    """Map clip_id → summary text for all clips present in ``bboxes.jsonl``."""
    path = Path(bboxes_path)
    clip_ids: set[str] = set()
    for row in _iter_bbox_rows(path):
        cid = str(row.get("clip_id") or "").strip()
        if cid:
            clip_ids.add(cid)
    out: dict[str, str] = {}
    for cid in clip_ids:
        text = summarize_bboxes_for_prompt(path, clip_id=cid, max_classes=max_classes)
        if text:
            out[cid] = text
    # Also expose an all-clips rollup under "" for single-clip runs without id match
    all_text = summarize_bboxes_for_prompt(path, clip_id=None, max_classes=max_classes)
    if all_text and not out:
        out[""] = all_text
    return out
