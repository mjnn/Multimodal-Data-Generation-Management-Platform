#!/usr/bin/env python3
"""Verify OSS artifacts and MaxCompute rows after a full pipeline run.

Usage:
  python scripts/verify_pipeline_run.py --clip-id sha256:... --run-id <uuid> --ds 20260609
  python scripts/verify_pipeline_run.py --clip-id sha256:...   # run_id/ds from dim_clip + MC
  python scripts/verify_pipeline_run.py --clip-id sha256:... --run-id <uuid> --json-report out.json

Exit code 0 = all checks passed; 1 = one or more failures.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import oss2
from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from scripts.apply_mc_ddl import load_config

DEFAULT_CLIP_ID = "sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b"

V2_EXPECTED_STEPS = (
    "job1_parse",
    "job1_align",
    "job2_labeling",
    "job2_embedding",
    "job3_labeling_by_other_model",
    "job4_label_merge_and_compare",
)
LEGACY_EXPECTED_STEPS = ("job1_parse", "job2_sample", "job2_asr", "job3_label", "job4_embed")

V2_REQUIRED_OSS_FILES = (
    "parsed/job1_mc_payload.json",
    "aligned/timeline.json",
    "aligned/sync_manifest.jsonl",
    "ai/labels_primary.json",
    "ai/labels_secondary.json",
    "ai/labels_merged.json",
    "ai/consensus_meta.json",
    "ai/embedding.json",
)

LEGACY_REQUIRED_OSS_FILES = (
    "parsed/job1_mc_payload.json",
    "job2/sample_manifest.jsonl",
    "job2/job2_sample_payload.json",
    "job2/job2_asr_payload.json",
    "job2/job2_mc_payload.json",
    "job3/frame_labels.jsonl",
    "job3/job3_mc_payload.json",
    "job4/embeddings.jsonl",
    "job4/job4_mc_payload.json",
)

MC_COUNT_TABLES = (
    "fact_message_timeline",
    "fact_frame",
    "fact_audio_chunk",
    "clip_parse_summary",
    "fact_sample_policy",
    "fact_audio_segment",
    "fact_image_label",
    "fact_embedding",
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_prefix(settings: dict[str, str], clip_id: str, run_id: str) -> str:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs_subdir}/"


def _count_run_across_partitions(
    odps: ODPS,
    table_prefix: str,
    table_suffix: str,
    *,
    clip_id: str,
    run_id: str,
) -> tuple[int, dict[str, int]]:
    table_name = f"{table_prefix}{table_suffix}"
    if not odps.exist_table(table_name):
        return 0, {}
    by_ds: dict[str, int] = {}
    for ds_value in _list_table_ds_partitions(odps, table_name):
        count = _count_rows_for_run(
            odps,
            table_name,
            run_id=run_id,
            ds=ds_value,
            clip_id=clip_id,
        )
        if count:
            by_ds[ds_value] = count
    return sum(by_ds.values()), by_ds


def _steps_across_partitions(
    odps: ODPS,
    table_prefix: str,
    run_id: str,
) -> tuple[dict[str, str], dict[str, str]]:
    table_name = f"{table_prefix}pipeline_step"
    steps: dict[str, str] = {}
    step_ds: dict[str, str] = {}
    if not odps.exist_table(table_name):
        return steps, step_ds
    for ds_value in _list_table_ds_partitions(odps, table_name):
        sql = (
            f"SELECT step_id, status FROM {table_name} "
            f"WHERE run_id={_sql_literal(run_id)} AND ds={_sql_literal(ds_value)}"
        )
        with odps.execute_sql(sql).open_reader() as reader:
            for row in reader:
                if hasattr(row, "step_id"):
                    sid = str(row.step_id)
                    status = str(row.status)
                else:
                    sid = str(row[0])
                    status = str(row[1])
                steps[sid] = status
                step_ds[sid] = ds_value
    return steps, step_ds


def _format_by_ds(by_ds: dict[str, int]) -> str:
    if not by_ds:
        return "rows=0"
    if len(by_ds) == 1:
        ds_value, count = next(iter(by_ds.items()))
        return f"rows={count} ds={ds_value}"
    parts = ", ".join(f"{ds}:{count}" for ds, count in sorted(by_ds.items()))
    return f"rows={sum(by_ds.values())} by_ds={{{parts}}}"


def _resolve_run_id(odps: ODPS, table_prefix: str, clip_id: str, run_id: str | None) -> str:
    if run_id:
        return run_id
    sql = (
        f"SELECT active_run_id FROM {table_prefix}dim_clip "
        f"WHERE clip_id={_sql_literal(clip_id)} LIMIT 1"
    )
    with odps.execute_sql(sql).open_reader() as reader:
        rows = list(reader)
    if not rows or not rows[0][0]:
        raise SystemExit(
            f"No active_run_id for clip_id={clip_id}. Pass --run-id or complete Job1 MC write."
        )
    return str(rows[0][0])


def _partition_ds_value(part_name: str) -> str:
    part_name = part_name.strip()
    if part_name.startswith("ds="):
        return part_name.split("=", 1)[1].strip().strip("'").strip('"')
    return part_name


def _list_table_ds_partitions(odps: ODPS, table_name: str) -> list[str]:
    if not odps.exist_table(table_name):
        return []
    table = odps.get_table(table_name)
    if not table.table_schema.partitions:
        return []
    return sorted({_partition_ds_value(part.name) for part in table.partitions}, reverse=True)


def _is_valid_ds(value: str) -> bool:
    return len(value) == 8 and value.isdigit()


def _count_rows_for_run(
    odps: ODPS,
    table_name: str,
    *,
    run_id: str,
    ds: str,
    clip_id: str | None = None,
) -> int:
    if not odps.exist_table(table_name):
        return 0
    where = [f"run_id={_sql_literal(run_id)}", f"ds={_sql_literal(ds)}"]
    if clip_id is not None:
        where.append(f"clip_id={_sql_literal(clip_id)}")
    sql = f"SELECT COUNT(*) FROM {table_name} WHERE {' AND '.join(where)}"
    with odps.execute_sql(sql).open_reader() as reader:
        return int(list(reader)[0][0])


def _head_object(bucket: oss2.Bucket, key: str) -> oss2.models.HeadObjectResult | None:
    try:
        return bucket.head_object(key)
    except oss2.exceptions.NoSuchKey:
        return None
    except oss2.exceptions.NotFound:
        return None


def _list_prefix(bucket: oss2.Bucket, prefix: str) -> list[str]:
    normalized = prefix.strip("/")
    scan_prefix = f"{normalized}/" if normalized else ""
    return [obj.key for obj in oss2.ObjectIterator(bucket, prefix=scan_prefix)]


def verify_oss(
    bucket: oss2.Bucket,
    run_prefix: str,
    *,
    required_files: tuple[str, ...],
    legacy: bool,
    min_asr_segments: int,
    min_parsed_objects: int,
) -> tuple[list[Check], dict[str, Any]]:
    checks: list[Check] = []
    meta: dict[str, Any] = {"payloads": {}}

    for rel in required_files:
        key = f"{run_prefix}{rel}"
        head = _head_object(bucket, key)
        if head is None:
            checks.append(Check(f"oss:{rel}", False, "missing"))
            continue
        checks.append(
            Check(f"oss:{rel}", True, f"size={head.content_length} bytes")
        )
        if rel.endswith("_payload.json") or rel.endswith("job1_mc_payload.json"):
            body = bucket.get_object(key).read()
            try:
                payload = json.loads(body)
                meta["payloads"][rel] = {
                    "keys": sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
                }
                if rel == "parsed/job1_mc_payload.json" and isinstance(payload, dict):
                    parse_result = payload.get("parse_result") or {}
                    meta["payloads"][rel]["frames"] = len(parse_result.get("frames") or [])
                    meta["payloads"][rel]["audio_chunks"] = len(parse_result.get("audio_chunks") or [])
            except json.JSONDecodeError as exc:
                checks.append(Check(f"oss:{rel}#json", False, str(exc)))

    if legacy:
        asr_keys = [k for k in _list_prefix(bucket, f"{run_prefix}job2/asr_segments") if k.endswith(".wav")]
        checks.append(
            Check(
                "oss:job2/asr_segments/*.wav",
                len(asr_keys) >= min_asr_segments,
                f"count={len(asr_keys)} (min={min_asr_segments})",
            )
        )

    parsed_keys = _list_prefix(bucket, f"{run_prefix}parsed")
    checks.append(
        Check(
            "oss:parsed/*",
            len(parsed_keys) >= min_parsed_objects,
            f"objects={len(parsed_keys)} (min={min_parsed_objects})",
        )
    )

    return checks, meta


def verify_mc(
    odps: ODPS,
    table_prefix: str,
    *,
    clip_id: str,
    run_id: str,
    expected_steps: tuple[str, ...],
    oss_meta: dict[str, Any],
) -> list[Check]:
    checks: list[Check] = []

    dim_sql = (
        f"SELECT active_run_id, bag_oss_key FROM {table_prefix}dim_clip "
        f"WHERE clip_id={_sql_literal(clip_id)} LIMIT 1"
    )
    with odps.execute_sql(dim_sql).open_reader() as reader:
        dim_rows = list(reader)
    if not dim_rows:
        checks.append(Check("mc:dim_clip", False, "clip_id not found"))
    else:
        active_run_id, bag_key = dim_rows[0][0], dim_rows[0][1]
        checks.append(
            Check(
                "mc:dim_clip.active_run_id",
                str(active_run_id or "") == run_id,
                f"active_run_id={active_run_id!r} expected={run_id}",
            )
        )
        checks.append(
            Check(
                "mc:dim_clip.bag_oss_key",
                bool(bag_key),
                f"bag_oss_key={bag_key!r}",
            )
        )

    run_total, run_by_ds = _count_run_across_partitions(
        odps, table_prefix, "pipeline_run", clip_id=clip_id, run_id=run_id
    )
    checks.append(
        Check(
            "mc:pipeline_run",
            run_total >= 1,
            _format_by_ds(run_by_ds),
        )
    )

    step_status, step_ds = _steps_across_partitions(odps, table_prefix, run_id)
    found_steps = set(step_status)
    missing_steps = [s for s in expected_steps if s not in found_steps]
    checks.append(
        Check(
            "mc:pipeline_step.steps",
            not missing_steps,
            f"missing={missing_steps or 'none'} found={sorted(found_steps)}",
        )
    )
    bad_status = [f"{sid}:{status}" for sid, status in step_status.items() if status != "completed"]
    checks.append(
        Check(
            "mc:pipeline_step.status",
            not bad_status,
            f"non-completed={bad_status or 'none'}",
        )
    )

    ds_values = sorted(set(step_ds.values()))
    invalid_ds = [d for d in ds_values if not _is_valid_ds(d)]
    checks.append(
        Check(
            "mc:ds.partition_format",
            not invalid_ds,
            f"invalid_ds={invalid_ds or 'none'} (use ${{bizdate}}, not literal bizdate)",
        )
    )
    valid_ds_values = [d for d in ds_values if _is_valid_ds(d)]
    checks.append(
        Check(
            "mc:ds.consistency",
            len(valid_ds_values) <= 1,
            f"steps span ds={ds_values} (prefer single yyyyMMdd partition)",
        )
    )

    for suffix in MC_COUNT_TABLES:
        total, by_ds = _count_run_across_partitions(
            odps, table_prefix, suffix, clip_id=clip_id, run_id=run_id
        )
        if not odps.exist_table(f"{table_prefix}{suffix}"):
            checks.append(Check(f"mc:{suffix}", False, "table missing"))
        else:
            checks.append(Check(f"mc:{suffix}", total > 0, _format_by_ds(by_ds)))

    job1_payload = (oss_meta.get("payloads") or {}).get("parsed/job1_mc_payload.json") or {}
    expected_frames = job1_payload.get("frames")
    if isinstance(expected_frames, int) and expected_frames >= 0:
        frame_total, frame_by_ds = _count_run_across_partitions(
            odps, table_prefix, "fact_frame", clip_id=clip_id, run_id=run_id
        )
        checks.append(
            Check(
                "mc:fact_frame vs job1 payload",
                frame_total == expected_frames,
                f"mc={frame_total} payload={expected_frames} {_format_by_ds(frame_by_ds)}",
            )
        )

    return checks


def _print_checks(checks: list[Check]) -> None:
    width = max((len(c.name) for c in checks), default=10)
    for check in checks:
        mark = "OK" if check.ok else "FAIL"
        print(f"[{mark:4}] {check.name:<{width}}  {check.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify OSS + MC after full pipeline run.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    parser.add_argument("--clip-id", default=DEFAULT_CLIP_ID)
    parser.add_argument("--run-id", help="Pipeline run UUID; default: dim_clip.active_run_id")
    parser.add_argument("--ds", help="Optional: only used for display/report; MC checks scan all partitions")
    parser.add_argument(
        "--legacy",
        action="store_true",
        help="Verify legacy sample/asr/label/embed pipeline (pre clip-omni v2)",
    )
    parser.add_argument("--oss-only", action="store_true")
    parser.add_argument("--mc-only", action="store_true")
    parser.add_argument("--min-asr-segments", type=int, default=1)
    parser.add_argument("--min-parsed-objects", type=int, default=5)
    parser.add_argument("--json-report", type=Path, help="Write check results as JSON")
    args = parser.parse_args()

    if args.oss_only and args.mc_only:
        raise SystemExit("Use at most one of --oss-only and --mc-only")

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    settings = require_odps_settings(resolve_cloud_settings(config))
    table_prefix = settings["table_prefix"] or "aig_rosbag__"

    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )

    run_id = _resolve_run_id(odps, table_prefix, args.clip_id, args.run_id)

    run_prefix = _run_prefix(settings, args.clip_id, run_id)
    bucket_name = settings["oss_bucket"]

    expected_steps = LEGACY_EXPECTED_STEPS if args.legacy else V2_EXPECTED_STEPS
    required_files = LEGACY_REQUIRED_OSS_FILES if args.legacy else V2_REQUIRED_OSS_FILES

    print("=== Pipeline verify ===")
    print(f"project={settings['odps_project']} bucket={bucket_name}")
    print(f"pipeline={'legacy' if args.legacy else 'clip_omni_v2'}")
    print(f"clip_id={args.clip_id}")
    print(f"run_id={run_id}")
    if args.ds:
        print(f"ds(hint)={args.ds}")
    print(f"oss_run_prefix={run_prefix}")
    print()

    all_checks: list[Check] = []
    oss_meta: dict[str, Any] = {}

    if not args.mc_only:
        auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
        bucket = oss2.Bucket(auth, settings["oss_endpoint"], bucket_name)
        print("--- OSS ---")
        oss_checks, oss_meta = verify_oss(
            bucket,
            run_prefix,
            required_files=required_files,
            legacy=args.legacy,
            min_asr_segments=args.min_asr_segments,
            min_parsed_objects=args.min_parsed_objects,
        )
        _print_checks(oss_checks)
        all_checks.extend(oss_checks)
        print()

    if not args.oss_only:
        print("--- MaxCompute ---")
        mc_checks = verify_mc(
            odps,
            table_prefix,
            clip_id=args.clip_id,
            run_id=run_id,
            expected_steps=expected_steps,
            oss_meta=oss_meta,
        )
        _print_checks(mc_checks)
        all_checks.extend(mc_checks)
        print()

    passed = sum(1 for c in all_checks if c.ok)
    failed = [c for c in all_checks if not c.ok]
    print(f"=== Summary: {passed}/{len(all_checks)} passed ===")
    if failed:
        print("Failed:")
        for check in failed:
            print(f"  - {check.name}: {check.detail}")

    if args.json_report:
        report = {
            "clip_id": args.clip_id,
            "run_id": run_id,
            "ds_hint": args.ds,
            "oss_run_prefix": run_prefix,
            "passed": passed,
            "total": len(all_checks),
            "checks": [asdict(c) for c in all_checks],
            "oss_meta": oss_meta,
        }
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_report}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
