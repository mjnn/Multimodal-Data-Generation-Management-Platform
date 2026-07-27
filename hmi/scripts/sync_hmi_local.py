#!/usr/bin/env python3
"""Sync MaxCompute tables + OSS artifacts to local SQLite + files for HMI local mode.

Usage:
  python scripts/sync_hmi_local.py --clip-id sha256:... --run-id <uuid> --ds 20260609
  python scripts/sync_hmi_local.py --clip-id sha256:...   # resolve run/ds from dim_clip + MC
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import oss2
from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from repo_paths import CONFIG_PATH, ENV_PATH

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from hmi.data_source import LOCAL_ARTIFACTS_ROOT, artifacts_dir
from hmi.local import store

DEFAULT_CLIP_ID = "sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b"


def _ingest_local_artifacts(clip_id: str, run_id: str, ds: str) -> dict[str, bool]:
    from hmi.ai_artifacts import ingest_v2_ai_from_local_artifacts

    return ingest_v2_ai_from_local_artifacts(clip_id, run_id, ds)


SDK_MC_TABLES = (
    ("dim_clip", "clip_id", False),
    ("pipeline_run", "clip_id", True),
    ("pipeline_step", None, True),
    ("clip_parse_summary", "clip_id", True),
    ("fact_clip_label", "clip_id", True),
    ("fact_clip_embedding", "clip_id", True),
    ("fact_audio_segment", "clip_id", True),
)

MC_TABLES = SDK_MC_TABLES

ASSET_PREFIXES = (
    "preview/",
    "labels.jsonl",
    "fusion_embeddings.jsonl",
    "clip_videos.jsonl",
    "run.json",
    # legacy v2 (read-only fallback during migration)
    "parsed/",
    "aligned/",
    "ai/",
    "job2/asr_segments/",
    "job2/",
    "job3/",
    "job4/",
)


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _cell(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[1]
    return value


def _row_dict(reader: Any, row: Any) -> dict[str, Any]:
    names = reader.schema.names
    out: dict[str, Any] = {}
    for i, name in enumerate(names):
        if hasattr(row, name):
            out[name] = _cell(getattr(row, name))
        else:
            out[name] = _cell(row[i])
    return out


def _mc_query(odps: ODPS, sql: str) -> list[dict[str, Any]]:
    with odps.execute_sql(sql).open_reader() as reader:
        return [_row_dict(reader, row) for row in reader]


def _list_ds_partitions(odps: ODPS, table_name: str) -> list[str]:
    if not odps.exist_table(table_name):
        return []
    table = odps.get_table(table_name)
    if not table.table_schema.partitions:
        return []
    out: list[str] = []
    for part in table.partitions:
        name = part.name.strip()
        if name.startswith("ds="):
            out.append(name.split("=", 1)[1].strip().strip("'").strip('"'))
    return sorted(set(out), reverse=True)


def _run_prefix(settings: dict[str, str], clip_id: str, run_id: str) -> str:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs_subdir}/"


def resolve_run_ds(
    odps: ODPS, settings: dict[str, str], clip_id: str, run_id: str | None, ds: str | None
) -> tuple[str, str]:
    tbl = f"{settings['table_prefix']}dim_clip"
    if not run_id:
        rows = _mc_query(
            odps,
            f"SELECT active_run_id FROM {tbl} WHERE clip_id={_sql_literal(clip_id)} LIMIT 1",
        )
        if not rows or not rows[0].get("active_run_id"):
            raise SystemExit(f"No active_run_id for {clip_id}")
        run_id = str(rows[0]["active_run_id"])
    if not ds:
        run_tbl = f"{settings['table_prefix']}pipeline_run"
        for ds_candidate in _list_ds_partitions(odps, run_tbl):
            rows = _mc_query(
                odps,
                f"SELECT run_id FROM {run_tbl} WHERE clip_id={_sql_literal(clip_id)} "
                f"AND run_id={_sql_literal(run_id)} AND ds={_sql_literal(ds_candidate)} LIMIT 1",
            )
            if rows:
                ds = ds_candidate
                break
        if not ds:
            step_tbl = f"{settings['table_prefix']}pipeline_step"
            for ds_candidate in _list_ds_partitions(odps, step_tbl):
                rows = _mc_query(
                    odps,
                    f"SELECT run_id FROM {step_tbl} WHERE run_id={_sql_literal(run_id)} "
                    f"AND ds={_sql_literal(ds_candidate)} LIMIT 1",
                )
                if rows:
                    ds = ds_candidate
                    break
        if not ds:
            raise SystemExit(f"No ds partition for clip={clip_id} run={run_id}")
    return run_id, ds


def _upsert_dim_clip(row: dict[str, Any]) -> None:
    store.execute(
        "INSERT INTO dim_clip (clip_id, clip_dir_name, content_hash, bag_oss_key, "
        "active_run_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(clip_id) DO UPDATE SET "
        "clip_dir_name=excluded.clip_dir_name, bag_oss_key=excluded.bag_oss_key, "
        "active_run_id=excluded.active_run_id, updated_at=excluded.updated_at",
        (
            str(row.get("clip_id") or ""),
            str(row.get("clip_dir_name") or ""),
            str(row.get("content_hash") or ""),
            str(row.get("bag_oss_key") or ""),
            str(row.get("active_run_id") or ""),
            str(row.get("created_at") or ""),
            str(row.get("updated_at") or ""),
        ),
    )


def _sync_table(
    odps: ODPS,
    settings: dict[str, str],
    suffix: str,
    clip_id: str,
    run_id: str,
    ds: str,
    *,
    clip_filter: bool,
) -> int:
    tbl = f"{settings['table_prefix']}{suffix}"
    if suffix == "dim_clip":
        sql = f"SELECT * FROM {tbl} WHERE clip_id={_sql_literal(clip_id)} LIMIT 1"
        rows = _mc_query(odps, sql)
        for row in rows:
            _upsert_dim_clip(row)
        return len(rows)

    if suffix == "pipeline_step":
        sql = (
            f"SELECT * FROM {tbl} WHERE run_id={_sql_literal(run_id)} "
            f"AND ds={_sql_literal(ds)}"
        )
    else:
        sql = (
            f"SELECT * FROM {tbl} WHERE clip_id={_sql_literal(clip_id)} "
            f"AND run_id={_sql_literal(run_id)} AND ds={_sql_literal(ds)}"
        )
    rows = _mc_query(odps, sql)
    if not rows:
        return 0

    if suffix == "pipeline_run":
        store.executemany(
            "INSERT OR REPLACE INTO pipeline_run "
            "(run_id, clip_id, ds, status, started_at, updated_at, completed_at, label_granularity) "
            "VALUES (?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["run_id"]),
                    str(r["clip_id"]),
                    str(r.get("ds") or ds),
                    str(r.get("status") or ""),
                    str(r.get("started_at") or ""),
                    str(r.get("updated_at") or ""),
                    str(r.get("completed_at") or ""),
                    str(r.get("label_granularity") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "pipeline_step":
        store.executemany(
            "INSERT OR REPLACE INTO pipeline_step "
            "(run_id, ds, step_id, status, started_at, finished_at, error_message) "
            "VALUES (?,?,?,?,?,?,?)",
            [
                (
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r["step_id"]),
                    str(r.get("status") or ""),
                    str(r.get("started_at") or ""),
                    str(r.get("finished_at") or ""),
                    str(r.get("error_message") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "clip_parse_summary":
        store.executemany(
            "INSERT OR REPLACE INTO clip_parse_summary "
            "(clip_id, run_id, ds, bag_stem, bag_file, duration_ns, duration_sec, "
            "start_time_ns, end_time_ns, message_count, topics_json, parsed_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r.get("bag_stem") or ""),
                    str(r.get("bag_file") or ""),
                    int(r.get("duration_ns") or 0),
                    float(r.get("duration_sec") or 0),
                    int(r.get("start_time_ns") or 0),
                    int(r.get("end_time_ns") or 0),
                    int(r.get("message_count") or 0),
                    str(r.get("topics_json") or ""),
                    str(r.get("parsed_at") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "fact_frame":
        store.executemany(
            "INSERT OR REPLACE INTO fact_frame "
            "(clip_id, run_id, ds, bag_stem, camera, frame_idx, timestamp_ns, topic, image_path) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r.get("bag_stem") or ""),
                    str(r["camera"]),
                    int(r["frame_idx"]),
                    int(r["timestamp_ns"]),
                    str(r.get("topic") or ""),
                    str(r.get("image_path") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "fact_event":
        store.executemany(
            "INSERT OR REPLACE INTO fact_event "
            "(clip_id, run_id, ds, bag_stem, timestamp_ns, event_data) VALUES (?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r.get("bag_stem") or ""),
                    int(r["timestamp_ns"]),
                    str(r.get("event_data") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "fact_audio_segment":
        store.executemany(
            "INSERT OR REPLACE INTO fact_audio_segment "
            "(clip_id, run_id, ds, segment_id, start_ns, end_ns, asr_text, confidence, "
            "model_version, source_chunk_from, source_chunk_to, audio_relpath) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    int(r["segment_id"]),
                    int(r["start_ns"]),
                    int(r["end_ns"]),
                    str(r.get("asr_text") or ""),
                    float(r.get("confidence") or 0),
                    str(r.get("model_version") or ""),
                    int(r.get("source_chunk_from") or 0),
                    int(r.get("source_chunk_to") or 0),
                    "",
                )
                for r in rows
            ],
        )
    elif suffix == "fact_sample_sync_group":
        store.executemany(
            "INSERT OR REPLACE INTO fact_sample_sync_group "
            "(clip_id, run_id, ds, sync_group_id, anchor_timestamp_ns, sample_policy, "
            "align_window_ms, frame_ids_json, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r["sync_group_id"]),
                    int(r.get("anchor_timestamp_ns") or 0),
                    str(r.get("sample_policy") or ""),
                    int(r.get("align_window_ms") or 0),
                    str(r.get("frame_ids_json") or ""),
                    str(r.get("created_at") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "fact_image_label":
        store.executemany(
            "INSERT OR REPLACE INTO fact_image_label "
            "(clip_id, run_id, ds, frame_id, timestamp_ns, labels_json, model_version, "
            "sync_group_id, anchor_timestamp_ns, label_scope) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r["frame_id"]),
                    int(r["timestamp_ns"]),
                    str(r.get("labels_json") or ""),
                    str(r.get("model_version") or ""),
                    str(r.get("sync_group_id") or ""),
                    int(r["anchor_timestamp_ns"]) if r.get("anchor_timestamp_ns") not in (None, "") else None,
                    str(r.get("label_scope") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "fact_clip_label":
        store.executemany(
            "INSERT OR REPLACE INTO fact_clip_label "
            "(clip_id, run_id, ds, labels_json, taxonomy_version_id, model_version, "
            "label_source, anchor_timestamp_ns, multi_ai_meta_json, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r.get("labels_json") or ""),
                    str(r.get("taxonomy_version_id") or "") or None,
                    str(r.get("model_version") or "") or None,
                    str(r.get("label_source") or "ai"),
                    int(r["anchor_timestamp_ns"])
                    if r.get("anchor_timestamp_ns") not in (None, "")
                    else None,
                    str(r.get("multi_ai_meta_json") or "") or None,
                    str(r.get("created_at") or ""),
                    str(r.get("updated_at") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "fact_embedding":
        store.executemany(
            "INSERT OR REPLACE INTO fact_embedding "
            "(clip_id, run_id, ds, object_type, object_id, timestamp_ns, start_ns, end_ns, "
            "vector_json, model_version, dim, storage_mode) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r["object_type"]),
                    str(r["object_id"]),
                    int(r.get("timestamp_ns") or 0),
                    int(r.get("start_ns") or 0),
                    int(r.get("end_ns") or 0),
                    str(r.get("vector_json") or ""),
                    str(r.get("model_version") or ""),
                    int(r.get("dim") or 0),
                    str(r.get("storage_mode") or ""),
                )
                for r in rows
            ],
        )
    elif suffix == "fact_clip_embedding":
        store.executemany(
            "INSERT OR REPLACE INTO fact_clip_embedding "
            "(clip_id, run_id, ds, vector_json, dim, model_version, "
            "aggregation_method, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            [
                (
                    str(r["clip_id"]),
                    str(r["run_id"]),
                    str(r.get("ds") or ds),
                    str(r.get("vector_json") or ""),
                    int(r.get("dim") or 0),
                    str(r.get("model_version") or "") or None,
                    str(r.get("aggregation_method") or "") or None,
                    str(r.get("created_at") or ""),
                    str(r.get("updated_at") or ""),
                )
                for r in rows
            ],
        )
    return len(rows)


def _download_oss_assets(
    settings: dict[str, str],
    clip_id: str,
    run_id: str,
    ds: str,
    *,
    skip_existing: bool,
) -> int:
    auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
    bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])
    prefix = _run_prefix(settings, clip_id, run_id)
    dest_root = artifacts_dir(clip_id, run_id)
    dest_root.mkdir(parents=True, exist_ok=True)
    downloaded = 0
    for obj in oss2.ObjectIterator(bucket, prefix=prefix):
        key = obj.key
        if key.endswith("/"):
            continue
        rel = key[len(prefix) :].lstrip("/")
        if not any(rel.startswith(p) for p in ASSET_PREFIXES):
            continue
        out = dest_root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        if skip_existing and out.is_file() and out.stat().st_size == obj.size:
            continue
        for attempt in range(5):
            try:
                bucket.get_object_to_file(key, str(out))
                break
            except Exception as exc:
                if attempt >= 4:
                    raise
                wait = 2 ** attempt
                print(f"OSS retry {attempt + 1}/5 for {rel}: {exc} (sleep {wait}s)")
                time.sleep(wait)
        downloaded += 1
        if downloaded % 50 == 0:
            print(f"OSS: downloaded {downloaded} files...")

    # Link ASR wav paths for segments
    seg_rows = store.query(
        "SELECT segment_id FROM fact_audio_segment WHERE clip_id=? AND run_id=? AND ds=?",
        (clip_id, run_id, ds),
    )
    asr_dir = dest_root / "job2" / "asr_segments"
    preview_audio = dest_root / "preview" / "audio.wav"
    if preview_audio.is_file() and seg_rows:
        rel = "preview/audio.wav"
        for row in seg_rows:
            store.execute(
                "UPDATE fact_audio_segment SET audio_relpath=? "
                "WHERE clip_id=? AND run_id=? AND ds=? AND segment_id=?",
                (rel, clip_id, run_id, ds, int(row["segment_id"])),
            )
    elif asr_dir.is_dir():
        wavs = sorted(asr_dir.glob("*.wav"))
        for i, row in enumerate(seg_rows):
            if i < len(wavs):
                rel = str(wavs[i].relative_to(dest_root)).replace("\\", "/")
                store.execute(
                    "UPDATE fact_audio_segment SET audio_relpath=? "
                    "WHERE clip_id=? AND run_id=? AND ds=? AND segment_id=?",
                    (rel, clip_id, run_id, ds, int(row["segment_id"])),
                )
    return downloaded


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync cloud MC+OSS to local HMI store")
    parser.add_argument("--clip-id", default=DEFAULT_CLIP_ID)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--ds", default=None)
    parser.add_argument("--skip-oss", action="store_true", help="Only sync MC tables")
    parser.add_argument(
        "--oss-only",
        action="store_true",
        help="Only download/link OSS assets (skip MC clear+sync)",
    )
    parser.add_argument("--skip-existing-oss", action="store_true", default=True)
    args = parser.parse_args()

    load_cloud_env(ENV_PATH)
    import yaml

    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    settings = require_odps_settings(resolve_cloud_settings(config))
    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )

    clip_id = args.clip_id
    run_id, ds = resolve_run_ds(odps, settings, clip_id, args.run_id, args.ds)
    print(f"=== Sync HMI local ===\nclip_id={clip_id}\nrun_id={run_id}\nds={ds}")
    print(f"db={store.ensure_db()}")
    print(f"artifacts={LOCAL_ARTIFACTS_ROOT}")

    total_rows = 0
    if not args.oss_only:
        store.clear_clip_data(clip_id, run_id, ds)
        for suffix, _clip_key, _partitioned in MC_TABLES:
            n = _sync_table(odps, settings, suffix, clip_id, run_id, ds, clip_filter=True)
            print(f"MC {suffix}: {n} rows")
            total_rows += n
    else:
        print("MC: skipped (--oss-only)")

    oss_count = 0
    if not args.skip_oss:
        oss_count = _download_oss_assets(
            settings, clip_id, run_id, ds, skip_existing=args.skip_existing_oss
        )
        print(f"OSS: downloaded {oss_count} files")
        ingested = _ingest_local_artifacts(clip_id, run_id, ds)
        if ingested.get("labels") or ingested.get("embedding"):
            print(f"Local SDK ingest: {ingested}")

    store.set_meta("last_clip_id", clip_id)
    store.set_meta("last_run_id", run_id)
    store.set_meta("last_ds", ds)
    store.set_meta("last_sync_rows", str(total_rows))
    store.set_meta("last_sync_oss_files", str(oss_count))
    print("Done. Set HMI_DATA_SOURCE=local or toggle in UI, then restart backend if needed.")


if __name__ == "__main__":
    main()
