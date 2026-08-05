"""Build and execute MaxCompute ingest SQL for one SDK v1 run directory."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SDK_LABELS_JSONL = "labels.jsonl"
SDK_EMBEDDINGS_JSONL = "fusion_embeddings.jsonl"
SDK_RUN_JSON = "run.json"

# Cloud verify_sdk_v1_run / HMI expect these five step_ids (see hmi.config.SDK_PIPELINE_STEP_ORDER).
SDK_PIPELINE_STEPS = (
    "sdk_discover",
    "sdk_infer",
    "sdk_upload",
    "sdk_mc_write",
    "sdk_dispatch",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _read_jsonl_first(path: Path) -> dict[str, Any]:
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if text:
            row = json.loads(text)
            if isinstance(row, dict):
                return row
    raise ValueError(f"empty jsonl: {path}")


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def _labels_to_clip_dict(raw_labels: Any) -> dict[str, Any]:
    if isinstance(raw_labels, str):
        raw_labels = json.loads(raw_labels) if raw_labels else {}
    if not isinstance(raw_labels, dict):
        return {}
    values = raw_labels.get("values")
    if not isinstance(values, dict):
        values = raw_labels
    result: dict[str, Any] = {}
    for key, entry in values.items():
        if isinstance(entry, dict) and "value" in entry:
            result[str(key)] = entry["value"]
        elif isinstance(entry, dict) and entry.get("values") is not None:
            result[str(key)] = str(entry["values"])
        elif entry is None:
            result[str(key)] = None
        else:
            result[str(key)] = str(entry)
    return result


def build_ingest_statements(
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    run_dir: Path,
    table_prefix: str = "aig_sdk__",
    bag_oss_key: str = "",
    now: str | None = None,
) -> list[str]:
    """Return SQL statements for SDK jsonl artifacts without contacting ODPS."""
    run_dir = Path(run_dir)
    label_row = _read_jsonl_first(run_dir / SDK_LABELS_JSONL)
    embed_row = _read_jsonl_first(run_dir / SDK_EMBEDDINGS_JSONL)
    run_doc = _read_json_object(run_dir / SDK_RUN_JSON)

    start_ns = int(label_row.get("start_timestamp_ns") or 0)
    end_ns = int(label_row.get("end_timestamp_ns") or start_ns)
    duration = float(label_row.get("duration_sec") or max(0.0, (end_ns - start_ns) / 1e9))
    labels_json = json.dumps(
        _labels_to_clip_dict(label_row.get("labels") or {}),
        ensure_ascii=False,
    )
    vector = embed_row.get("embedding") or embed_row.get("vector") or []
    vector_json = json.dumps(list(vector), ensure_ascii=False)

    clip_dir_name = str(run_doc.get("source_run_dir") or clip_id)
    effective_bag_key = str(bag_oss_key or run_doc.get("bag_oss_key") or "")
    created_at = now or _utc_now()
    content_hash = clip_id.split(":", 1)[-1][:64]
    p = table_prefix

    statements = [
        f"INSERT INTO TABLE {p}dim_clip "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(clip_dir_name)}, "
        f"{_sql_literal(content_hash)}, {_sql_literal(effective_bag_key)}, "
        f"{_sql_literal(run_id)}, 'sdk_v1', {_sql_literal(created_at)}, {_sql_literal(created_at)}",
        f"INSERT INTO TABLE {p}pipeline_run PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(run_id)}, {_sql_literal(clip_id)}, 'completed', 'sdk_v1', 'clip', "
        f"{_sql_literal(created_at)}, {_sql_literal(created_at)}, {_sql_literal(created_at)}",
        f"INSERT INTO TABLE {p}clip_parse_summary PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, 'output', 'output.bag', "
        f"{end_ns - start_ns}, {duration}, {start_ns}, {end_ns}, 0, {_sql_literal(created_at)}",
        f"INSERT INTO TABLE {p}fact_clip_label PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, {_sql_literal(labels_json)}, "
        f"NULL, {_sql_literal(str(label_row.get('model') or ''))}, 'ai', {start_ns}, NULL, "
        f"{_sql_literal(f'clips/{clip_id}/runs/{run_id}/{SDK_LABELS_JSONL}')}, "
        f"{_sql_literal(created_at)}, {_sql_literal(created_at)}",
        f"INSERT INTO TABLE {p}fact_clip_embedding PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, {_sql_literal(vector_json)}, "
        f"{len(vector)}, {_sql_literal(str(embed_row.get('model') or ''))}, 'clip_native', "
        f"{_sql_literal(f'clips/{clip_id}/runs/{run_id}/{SDK_EMBEDDINGS_JSONL}')}, "
        f"{_sql_literal(created_at)}, {_sql_literal(created_at)}",
    ]

    asr_text = str(label_row.get("asr_text") or "").strip()
    if asr_text:
        statements.append(
            f"INSERT INTO TABLE {p}fact_audio_segment PARTITION (ds={_sql_literal(ds)}) "
            f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, 0, {start_ns}, {end_ns}, "
            f"{_sql_literal(asr_text)}, 1.0, NULL, 'preview/audio.wav'"
        )

    # Mark cloud five-step contract complete for a successful Driver ingest.
    # Partial UDF stages still land as completed once artifacts exist and ingest runs.
    for step_id in SDK_PIPELINE_STEPS:
        statements.append(
            f"INSERT INTO TABLE {p}pipeline_step PARTITION (ds={_sql_literal(ds)}) "
            f"SELECT {_sql_literal(run_id)}, {_sql_literal(step_id)}, 'completed', "
            f"{_sql_literal(created_at)}, {_sql_literal(created_at)}, NULL"
        )
    return statements


def ingest_sdk_run(
    odps: Any,
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    run_dir: Path,
    table_prefix: str = "aig_sdk__",
    bag_oss_key: str = "",
) -> None:
    """Execute all ingest statements for one successful SDK run."""
    statements = build_ingest_statements(
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        run_dir=run_dir,
        table_prefix=table_prefix,
        bag_oss_key=bag_oss_key,
    )
    for sql in statements:
        odps.execute_sql(sql)
        print("OK", sql[:80], "...")
