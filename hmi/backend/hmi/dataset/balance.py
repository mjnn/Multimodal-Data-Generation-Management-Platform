"""Balance sampling and oversample virtual rows for dataset manifests."""

from __future__ import annotations

import random
from typing import Any

DEFAULT_VARIANT_ID = "base"


def _source_row_key(clip_id: str, run_id: str, variant_id: str = DEFAULT_VARIANT_ID) -> str:
    return f"{clip_id}|{run_id}|{variant_id}"


def _clone_row(
    source: dict[str, Any],
    *,
    variant_id: str,
    duplicate_index: int,
    balance_by_label: str,
) -> dict[str, Any]:
    clip_id = str(source["clip_id"])
    run_id = str(source["run_id"])
    row = dict(source)
    row["variant_id"] = variant_id
    row["source_row_key"] = _source_row_key(clip_id, run_id, variant_id)
    row["aug_hint"] = {
        "type": "platform_oversample",
        "balance_by_label": balance_by_label,
        "duplicate_index": duplicate_index,
    }
    return row


def _ensure_base_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    clip_id = str(out["clip_id"])
    run_id = str(out["run_id"])
    out.setdefault("variant_id", DEFAULT_VARIANT_ID)
    out.setdefault("source_row_key", _source_row_key(clip_id, run_id, str(out["variant_id"])))
    return out


def _group_by_label(
    rows: list[dict[str, Any]],
    balance_by_label: str,
) -> dict[str, list[dict[str, Any]]]:
    from hmi.dataset.distribution import label_value

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        val = label_value(row, balance_by_label)
        key = val if val is not None else "__missing__"
        groups.setdefault(key, []).append(row)
    return groups


def apply_balance(
    rows: list[dict[str, Any]],
    filt: dict[str, Any],
) -> list[dict[str, Any]]:
    """Apply max_per_class cap and duplicate_to_min oversampling."""
    balance_by_label = filt.get("balance_by_label")
    if not balance_by_label:
        return [_ensure_base_row(r) for r in rows]

    min_per_class = filt.get("min_per_class")
    max_per_class = filt.get("max_per_class")
    policy = str(filt.get("oversample_policy") or "none").strip()
    max_multiplier = int(filt.get("oversample_max_multiplier") or 10)

    base_rows = [_ensure_base_row(r) for r in rows]
    groups = _group_by_label(base_rows, str(balance_by_label))

    capped: list[dict[str, Any]] = []
    for _label, group in groups.items():
        if max_per_class is not None and len(group) > int(max_per_class):
            capped.extend(random.sample(group, int(max_per_class)))
        else:
            capped.extend(group)

    if policy != "duplicate_to_min" or min_per_class is None:
        return capped

    target_min = int(min_per_class)
    out: list[dict[str, Any]] = []
    for _label, group in _group_by_label(capped, str(balance_by_label)).items():
        if not group:
            continue
        out.extend(group)
        need = target_min - len(group)
        if need <= 0:
            continue
        max_dup = max(1, len(group) * max_multiplier - len(group))
        dup_count = min(need, max_dup)
        for i in range(dup_count):
            source = group[i % len(group)]
            variant_id = f"dup_{i + 1}"
            out.append(
                _clone_row(
                    source,
                    variant_id=variant_id,
                    duplicate_index=i + 1,
                    balance_by_label=str(balance_by_label),
                )
            )
    return out


def unique_clip_count(rows: list[dict[str, Any]]) -> int:
    seen: set[tuple[str, str]] = set()
    for row in rows:
        seen.add((str(row["clip_id"]), str(row["run_id"])))
    return len(seen)
