"""Tests for label value distribution sampling."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from hmi.dataset.label_distribution import apply_label_distribution_sample


def _review(clip_id: str, label_id: str, value: str) -> dict:
    return {
        "clip_id": clip_id,
        "run_id": "run1",
        "labels_json": {"values": {label_id: {"value": value}}},
    }


def test_enum_distribution_with_weights() -> None:
    reviews = [
        _review("c1", "L1.1.day_period", "morning"),
        _review("c2", "L1.1.day_period", "morning"),
        _review("c3", "L1.1.day_period", "night"),
        _review("c4", "L1.1.day_period", "night"),
    ]
    filt = {
        "sample_size": 2,
        "label_distribution": {
            "label_id": "L1.1.day_period",
            "kind": "enum",
            "weights": {"morning": 50, "night": 50},
        },
    }
    out = apply_label_distribution_sample(reviews, filt)
    assert out is not None
    assert len(out) == 2
    print("OK enum distribution weighted sample")


def test_string_distribution_exact() -> None:
    reviews = [
        _review("c1", "L1.2.scene", "highway"),
        _review("c2", "L1.2.scene", "urban"),
        _review("c3", "L1.2.scene", "highway"),
    ]
    filt = {
        "sample_size": 2,
        "label_distribution": {
            "label_id": "L1.2.scene",
            "kind": "string",
            "buckets": [{"match": "exact", "value": "highway", "weight": 100}],
        },
    }
    out = apply_label_distribution_sample(reviews, filt)
    assert out is not None
    assert len(out) == 2
    assert all(
        str(r["labels_json"]["values"]["L1.2.scene"]["value"]) == "highway" for r in out
    )
    print("OK string distribution exact match")


def main() -> None:
    test_enum_distribution_with_weights()
    test_string_distribution_exact()
    print("ALL label_distribution TESTS PASSED")


if __name__ == "__main__":
    main()
