# =============================================================================
# Job2_labeling — 主模型整 clip 打标（clip-omni v2）
#
# 输入：aligned/
# 输出：ai/labels_primary.json
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

from clip_labeling_common import write_labels_artifact


def write_primary_labels(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    labels_json: dict[str, Any],
    model_version: str | None = None,
) -> str:
    return write_labels_artifact(
        run_root,
        filename="labels_primary.json",
        clip_id=clip_id,
        run_id=run_id,
        labels_json=labels_json,
        model_version=model_version,
        label_role="primary",
    )


def main() -> None:
    print("job2_labeling: invoke Omni/VL on aligned timeline → write_primary_labels()")


if __name__ == "__main__":
    main()
