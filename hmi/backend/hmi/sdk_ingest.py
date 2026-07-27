"""Ingest SDK v1 bundle (jsonl + preview/) into local SQLite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.clip_facts import upsert_clip_embedding, upsert_clip_label
from hmi.config import SDK_PIPELINE_STEP_ORDER
from hmi.data_source import artifact_path
from hmi.labels_util import labels_to_clip_dict
from hmi.local import store
from hmi.media.preview_manifest import load_preview_manifest
from hmi.oss_layout import (
    SDK_EMBEDDINGS_JSONL,
    SDK_LABELS_JSONL,
    CLIP_PREVIEW_AUDIO_KEY,
    SDK_RUN_JSON_KEY,
    SDK_VIDEOS_JSONL,
)


def read_jsonl_first(path: Path) -> dict[str, Any]:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            row = json.loads(line)
            if isinstance(row, dict):
                return row
    raise ValueError(f"empty jsonl: {path}")


def content_hash_from_clip_id(clip_id: str) -> str:
    return clip_id.split(":", 1)[-1][:64]


def sdk_bundle_present(clip_id: str, run_id: str) -> bool:
    root = artifact_path(clip_id, run_id, "")
    return (root / SDK_LABELS_JSONL).is_file() and (root / SDK_EMBEDDINGS_JSONL).is_file()


def load_sdk_run_json(clip_id: str, run_id: str) -> dict[str, Any] | None:
    path = artifact_path(clip_id, run_id, SDK_RUN_JSON_KEY)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


def _asr_text_from_label_row(label_row: dict[str, Any]) -> str:
    direct = str(label_row.get("asr_text") or "").strip()
    if direct:
        return direct
    asr = label_row.get("asr")
    if isinstance(asr, dict):
        return str(asr.get("text") or "").strip()
    return ""


def _frame_rows_from_manifest(clip_id: str, run_id: str, start_ns: int) -> list[dict[str, Any]]:
    doc = load_preview_manifest(clip_id, run_id)
    if not doc:
        return []
    cams = doc.get("cameras")
    rows: list[dict[str, Any]] = []
    if isinstance(cams, dict):
        for cam in sorted(cams.keys()):
            info = cams[cam]
            if not isinstance(info, dict):
                continue
            rel = str(info.get("relpath") or "")
            if not rel:
                continue
            rows.append(
                {
                    "camera": cam,
                    "frame_idx": 0,
                    "timestamp_ns": start_ns,
                    "image_path": rel,
                }
            )
    return rows


def seed_sqlite_from_sdk_parsed(
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    clip_dir_name: str,
    bag_oss_key: str,
    label_row: dict[str, Any],
    embed_row: dict[str, Any],
    flat_labels: dict[str, Any] | None = None,
    frame_rows: list[dict[str, Any]] | None = None,
    audio_relpath: str | None = None,
) -> None:
    start_ns = int(label_row.get("start_timestamp_ns") or 0)
    end_ns = int(label_row.get("end_timestamp_ns") or start_ns)
    duration = float(label_row.get("duration_sec") or max(0.0, (end_ns - start_ns) / 1e9))
    labels = flat_labels if flat_labels is not None else labels_to_clip_dict(label_row.get("labels") or {})

    if frame_rows is None:
        frame_rows = _frame_rows_from_manifest(clip_id, run_id, start_ns)

    if audio_relpath is None:
        audio_path = artifact_path(clip_id, run_id, CLIP_PREVIEW_AUDIO_KEY)
        audio_relpath = CLIP_PREVIEW_AUDIO_KEY if audio_path.is_file() else ""

    store.execute(
        """
        INSERT OR REPLACE INTO dim_clip (
          clip_id, clip_dir_name, content_hash, bag_oss_key, active_run_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (
            clip_id,
            clip_dir_name,
            content_hash_from_clip_id(clip_id),
            bag_oss_key,
            run_id,
        ),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO pipeline_run (
          run_id, clip_id, ds, status, label_granularity, started_at, updated_at, completed_at
        ) VALUES (?, ?, ?, 'completed', 'clip', datetime('now'), datetime('now'), datetime('now'))
        """,
        (run_id, clip_id, ds),
    )
    store.execute("DELETE FROM pipeline_step WHERE run_id=? AND ds=?", (run_id, ds))
    for step_id in SDK_PIPELINE_STEP_ORDER:
        store.execute(
            """
            INSERT OR REPLACE INTO pipeline_step (run_id, ds, step_id, status, started_at, finished_at)
            VALUES (?, ?, ?, 'success', datetime('now'), datetime('now'))
            """,
            (run_id, ds, step_id),
        )

    store.execute(
        """
        INSERT OR REPLACE INTO clip_parse_summary (
          clip_id, run_id, ds, start_time_ns, end_time_ns, duration_sec
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (clip_id, run_id, ds, start_ns, end_ns, duration),
    )

    store.execute(
        "DELETE FROM fact_frame WHERE clip_id=? AND run_id=? AND ds=?",
        (clip_id, run_id, ds),
    )
    for row in frame_rows:
        store.execute(
            """
            INSERT OR REPLACE INTO fact_frame (
              clip_id, run_id, ds, camera, frame_idx, timestamp_ns, image_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                run_id,
                ds,
                row["camera"],
                row["frame_idx"],
                row["timestamp_ns"],
                row["image_path"],
            ),
        )

    store.execute(
        "DELETE FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=?",
        (clip_id, run_id, ds),
    )
    asr_text = _asr_text_from_label_row(label_row)
    if asr_text:
        store.execute(
            """
            INSERT OR REPLACE INTO fact_audio_segment (
              clip_id, run_id, ds, segment_id, start_ns, end_ns, asr_text, confidence, audio_relpath
            ) VALUES (?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (clip_id, run_id, ds, start_ns, end_ns, asr_text, 1.0, audio_relpath or ""),
        )

    upsert_clip_label(
        clip_id,
        run_id,
        ds=ds,
        labels_json=labels,
        model_version=str(label_row.get("model") or "qwen3.5-omni-plus"),
        label_source="ai",
        anchor_timestamp_ns=start_ns,
        multi_ai_meta_json={
            "layout_version": "sdk_v1",
            "gate": {"passed": True, "clip_score": 1.0},
            "disputed_label_ids": [],
        },
    )
    vector = embed_row.get("embedding") or embed_row.get("vector") or []
    upsert_clip_embedding(
        clip_id,
        run_id,
        ds=ds,
        vector=list(vector),
        model_version=str(embed_row.get("model") or "qwen3-vl-embedding"),
        aggregation_method="clip_native",
    )


def ingest_sdk_run_local(clip_id: str, run_id: str, ds: str) -> dict[str, bool]:
    """Load SDK jsonl from artifact dir and refresh SQLite facts."""
    root = artifact_path(clip_id, run_id, "")
    labels_path = root / SDK_LABELS_JSONL
    embed_path = root / SDK_EMBEDDINGS_JSONL
    if not labels_path.is_file() or not embed_path.is_file():
        return {"labels": False, "embedding": False}

    label_row = read_jsonl_first(labels_path)
    embed_row = read_jsonl_first(embed_path)
    run_doc = load_sdk_run_json(clip_id, run_id) or {}

    clip_dir_name = str(run_doc.get("source_run_dir") or clip_id)
    bag_oss_key = str(run_doc.get("bag_oss_key") or "")
    if not bag_oss_key:
        bag_name = str(label_row.get("bag_name") or "output.bag")
        bag_oss_key = f"rosbags/{bag_name}"

    seed_sqlite_from_sdk_parsed(
        clip_id=clip_id,
        run_id=run_id,
        ds=str(run_doc.get("ds") or ds),
        clip_dir_name=clip_dir_name,
        bag_oss_key=bag_oss_key,
        label_row=label_row,
        embed_row=embed_row,
    )
    return {"labels": True, "embedding": True}
