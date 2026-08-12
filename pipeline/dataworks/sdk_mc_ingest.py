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


def build_run_json_document(
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    bag_oss_key: str = "",
    stages_done: tuple[str, ...] | list[str] = (),
    model_backend: str = "mc",
    extra: dict[str, Any] | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    """sdk_v1 run.json schema (matches OMS ``write_run_json`` / verify_sdk_v1_run)."""
    doc: dict[str, Any] = {
        "layout_version": "sdk_v1",
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": ds,
        "bag_oss_key": bag_oss_key,
        "sdk_files": {
            "labels": SDK_LABELS_JSONL,
            "embeddings": SDK_EMBEDDINGS_JSONL,
            "videos": "clip_videos.jsonl",
        },
        "preview_manifest": "preview/manifest.json",
        "stages_done": list(stages_done),
        "model_backend": model_backend,
        "completed_at": completed_at or _utc_now(),
    }
    if extra:
        doc.update(extra)
    return doc


def format_run_json_body(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


def _fetch_dim_clip_created_at(odps: Any, table_name: str, clip_id: str) -> str | None:
    sql = (
        f"SELECT created_at FROM {table_name} "
        f"WHERE clip_id = {_sql_literal(clip_id)} LIMIT 1"
    )
    with odps.execute_sql(sql).open_reader() as reader:
        rows = list(reader)
    if not rows:
        return None
    value = rows[0][0]
    return None if value is None else str(value)


def build_dim_clip_upsert_sql(
    *,
    clip_id: str,
    clip_dir_name: str,
    content_hash: str,
    bag_oss_key: str,
    run_id: str,
    created_at: str,
    updated_at: str,
    table_prefix: str = "aig_sdk__",
) -> str:
    """INSERT OVERWRITE merge: one row per clip_id with active_run_id = this run.

    Plain INSERT INTO would append duplicates; verify/HMI then may see a stale
    active_run_id. Same pattern as job1_mc_write_node._upsert_dim_clip.
    """
    p = table_prefix
    cols = (
        "clip_id, clip_dir_name, content_hash, bag_oss_key, "
        "active_run_id, layout_version, created_at, updated_at"
    )
    return (
        f"INSERT OVERWRITE TABLE {p}dim_clip "
        f"SELECT {cols} FROM {p}dim_clip WHERE clip_id != {_sql_literal(clip_id)} "
        f"UNION ALL "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(clip_dir_name)}, "
        f"{_sql_literal(content_hash)}, {_sql_literal(bag_oss_key)}, "
        f"{_sql_literal(run_id)}, 'sdk_v1', {_sql_literal(created_at)}, "
        f"{_sql_literal(updated_at)}"
    )


def upsert_dim_clip_active_run(
    odps: Any,
    *,
    clip_id: str,
    run_id: str,
    table_prefix: str = "aig_sdk__",
    bag_oss_key: str = "",
    clip_dir_name: str = "",
    now: str | None = None,
) -> None:
    """Point ``aig_sdk__dim_clip.active_run_id`` at ``run_id`` (overwrite upsert)."""
    updated_at = now or _utc_now()
    table_name = f"{table_prefix}dim_clip"
    created_at = _fetch_dim_clip_created_at(odps, table_name, clip_id) or updated_at
    content_hash = clip_id.split(":", 1)[-1][:64]
    sql = build_dim_clip_upsert_sql(
        clip_id=clip_id,
        clip_dir_name=clip_dir_name or clip_id,
        content_hash=content_hash,
        bag_oss_key=bag_oss_key,
        run_id=run_id,
        created_at=created_at,
        updated_at=updated_at,
        table_prefix=table_prefix,
    )
    odps.execute_sql(sql)
    print("OK", sql[:80], "...")


def build_ingest_statements(
    *,
    clip_id: str,
    run_id: str,
    ds: str,
    run_dir: Path | None = None,
    table_prefix: str = "aig_sdk__",
    bag_oss_key: str = "",
    now: str | None = None,
    label_row: dict[str, Any] | None = None,
    embed_row: dict[str, Any] | None = None,
    run_doc: dict[str, Any] | None = None,
    include_dim_clip: bool = False,
) -> list[str]:
    """Return SQL statements for SDK jsonl artifacts without contacting ODPS.

    Prefer in-memory ``label_row`` / ``embed_row`` (Driver bare AI path). When
    omitted, read from ``run_dir`` (requires local/mount filesystem).

    ``dim_clip`` is upserted separately via ``upsert_dim_clip_active_run`` so
    ``active_run_id`` is overwritten (not appended). Set ``include_dim_clip=True``
    only for legacy tests that assert a plain INSERT string.
    """
    if label_row is None or embed_row is None:
        if run_dir is None:
            raise ValueError("run_dir or label_row+embed_row required")
        run_dir = Path(run_dir)
        if label_row is None:
            label_row = _read_jsonl_first(run_dir / SDK_LABELS_JSONL)
        if embed_row is None:
            embed_row = _read_jsonl_first(run_dir / SDK_EMBEDDINGS_JSONL)
        if run_doc is None:
            run_doc = _read_json_object(run_dir / SDK_RUN_JSON)
    run_doc = run_doc or {}

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

    statements: list[str] = []
    if include_dim_clip:
        statements.append(
            f"INSERT INTO TABLE {p}dim_clip "
            f"SELECT {_sql_literal(clip_id)}, {_sql_literal(clip_dir_name)}, "
            f"{_sql_literal(content_hash)}, {_sql_literal(effective_bag_key)}, "
            f"{_sql_literal(run_id)}, 'sdk_v1', {_sql_literal(created_at)}, "
            f"{_sql_literal(created_at)}"
        )

    statements.extend(
        [
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
    )

    asr_text = str(label_row.get("asr_text") or "").strip()
    if asr_text:
        statements.append(
            f"INSERT INTO TABLE {p}fact_audio_segment PARTITION (ds={_sql_literal(ds)}) "
            f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, 0, {start_ns}, {end_ns}, "
            f"{_sql_literal(asr_text)}, 1.0, NULL, 'preview/audio.wav'"
        )

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
    run_dir: Path | None = None,
    table_prefix: str = "aig_sdk__",
    bag_oss_key: str = "",
    label_row: dict[str, Any] | None = None,
    embed_row: dict[str, Any] | None = None,
    run_doc: dict[str, Any] | None = None,
) -> None:
    """Execute all ingest statements for one successful SDK run."""
    # Resolve clip_dir_name / bag key the same way as build_ingest_statements.
    resolved_doc = run_doc
    if resolved_doc is None and run_dir is not None:
        resolved_doc = _read_json_object(Path(run_dir) / SDK_RUN_JSON)
    resolved_doc = resolved_doc or {}
    clip_dir_name = str(resolved_doc.get("source_run_dir") or clip_id)
    effective_bag_key = str(bag_oss_key or resolved_doc.get("bag_oss_key") or "")

    upsert_dim_clip_active_run(
        odps,
        clip_id=clip_id,
        run_id=run_id,
        table_prefix=table_prefix,
        bag_oss_key=effective_bag_key,
        clip_dir_name=clip_dir_name,
    )

    statements = build_ingest_statements(
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        run_dir=run_dir,
        table_prefix=table_prefix,
        bag_oss_key=bag_oss_key,
        label_row=label_row,
        embed_row=embed_row,
        run_doc=run_doc,
        include_dim_clip=False,
    )
    for sql in statements:
        odps.execute_sql(sql)
        print("OK", sql[:80], "...")
