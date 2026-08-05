"""Sample review candidates by target label value distribution (enum or string buckets)."""

from __future__ import annotations

import random
from typing import Any

from hmi.labels_util import get_clip_label_value


def _clip_label_str(review: dict[str, Any], label_id: str) -> str | None:
    val = get_clip_label_value(review.get("labels_json"), label_id)
    if val is None or val == "":
        return None
    return str(val)


def _match_string_bucket(value: str, bucket: dict[str, Any]) -> bool:
    match = str(bucket.get("match") or "exact").strip()
    if match == "exact":
        target = bucket.get("value")
        if target is None or str(target).strip() == "":
            return False
        return value == str(target)
    if match == "range":
        lo = str(bucket.get("min") or "")
        hi = str(bucket.get("max") or "")
        if lo and hi:
            return lo <= value <= hi
        if lo:
            return value >= lo
        if hi:
            return value <= hi
        return False
    return False


def _sample_from_pool(pool: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    if target <= 0 or not pool:
        return []
    if len(pool) <= target:
        return list(pool)
    return random.sample(pool, target)


def _normalize_enum_weights(weights: dict[str, Any]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, raw in weights.items():
        if raw is None or raw == "":
            continue
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            continue
        if pct > 0:
            out[str(key)] = pct
    return out


def _apply_enum_distribution(
    reviews: list[dict[str, Any]],
    label_id: str,
    weights: dict[str, Any],
    total: int,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for review in reviews:
        val = _clip_label_str(review, label_id)
        if val is None:
            continue
        groups.setdefault(val, []).append(review)

    if not groups:
        return []

    norm_weights = _normalize_enum_weights(weights if isinstance(weights, dict) else {})
    specified_keys = {k for k in norm_weights if k in groups}
    unspecified_keys = [k for k in groups if k not in specified_keys]
    specified_total_pct = sum(norm_weights[k] for k in specified_keys)

    targets: dict[str, int] = {}
    for key, pct in norm_weights.items():
        if key not in groups:
            continue
        targets[key] = max(0, round(total * pct / 100.0))

    remainder_pct = max(0.0, 100.0 - specified_total_pct)
    if unspecified_keys and remainder_pct > 0:
        per = remainder_pct / len(unspecified_keys)
        for key in unspecified_keys:
            add = max(0, round(total * per / 100.0))
            targets[key] = targets.get(key, 0) + add

    if not targets and unspecified_keys:
        per = 100.0 / len(unspecified_keys)
        for key in unspecified_keys:
            targets[key] = max(0, round(total * per / 100.0))

    selected: list[dict[str, Any]] = []
    used: set[tuple[str, str]] = set()
    for key, target in targets.items():
        for row in _sample_from_pool(groups.get(key, []), target):
            pair = (str(row["clip_id"]), str(row["run_id"]))
            if pair in used:
                continue
            used.add(pair)
            selected.append(row)

    if len(selected) < total:
        remaining = [
            r
            for r in reviews
            if (str(r["clip_id"]), str(r["run_id"])) not in used
            and _clip_label_str(r, label_id) is not None
        ]
        need = min(total - len(selected), len(remaining))
        if need > 0:
            selected.extend(random.sample(remaining, need))

    if len(selected) > total:
        selected = random.sample(selected, total)
    return selected


def _apply_string_distribution(
    reviews: list[dict[str, Any]],
    label_id: str,
    buckets: list[Any],
    total: int,
) -> list[dict[str, Any]]:
    if not isinstance(buckets, list) or not buckets:
        return []

    selected: list[dict[str, Any]] = []
    used: set[tuple[str, str]] = set()

    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        try:
            pct = float(bucket.get("weight"))
        except (TypeError, ValueError):
            continue
        if pct <= 0:
            continue
        target = max(0, round(total * pct / 100.0))
        pool: list[dict[str, Any]] = []
        for review in reviews:
            pair = (str(review["clip_id"]), str(review["run_id"]))
            if pair in used:
                continue
            val = _clip_label_str(review, label_id)
            if val is None:
                continue
            if _match_string_bucket(val, bucket):
                pool.append(review)
        for row in _sample_from_pool(pool, target):
            pair = (str(row["clip_id"]), str(row["run_id"]))
            if pair in used:
                continue
            used.add(pair)
            selected.append(row)

    if len(selected) > total:
        selected = random.sample(selected, total)
    return selected


def apply_label_distribution_sample(
    reviews: list[dict[str, Any]],
    filt: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Return sampled reviews when label_distribution is configured; else None."""
    dist = filt.get("label_distribution")
    if not isinstance(dist, dict):
        return None

    label_id = str(dist.get("label_id") or "").strip()
    if not label_id:
        return None

    sample_size = filt.get("sample_size")
    total = int(sample_size) if sample_size else len(reviews)
    if total <= 0:
        return []

    kind = str(dist.get("kind") or "enum").strip()
    if kind == "string":
        buckets = dist.get("buckets")
        if not isinstance(buckets, list) or not buckets:
            return None
        has_weight = any(
            isinstance(b, dict) and b.get("weight") not in (None, "")
            for b in buckets
        )
        if not has_weight:
            return None
        return _apply_string_distribution(reviews, label_id, buckets, total)

    weights = dist.get("weights")
    return _apply_enum_distribution(
        reviews,
        label_id,
        weights if isinstance(weights, dict) else {},
        total,
    )
