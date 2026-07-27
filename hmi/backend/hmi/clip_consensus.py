"""Multi-AI label consensus metadata for clip-level facts."""

from __future__ import annotations

import json
from typing import Any

DISPUTE_STATUSES = frozenset({"split", "minority", "tie"})


def parse_multi_ai_meta(raw: str | dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def label_consensus_entries(meta: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not meta:
        return {}
    labels = meta.get("labels")
    if not isinstance(labels, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for label_id, entry in labels.items():
        if isinstance(entry, dict):
            out[str(label_id)] = entry
    return out


def disputed_label_ids(meta: dict[str, Any] | None) -> list[str]:
    """Label IDs where multi-AI models disagreed and human review is recommended."""
    disputed: list[str] = []
    for label_id, entry in label_consensus_entries(meta).items():
        if entry.get("needs_review") is True:
            disputed.append(label_id)
            continue
        status = str(entry.get("status") or "").strip().lower()
        if status in DISPUTE_STATUSES:
            disputed.append(label_id)
    return disputed


def dispute_count(meta: dict[str, Any] | None) -> int:
    return len(disputed_label_ids(meta))


def gate_summary(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if not meta:
        return None
    gate = meta.get("gate")
    return gate if isinstance(gate, dict) else None


def attach_consensus_fields(view: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """Merge multi-AI consensus metadata into a clip label view dict."""
    if not row:
        return view
    meta = parse_multi_ai_meta(row.get("multi_ai_meta_json"))
    if not meta:
        view.setdefault("disputed_label_ids", [])
        view.setdefault("dispute_count", 0)
        view.setdefault("label_consensus", {})
        view.setdefault("multi_ai_gate", None)
        return view
    entries = label_consensus_entries(meta)
    view["multi_ai_meta"] = meta
    view["label_consensus"] = entries
    view["disputed_label_ids"] = disputed_label_ids(meta)
    view["dispute_count"] = len(view["disputed_label_ids"])
    view["multi_ai_gate"] = gate_summary(meta)
    return view


def build_multi_ai_meta(
    *,
    gate_passed: bool,
    clip_score: float,
    threshold: float,
    model_count: int,
    labels: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Helper for pipeline/seed to build consensus JSON."""
    return {
        "gate": {
            "passed": gate_passed,
            "clip_score": clip_score,
            "threshold": threshold,
            "model_count": model_count,
        },
        "labels": labels,
    }


def build_label_consensus_entry(
    *,
    output: Any,
    votes: list[dict[str, Any]],
    status: str | None = None,
    agreement: float | None = None,
    needs_review: bool | None = None,
) -> dict[str, Any]:
    """Build one label's consensus block from model votes."""
    if not votes:
        return {
            "output": output,
            "status": status or "unanimous",
            "agreement": agreement if agreement is not None else 1.0,
            "needs_review": bool(needs_review),
            "votes": [],
        }
    values = [str(v.get("value")) for v in votes if v.get("value") is not None]
    unique = set(values)
    if agreement is None:
        if values:
            majority = str(output) if output is not None else values[0]
            agreement = sum(1 for v in values if v == majority) / len(values)
        else:
            agreement = 1.0
    if status is None:
        if len(unique) <= 1:
            status = "unanimous"
        elif agreement >= 0.67:
            status = "majority"
        else:
            status = "split"
    if needs_review is None:
        needs_review = status in DISPUTE_STATUSES or (
            status == "majority" and agreement < 1.0
        )
    return {
        "output": output,
        "status": status,
        "agreement": round(float(agreement), 4),
        "needs_review": bool(needs_review),
        "votes": votes,
    }
