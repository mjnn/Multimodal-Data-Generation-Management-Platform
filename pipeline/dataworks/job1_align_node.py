# =============================================================================
# DataWorks PyODPS 3：Job1_align — 多模态时间轴对齐（clip-omni v2）
#
# 输入：clips/{clip_id}/runs/{run_id}/parsed/
# 输出：aligned/timeline.json · aligned/sync_manifest.jsonl
# 下游：job2_clip_omni
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def build_timeline(parsed_manifest: dict[str, Any], *, clip_id: str, run_id: str) -> dict[str, Any]:
    start = int(parsed_manifest.get("start_time_ns") or 0)
    end = int(parsed_manifest.get("end_time_ns") or start)
    duration = float(parsed_manifest.get("duration_sec") or max(0.0, (end - start) / 1e9))
    return {
        "pipeline_version": "clip_omni_v1",
        "clip_id": clip_id,
        "run_id": run_id,
        "start_time_ns": start,
        "end_time_ns": end,
        "duration_sec": duration,
        "modalities": parsed_manifest.get("modalities") or ["camera", "audio", "event"],
    }


def build_sync_manifest_lines(parsed_root: Path) -> list[dict[str, Any]]:
    """Build anchor lines from parsed frames/events (stub — extend in DPE)."""
    lines: list[dict[str, Any]] = []
    events = parsed_root / "events.jsonl"
    if events.is_file():
        for raw in events.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if row.get("timestamp_ns") is not None:
                lines.append(
                    {
                        "anchor_timestamp_ns": int(row["timestamp_ns"]),
                        "object_type": "event",
                        "object_id": str(row.get("topic") or row.get("event_id") or "event"),
                    }
                )
    return lines


def write_aligned_artifacts(
    run_root: Path,
    *,
    clip_id: str,
    run_id: str,
    parsed_manifest: dict[str, Any],
) -> dict[str, str]:
    aligned = run_root / "aligned"
    aligned.mkdir(parents=True, exist_ok=True)
    timeline_path = aligned / "timeline.json"
    sync_path = aligned / "sync_manifest.jsonl"
    timeline = build_timeline(parsed_manifest, clip_id=clip_id, run_id=run_id)
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = build_sync_manifest_lines(run_root / "parsed")
    sync_path.write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )
    return {"timeline": str(timeline_path), "sync_manifest": str(sync_path)}


def main() -> None:
    print("job1_align: use write_aligned_artifacts() from bundled node or local tests")


if __name__ == "__main__":
    main()
