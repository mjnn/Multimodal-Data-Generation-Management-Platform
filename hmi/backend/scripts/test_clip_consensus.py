"""Multi-AI consensus metadata helpers."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from hmi.clip_consensus import (
    build_label_consensus_entry,
    build_multi_ai_meta,
    disputed_label_ids,
    parse_multi_ai_meta,
)


def test_disputed_labels() -> None:
    meta = build_multi_ai_meta(
        gate_passed=True,
        clip_score=0.82,
        threshold=0.7,
        model_count=3,
        labels={
            "L1.1.day_period": build_label_consensus_entry(
                output="morning",
                votes=[
                    {"model": "a", "value": "morning", "confidence": 0.9},
                    {"model": "b", "value": "afternoon", "confidence": 0.8},
                    {"model": "c", "value": "morning", "confidence": 0.88},
                ],
                status="split",
                needs_review=True,
            ),
            "L1.1.is_holiday": build_label_consensus_entry(
                output=False,
                votes=[
                    {"model": "a", "value": False, "confidence": 0.9},
                    {"model": "b", "value": False, "confidence": 0.9},
                ],
            ),
        },
    )
    parsed = parse_multi_ai_meta(meta)
    assert parsed is not None
    disputed = disputed_label_ids(parsed)
    assert disputed == ["L1.1.day_period"]
    print("OK clip_consensus disputed_label_ids")


if __name__ == "__main__":
    test_disputed_labels()
