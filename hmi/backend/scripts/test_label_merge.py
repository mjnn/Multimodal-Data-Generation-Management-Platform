"""Dual-model label merge unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "pipeline" / "dataworks"))

from label_merge import merge_dual_model_labels  # noqa: E402


def test_gate_pass_primary_wins() -> None:
    primary = {"L1.1.day_period": "morning", "L1.1.is_holiday": False}
    secondary = {"L1.1.day_period": "afternoon", "L1.1.is_holiday": False}
    merged, meta = merge_dual_model_labels(
        primary, secondary, threshold=0.5, primary_model="m1", secondary_model="m2"
    )
    assert merged["L1.1.day_period"] == "morning"
    assert merged["L1.1.is_holiday"] is False
    assert meta["gate"]["passed"] is True
    assert meta["labels"]["L1.1.day_period"]["needs_review"] is False


def test_gate_fail_dispute_empty() -> None:
    primary = {"L1.1.day_period": "morning", "L1.1.is_holiday": False}
    secondary = {"L1.1.day_period": "night", "L1.1.is_holiday": True}
    merged, meta = merge_dual_model_labels(
        primary, secondary, threshold=0.9, primary_model="m1", secondary_model="m2"
    )
    assert "L1.1.day_period" not in merged
    assert "L1.1.is_holiday" not in merged
    assert meta["gate"]["passed"] is False
    assert "L1.1.day_period" in meta["disputed_label_ids"]
    assert meta["labels"]["L1.1.day_period"]["needs_review"] is True


def main() -> None:
    test_gate_pass_primary_wins()
    print("OK gate pass → primary wins on conflict")
    test_gate_fail_dispute_empty()
    print("OK gate fail → disputed fields empty")
    print("All label merge tests passed.")


if __name__ == "__main__":
    main()
