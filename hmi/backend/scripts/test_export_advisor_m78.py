"""M7.8 export advisor smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from hmi.dataset.assemble import MAX_CLIP_COUNT
from hmi.dataset.export_advisor import build_export_recommendation


def main() -> None:
    small = build_export_recommendation(
        filter_json={"export_preset": "minimal"},
        estimated_clip_count=100,
        estimated_line_count=100,
        label_column_count=5,
        embedding_summary={"schemas": ["clip_embedding_v1"], "model_versions": ["v1"]},
    )
    assert small["suggested_export_preset"] == "minimal"
    assert small["suggested_include_parquet"] is False
    assert small["confidence"] == "high"
    print("OK small dataset recommendation")

    large = build_export_recommendation(
        filter_json={"export_preset": "minimal", "balance_by_label": "L1.1.day_period"},
        estimated_clip_count=3000,
        estimated_line_count=3500,
        label_column_count=22,
        embedding_summary={"schemas": ["clip_embedding_v1"], "model_versions": []},
        distribution_after={"day": 100, "night": 3000},
    )
    assert large["suggested_include_parquet"] is True
    assert any("Parquet" in r for r in large["reasons"])
    print("OK large dataset recommends parquet")

    over = build_export_recommendation(
        filter_json={},
        estimated_clip_count=MAX_CLIP_COUNT + 1,
        estimated_line_count=MAX_CLIP_COUNT + 1,
        label_column_count=10,
        exceeds_clip_limit=True,
    )
    assert over["suggested_batch"] is True
    assert over["suggested_sample_size"] == MAX_CLIP_COUNT
    print("OK exceeds limit suggests sample")

    print("\nM7.8 export advisor tests passed.")


if __name__ == "__main__":
    main()
