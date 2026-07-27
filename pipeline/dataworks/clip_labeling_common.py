# =============================================================================
# Shared helpers for clip-level labeling nodes (job2_labeling / job3 secondary)
# =============================================================================

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_labels_artifact(
    run_root: Path,
    *,
    filename: str,
    clip_id: str,
    run_id: str,
    labels_json: dict[str, Any],
    model_version: str | None = None,
    label_role: str = "primary",
) -> str:
    ai_dir = run_root / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)
    path = ai_dir / filename
    doc = {
        "clip_id": clip_id,
        "run_id": run_id,
        "label_source": "ai",
        "label_role": label_role,
        "model_version": model_version,
        "labels_json": labels_json,
        "created_at": utc_now(),
    }
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)
