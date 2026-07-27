"""Dual-model clip label merge & compare (job4_label_merge_and_compare).

Used by DataWorks job4 node and HMI ingest (via backend/hmi/label_merge.py).
"""

from __future__ import annotations

from typing import Any


def flat_label_map(doc: dict[str, Any] | None) -> dict[str, Any]:
    """Extract {label_id: value} from an ai/* labels artifact doc."""
    if not doc:
        return {}
    raw = doc.get("labels_json")
    if raw is None:
        raw = doc.get("labels")
    if not isinstance(raw, dict):
        return {}
    if isinstance(raw.get("values"), dict):
        raw = raw["values"]
    out: dict[str, Any] = {}
    for key, entry in raw.items():
        if isinstance(entry, dict) and "value" in entry:
            out[str(key)] = entry["value"]
        else:
            out[str(key)] = entry
    return out


def _values_equal(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return str(a).strip().lower() == str(b).strip().lower()


def build_label_vote_entry(
    *,
    output: Any,
    votes: list[dict[str, Any]],
    status: str,
    agreement: float,
    needs_review: bool,
) -> dict[str, Any]:
    return {
        "output": output,
        "status": status,
        "agreement": round(float(agreement), 4),
        "needs_review": bool(needs_review),
        "votes": votes,
    }


def merge_dual_model_labels(
    primary_map: dict[str, Any],
    secondary_map: dict[str, Any],
    *,
    threshold: float = 0.7,
    primary_model: str = "job2_labeling",
    secondary_model: str = "job3_labeling_by_other_model",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge two flat label maps into review-ready labels + multi_ai_meta.

    Rules:
    - clip_agreement = matching labels / comparable labels
    - gate_passed when clip_agreement >= threshold
    - unanimous label: use shared value
    - disagree + gate_passed: use primary (job2) value
    - disagree + gate_failed: omit from merged (empty for human); mark needs_review
    """
    all_keys = sorted(set(primary_map) | set(secondary_map))
    consensus: dict[str, dict[str, Any]] = {}
    merged: dict[str, Any] = {}

    comparable = 0
    agree_count = 0

    for label_id in all_keys:
        primary_val = primary_map.get(label_id)
        secondary_val = secondary_map.get(label_id)
        if primary_val is None and secondary_val is None:
            continue

        comparable += 1
        match = _values_equal(primary_val, secondary_val)
        if match:
            agree_count += 1

        votes = [
            {"model": primary_model, "value": primary_val},
            {"model": secondary_model, "value": secondary_val},
        ]
        label_agreement = 1.0 if match else 0.0
        status = "unanimous" if match else "split"
        consensus[label_id] = build_label_vote_entry(
            output=primary_val if not match else primary_val,
            votes=votes,
            status=status,
            agreement=label_agreement,
            needs_review=not match,
        )

    clip_score = (agree_count / comparable) if comparable else 1.0
    gate_passed = clip_score >= threshold

    disputed: list[str] = []
    for label_id in all_keys:
        primary_val = primary_map.get(label_id)
        secondary_val = secondary_map.get(label_id)
        if primary_val is None and secondary_val is None:
            continue

        match = _values_equal(primary_val, secondary_val)
        entry = consensus[label_id]

        if match:
            merged[label_id] = primary_val
            entry["output"] = primary_val
            entry["status"] = "unanimous"
            entry["needs_review"] = False
            continue

        if gate_passed:
            merged[label_id] = primary_val
            entry["output"] = primary_val
            entry["status"] = "majority"
            entry["agreement"] = 0.5
            entry["needs_review"] = False
        else:
            entry["output"] = None
            entry["status"] = "split"
            entry["needs_review"] = True
            disputed.append(label_id)

    multi_ai_meta = {
        "gate": {
            "passed": gate_passed,
            "clip_score": round(clip_score, 4),
            "threshold": threshold,
            "model_count": 2,
            "comparable_labels": comparable,
            "agree_count": agree_count,
        },
        "labels": consensus,
        "disputed_label_ids": disputed,
        "primary_model": primary_model,
        "secondary_model": secondary_model,
    }
    return merged, multi_ai_meta


def merge_from_label_docs(
    primary_doc: dict[str, Any],
    secondary_doc: dict[str, Any],
    *,
    threshold: float = 0.7,
    primary_model: str | None = None,
    secondary_model: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    primary_model = primary_model or str(primary_doc.get("model_version") or "job2_labeling")
    secondary_model = secondary_model or str(
        secondary_doc.get("model_version") or "job3_labeling_by_other_model"
    )
    return merge_dual_model_labels(
        flat_label_map(primary_doc),
        flat_label_map(secondary_doc),
        threshold=threshold,
        primary_model=primary_model,
        secondary_model=secondary_model,
    )
