# =============================================================================
# Job3_labeling_by_other_model — 第二模型整 clip 打标（流程同 job2_labeling）
#
# 输入：aligned/
# 输出：ai/labels_secondary.json
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

from clip_labeling_common import write_labels_artifact


def write_secondary_labels(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    labels_json: dict[str, Any],
    model_version: str | None = None,
) -> str:
    return write_labels_artifact(
        run_root,
        filename="labels_secondary.json",
        clip_id=clip_id,
        run_id=run_id,
        labels_json=labels_json,
        model_version=model_version,
        label_role="secondary",
    )


def main() -> None:
    print(
        "job3_labeling_by_other_model: same flow as job2_labeling with secondary_model param"
    )


if __name__ == "__main__":
    main()
