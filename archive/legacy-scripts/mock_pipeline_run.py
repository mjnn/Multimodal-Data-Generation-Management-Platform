"""Write local artifacts that mirror clip-omni v2 pipeline OSS layout."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_DATAWORKS = PROJECT_ROOT / "dataworks"
if str(_DATAWORKS) not in sys.path:
    sys.path.insert(0, str(_DATAWORKS))

from label_merge import merge_from_label_docs  # noqa: E402

PIPELINE_VERSION = "clip_omni_v2"
AGREEMENT_THRESHOLD = 0.7
PRIMARY_MODEL = "mock-qwen-vl-primary"
SECONDARY_MODEL = "mock-qwen-vl-secondary"
EMBED_MODEL = "mock-clip-embed-v1"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def labels_payload(day_period: str | None, is_holiday: bool | None) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if day_period is not None:
        values["L1.1.day_period"] = {"value": day_period}
    if is_holiday is not None:
        values["L1.1.is_holiday"] = {"value": is_holiday}
    return {"values": values}


def flat_map_to_labels_payload(flat: dict[str, Any]) -> dict[str, Any]:
    return {"values": {str(k): {"value": v} for k, v in flat.items()}}


def build_label_maps_from_spec(spec: MockRunSpec) -> tuple[dict[str, Any], dict[str, Any]]:
    if spec.primary_labels is not None:
        primary = dict(spec.primary_labels)
        secondary = dict(spec.secondary_labels if spec.secondary_labels is not None else spec.primary_labels)
        return primary, secondary
    primary: dict[str, Any] = {}
    secondary: dict[str, Any] = {}
    if spec.day_period is not None:
        primary["L1.1.day_period"] = spec.day_period
        secondary["L1.1.day_period"] = (
            spec.secondary_day_period if spec.secondary_day_period is not None else spec.day_period
        )
    if spec.is_holiday is not None:
        primary["L1.1.is_holiday"] = spec.is_holiday
        secondary["L1.1.is_holiday"] = (
            spec.secondary_is_holiday if spec.secondary_is_holiday is not None else spec.is_holiday
        )
    return primary, secondary


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


@dataclass(frozen=True)
class MockRunSpec:
    clip_id: str
    run_id: str
    dir_name: str
    start_time_ns: int
    end_time_ns: int
    duration_sec: float
    anchor_ns: int
    day_period: str | None
    is_holiday: bool | None
    secondary_day_period: str | None = None
    secondary_is_holiday: bool | None = None
    primary_labels: dict[str, Any] | None = None
    secondary_labels: dict[str, Any] | None = None
    agreement_threshold: float = AGREEMENT_THRESHOLD
    vector: list[float] | None = None
    labeled: bool = True


def write_parsed_artifacts(
    run_root: Path,
    spec: MockRunSpec,
    *,
    image_paths: list[str] | None = None,
) -> dict[str, str]:
    parsed = run_root / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)

    manifest = {
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "bag_stem": spec.dir_name,
        "start_time_ns": spec.start_time_ns,
        "end_time_ns": spec.end_time_ns,
        "duration_sec": spec.duration_sec,
        "modalities": ["camera", "audio", "event"],
        "cameras": ["camera0", "camera1", "camera2", "camera3"],
        "parsed_at": _utc_now(),
    }
    _write_json(parsed / "manifest.json", manifest)

    event_line = {
        "timestamp_ns": spec.anchor_ns,
        "topic": "/vehicle/event",
        "event_id": f"evt_{spec.dir_name}",
        "payload": {"demo": True},
    }
    (parsed / "events.jsonl").write_text(
        json.dumps(event_line, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    mc_payload = {
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "ds": "20260721",
        "parse_result": {
            "frames": [
                {
                    "camera": f"camera{i}",
                    "frame_idx": 0,
                    "timestamp_ns": spec.anchor_ns + i * 50_000_000,
                    "image_path": (image_paths or [f"parsed/output/images/camera{i}/000000.jpg"])[
                        min(i, len(image_paths or []) - 1)
                    ]
                    if image_paths
                    else f"parsed/output/images/camera{i}/000000.jpg",
                }
                for i in range(4)
            ],
            "audio_chunks": [
                {
                    "chunk_idx": 0,
                    "timestamp_ns": spec.start_time_ns,
                    "duration_sec": spec.duration_sec,
                }
            ],
        },
    }
    _write_json(parsed / "job1_mc_payload.json", mc_payload)

    return {
        "manifest": str(parsed / "manifest.json"),
        "events": str(parsed / "events.jsonl"),
        "mc_payload": str(parsed / "job1_mc_payload.json"),
    }


def write_aligned_artifacts(run_root: Path, spec: MockRunSpec) -> dict[str, str]:
    aligned = run_root / "aligned"
    aligned.mkdir(parents=True, exist_ok=True)

    timeline = {
        "pipeline_version": PIPELINE_VERSION,
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "start_time_ns": spec.start_time_ns,
        "end_time_ns": spec.end_time_ns,
        "duration_sec": spec.duration_sec,
        "modalities": ["camera", "audio", "event"],
    }
    _write_json(aligned / "timeline.json", timeline)

    sync_lines = [
        {
            "anchor_timestamp_ns": spec.anchor_ns,
            "object_type": "event",
            "object_id": f"evt_{spec.dir_name}",
        },
        {
            "anchor_timestamp_ns": spec.anchor_ns,
            "object_type": "frame",
            "object_id": "camera0:0",
        },
    ]
    (aligned / "sync_manifest.jsonl").write_text(
        "\n".join(json.dumps(x, ensure_ascii=False) for x in sync_lines) + "\n",
        encoding="utf-8",
    )

    return {
        "timeline": str(aligned / "timeline.json"),
        "sync_manifest": str(aligned / "sync_manifest.jsonl"),
    }


def write_ai_artifacts(
    run_root: Path,
    spec: MockRunSpec,
    *,
    threshold: float | None = None,
) -> dict[str, Any] | None:
    if not spec.labeled:
        return None
    primary_map, secondary_map = build_label_maps_from_spec(spec)
    if not primary_map:
        return None

    ai_dir = run_root / "ai"
    ai_dir.mkdir(parents=True, exist_ok=True)

    merge_threshold = threshold if threshold is not None else spec.agreement_threshold

    primary_labels = flat_map_to_labels_payload(primary_map)
    secondary_labels = flat_map_to_labels_payload(secondary_map)

    primary_doc = {
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "label_source": "ai",
        "label_role": "primary",
        "model_version": PRIMARY_MODEL,
        "labels_json": primary_labels,
        "created_at": _utc_now(),
    }
    secondary_doc = {
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "label_source": "ai",
        "label_role": "secondary",
        "model_version": SECONDARY_MODEL,
        "labels_json": secondary_labels,
        "created_at": _utc_now(),
    }

    _write_json(ai_dir / "labels_primary.json", primary_doc)
    _write_json(ai_dir / "labels_secondary.json", secondary_doc)

    merged_flat, multi_ai_meta = merge_from_label_docs(
        primary_doc,
        secondary_doc,
        threshold=merge_threshold,
        primary_model=PRIMARY_MODEL,
        secondary_model=SECONDARY_MODEL,
    )
    gate = multi_ai_meta.get("gate") or {}

    merged_doc = {
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "label_source": "ai_merged",
        "labels_json": merged_flat,
        "multi_ai_meta": multi_ai_meta,
        "gate_passed": bool(gate.get("passed")),
        "clip_agreement": gate.get("clip_score"),
        "agreement_threshold": merge_threshold,
        "created_at": _utc_now(),
    }
    consensus_doc = {
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "multi_ai_meta": multi_ai_meta,
        "disputed_label_ids": multi_ai_meta.get("disputed_label_ids") or [],
        "gate_passed": bool(gate.get("passed")),
        "created_at": _utc_now(),
    }

    _write_json(ai_dir / "labels_merged.json", merged_doc)
    _write_json(ai_dir / "labels.json", merged_doc)
    _write_json(ai_dir / "consensus_meta.json", consensus_doc)

    vector = spec.vector or [0.25, 0.25, 0.25, 0.25]
    embed_doc = {
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "dim": len(vector),
        "model_version": EMBED_MODEL,
        "aggregation_method": "clip_omni",
        "vector": vector,
        "created_at": _utc_now(),
    }
    _write_json(ai_dir / "embedding.json", embed_doc)

    infer_meta = {
        "pipeline_version": PIPELINE_VERSION,
        "clip_id": spec.clip_id,
        "run_id": spec.run_id,
        "primary_model": PRIMARY_MODEL,
        "secondary_model": SECONDARY_MODEL,
        "embed_model": EMBED_MODEL,
        "gate_passed": bool(gate.get("passed")),
        "clip_agreement": gate.get("clip_score"),
        "finished_at": _utc_now(),
    }
    _write_json(ai_dir / "infer_meta.json", infer_meta)

    return {
        "merged_doc": merged_doc,
        "consensus_doc": consensus_doc,
        "embed_doc": embed_doc,
        "primary_doc": primary_doc,
        "secondary_doc": secondary_doc,
    }


def write_full_mock_run(
    run_root: Path,
    spec: MockRunSpec,
    *,
    image_paths: list[str] | None = None,
) -> dict[str, Any]:
    """Write parsed + aligned + optional ai artifacts under run_root."""
    out: dict[str, Any] = {"run_root": str(run_root), "clip_id": spec.clip_id, "run_id": spec.run_id}
    out["parsed"] = write_parsed_artifacts(run_root, spec, image_paths=image_paths)
    out["aligned"] = write_aligned_artifacts(run_root, spec)
    ai_result = write_ai_artifacts(run_root, spec)
    out["ai"] = ai_result
    if ai_result:
        gate = (ai_result["merged_doc"].get("multi_ai_meta") or {}).get("gate") or {}
        out["gate_passed"] = bool(gate.get("passed"))
        out["clip_agreement"] = gate.get("clip_score")
        out["disputed_label_ids"] = ai_result["consensus_doc"].get("disputed_label_ids") or []
        out["merged_labels"] = ai_result["merged_doc"].get("labels_json") or {}
    return out


def artifact_checklist(run_root: Path, *, labeled: bool = True) -> list[tuple[str, bool]]:
    rels = [
        "parsed/manifest.json",
        "parsed/events.jsonl",
        "parsed/job1_mc_payload.json",
        "aligned/timeline.json",
        "aligned/sync_manifest.jsonl",
    ]
    if labeled:
        rels.extend(
            [
                "ai/labels_primary.json",
                "ai/labels_secondary.json",
                "ai/labels_merged.json",
                "ai/consensus_meta.json",
                "ai/embedding.json",
                "ai/infer_meta.json",
                "ai/labels.json",
            ]
        )
    return [(rel, (run_root / rel).is_file()) for rel in rels]
