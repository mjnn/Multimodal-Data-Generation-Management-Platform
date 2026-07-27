#!/usr/bin/env python3
"""Push SDK jsonl facts from local artifacts into MaxCompute aig_sdk__ tables.

Requires MC tables from sql/maxcompute/aig_sdk__ddl.sql and ODPS credentials in .env.

Usage:
  py -3 scripts/ingest_sdk_run_to_mc.py --clip-id sha256:... --run-id <uuid> --ds 20260727
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from hmi.data_source import artifact_path
from hmi.sdk_ingest import content_hash_from_clip_id, load_sdk_run_json, read_jsonl_first
from hmi.labels_util import labels_to_clip_dict
from hmi.oss_layout import SDK_EMBEDDINGS_JSONL, SDK_LABELS_JSONL


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _prefix(settings: dict[str, str]) -> str:
    return settings.get("sdk_table_prefix") or settings.get("table_prefix") or "aig_sdk__"


def main() -> int:
    load_cloud_env()
    import yaml

    with (CONFIG_PATH).open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    settings = require_odps_settings(resolve_cloud_settings(config))
    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )

    parser = argparse.ArgumentParser(description="Ingest local SDK bundle into MaxCompute")
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--ds", required=True, help="yyyyMMdd partition")
    args = parser.parse_args()

    clip_id = args.clip_id.strip()
    run_id = args.run_id.strip()
    ds = args.ds.strip()
    root = artifact_path(clip_id, run_id, "")
    label_row = read_jsonl_first(root / SDK_LABELS_JSONL)
    embed_row = read_jsonl_first(root / SDK_EMBEDDINGS_JSONL)
    run_doc = load_sdk_run_json(clip_id, run_id) or {}

    start_ns = int(label_row.get("start_timestamp_ns") or 0)
    end_ns = int(label_row.get("end_timestamp_ns") or start_ns)
    duration = float(label_row.get("duration_sec") or max(0.0, (end_ns - start_ns) / 1e9))
    labels_json = json.dumps(labels_to_clip_dict(label_row.get("labels") or {}), ensure_ascii=False)
    vector = embed_row.get("embedding") or embed_row.get("vector") or []
    vector_json = json.dumps(list(vector), ensure_ascii=False)

    clip_dir_name = str(run_doc.get("source_run_dir") or clip_id)
    bag_oss_key = str(run_doc.get("bag_oss_key") or "")
    now = _utc_now()
    p = _prefix(settings)

    statements = [
        f"INSERT INTO TABLE {p}dim_clip "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(clip_dir_name)}, "
        f"{_sql_literal(content_hash_from_clip_id(clip_id))}, {_sql_literal(bag_oss_key)}, "
        f"{_sql_literal(run_id)}, 'sdk_v1', {_sql_literal(now)}, {_sql_literal(now)}",
        f"INSERT INTO TABLE {p}pipeline_run PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(run_id)}, {_sql_literal(clip_id)}, 'completed', 'sdk_v1', 'clip', "
        f"{_sql_literal(now)}, {_sql_literal(now)}, {_sql_literal(now)}",
        f"INSERT INTO TABLE {p}clip_parse_summary PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, 'output', 'output.bag', "
        f"{int((end_ns - start_ns))}, {duration}, {start_ns}, {end_ns}, 0, {_sql_literal(now)}",
        f"INSERT INTO TABLE {p}fact_clip_label PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, {_sql_literal(labels_json)}, "
        f"NULL, {_sql_literal(str(label_row.get('model') or ''))}, 'ai', {start_ns}, NULL, "
        f"{_sql_literal(f'clips/{clip_id}/runs/{run_id}/{SDK_LABELS_JSONL}')}, "
        f"{_sql_literal(now)}, {_sql_literal(now)}",
        f"INSERT INTO TABLE {p}fact_clip_embedding PARTITION (ds={_sql_literal(ds)}) "
        f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, {_sql_literal(vector_json)}, "
        f"{len(vector)}, {_sql_literal(str(embed_row.get('model') or ''))}, 'clip_native', "
        f"{_sql_literal(f'clips/{clip_id}/runs/{run_id}/{SDK_EMBEDDINGS_JSONL}')}, "
        f"{_sql_literal(now)}, {_sql_literal(now)}",
    ]

    asr_text = str(label_row.get("asr_text") or "").strip()
    if asr_text:
        statements.append(
            f"INSERT INTO TABLE {p}fact_audio_segment PARTITION (ds={_sql_literal(ds)}) "
            f"SELECT {_sql_literal(clip_id)}, {_sql_literal(run_id)}, 0, {start_ns}, {end_ns}, "
            f"{_sql_literal(asr_text)}, 1.0, NULL, 'preview/audio.wav'"
        )

    for sql in statements:
        odps.execute_sql(sql)
        print("OK", sql[:80], "...")

    print(f"Ingested SDK run clip_id={clip_id[:24]}… ds={ds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
