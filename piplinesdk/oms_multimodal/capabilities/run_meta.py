from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_run_json(
    run_dir: Path | str,
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    bag_oss_key: str = "",
    stages_done: tuple[str, ...] | list[str] = (),
    model_backend: str = "mc",
    extra: dict[str, Any] | None = None,
) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    doc: dict[str, Any] = {
        "layout_version": "sdk_v1",
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": ds,
        "bag_oss_key": bag_oss_key,
        "sdk_files": {
            "labels": "labels.jsonl",
            "embeddings": "fusion_embeddings.jsonl",
            "videos": "clip_videos.jsonl",
        },
        "preview_manifest": "preview/manifest.json",
        "stages_done": list(stages_done),
        "model_backend": model_backend,
        "completed_at": _utc_now(),
    }
    if extra:
        doc.update(extra)
    path = run_dir / "run.json"
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
