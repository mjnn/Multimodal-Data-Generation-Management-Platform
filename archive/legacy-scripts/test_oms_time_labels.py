#!/usr/bin/env python3
"""Smoke tests for OMS L1.1 time label derivation."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "dataworks"))

from oms_time_labels import apply_l1_time_label_overrides, derive_l1_time_labels  # noqa: E402

# Local sample bag start_time_ns (2026-06-05 13:27:09 Asia/Shanghai)
SAMPLE_NS = 1780637229858114019


def test_derive_l1_time_labels_sample_bag() -> None:
    labels = derive_l1_time_labels(SAMPLE_NS, timezone="Asia/Shanghai")
    ts = labels["L1.1.timestamp"]
    assert ts["timestamp_ms"] == SAMPLE_NS // 1_000_000
    assert ts["timezone"] == "Asia/Shanghai"
    assert labels["L1.1.day_period"] == "afternoon"
    assert labels["L1.1.commute_flag"] == "non_commute"
    assert labels["L1.1.is_holiday"] == "false"


def test_apply_overrides_replaces_vl_hallucination() -> None:
    merged = apply_l1_time_label_overrides(
        {"L1.1.timestamp": {"timestamp_ms": 1672531200000, "timezone": "UTC"}},
        SAMPLE_NS,
        timezone="Asia/Shanghai",
    )
    assert merged["L1.1.timestamp"]["timestamp_ms"] == SAMPLE_NS // 1_000_000
    assert merged["L1.1.timestamp"]["timezone"] == "Asia/Shanghai"


if __name__ == "__main__":
    test_derive_l1_time_labels_sample_bag()
    test_apply_overrides_replaces_vl_hallucination()
    print("ok")
