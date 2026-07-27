# =============================================================================
# Job2_embedding — clip 向量化（与打标解耦）
#
# 输入：aligned/（+ 可选 parsed/ 多模态）
# 输出：ai/embedding.json
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_embedding_artifact(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    vector: list[float],
    model_version: str | None = None,
    aggregation_method: str = "clip_omni",
) -> str:
    ai_dir = run_root / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)
    path = ai_dir / "embedding.json"
    doc = {
        "clip_id": clip_id,
        "run_id": run_id,
        "dim": len(vector),
        "model_version": model_version,
        "aggregation_method": aggregation_method,
        "vector": vector,
        "created_at": utc_now(),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def main() -> None:
    print("job2_embedding: invoke embed model on clip → write_embedding_artifact()")


if __name__ == "__main__":
    main()
