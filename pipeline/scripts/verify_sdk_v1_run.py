#!/usr/bin/env python3
"""Verify SDK v1 (layout_version sdk_v1) OSS + MaxCompute + dispatch after cloud run.

Usage:
  py -3 scripts/verify_sdk_v1_run.py --clip-id sha256:... --run-id <uuid>
  py -3 scripts/verify_sdk_v1_run.py --clip-id sha256:... --run-id <uuid> --ds 20260803
  py -3 scripts/verify_sdk_v1_run.py --clip-id sha256:... --local-artifacts hmi/data/hmi_local/artifacts/...

Exit 0 = all checks passed; 1 = failures.
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
from repo_paths import CONFIG_PATH

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from hmi.config import SDK_PIPELINE_STEP_ORDER
from hmi.oss_layout import (
    SDK_EMBEDDINGS_JSONL,
    SDK_LABELS_JSONL,
    SDK_LAYOUT_VERSION,
    SDK_RUN_JSON_KEY,
    SDK_VIDEOS_JSONL,
)
from hmi.services.pipeline_status import DISPATCH_MANIFEST_KEY
from scripts.apply_mc_ddl import load_config

SDK_REQUIRED_OSS_FILES = (
    SDK_RUN_JSON_KEY,
    SDK_LABELS_JSONL,
    SDK_EMBEDDINGS_JSONL,
    SDK_VIDEOS_JSONL,
    "preview/audio.wav",
)

SDK_MC_TABLES = (
    "clip_parse_summary",
    "fact_clip_label",
    "fact_clip_embedding",
)

STEP_OK_STATUSES = frozenset({"success", "completed", "skipped"})


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


def expected_sdk_steps() -> tuple[str, ...]:
    return tuple(SDK_PIPELINE_STEP_ORDER)


def sdk_required_oss_files() -> tuple[str, ...]:
    return SDK_REQUIRED_OSS_FILES


def validate_run_json(doc: dict[str, Any], *, clip_id: str, run_id: str) -> list[str]:
    errors: list[str] = []
    if doc.get("layout_version") != SDK_LAYOUT_VERSION:
        errors.append(f"layout_version={doc.get('layout_version')!r} expected {SDK_LAYOUT_VERSION!r}")
    if str(doc.get("clip_id") or "") != clip_id:
        errors.append(f"clip_id mismatch: {doc.get('clip_id')!r}")
    if str(doc.get("run_id") or "") != run_id:
        errors.append(f"run_id mismatch: {doc.get('run_id')!r}")
    sdk_files = doc.get("sdk_files")
    if not isinstance(sdk_files, dict):
        errors.append("sdk_files missing or not object")
    return errors


def validate_dispatch_manifest(
    doc: dict[str, Any],
    *,
    clip_id: str,
    run_id: str,
) -> list[str]:
    errors: list[str] = []
    if doc.get("layout_version") != SDK_LAYOUT_VERSION:
        errors.append(f"layout_version={doc.get('layout_version')!r}")
    if str(doc.get("clip_id") or "") != clip_id:
        errors.append(f"clip_id={doc.get('clip_id')!r}")
    if str(doc.get("run_id") or "") != run_id:
        errors.append(f"run_id={doc.get('run_id')!r}")
    if not str(doc.get("run_oss_prefix") or "").strip():
        errors.append("run_oss_prefix empty")
    return errors


def validate_jsonl_row(path: Path, *, require_keys: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    if not path.is_file():
        return [f"missing file {path}"]
    first: dict[str, Any] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        if isinstance(row, dict):
            first = row
            break
    if first is None:
        return ["empty jsonl"]
    for key in require_keys:
        if key not in first:
            errors.append(f"missing key {key!r}")
    return errors


def _sql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _run_prefix(settings: dict[str, str], clip_id: str, run_id: str) -> str:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs_subdir}/"


def _head_object(bucket: oss2.Bucket, key: str) -> oss2.models.HeadObjectResult | None:
    try:
        return bucket.head_object(key)
    except (oss2.exceptions.NoSuchKey, oss2.exceptions.NotFound):
        return None


def _list_prefix(bucket: oss2.Bucket, prefix: str) -> list[str]:
    normalized = prefix.strip("/")
    scan_prefix = f"{normalized}/" if normalized else ""
    return [obj.key for obj in oss2.ObjectIterator(bucket, prefix=scan_prefix)]


def _list_table_ds_partitions(odps: ODPS, table_name: str) -> list[str]:
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
        else:
            out.append(name)
    return sorted(set(out), reverse=True)


def _count_rows_for_run(
    odps: ODPS,
    table_name: str,
    *,
    run_id: str,
    ds: str | None,
    clip_id: str,
) -> int:
    if not odps.exist_table(table_name):
        return 0
    where = [f"run_id={_sql_literal(run_id)}", f"clip_id={_sql_literal(clip_id)}"]
    if ds:
        where.append(f"ds={_sql_literal(ds)}")
    sql = f"SELECT COUNT(*) FROM {table_name} WHERE {' AND '.join(where)}"
    with odps.execute_sql(sql).open_reader() as reader:
        return int(list(reader)[0][0])


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
        raise SystemExit(f"No active_run_id for clip_id={clip_id}; pass --run-id")
    return str(rows[0][0])


def verify_local_artifacts(root: Path, *, clip_id: str, run_id: str) -> list[Check]:
    checks: list[Check] = []
    run_path = root / SDK_RUN_JSON_KEY
    if run_path.is_file():
        try:
            doc = json.loads(run_path.read_text(encoding="utf-8"))
            errs = validate_run_json(doc if isinstance(doc, dict) else {}, clip_id=clip_id, run_id=run_id)
            checks.append(Check("local:run.json", not errs, "; ".join(errs) or "ok"))
        except json.JSONDecodeError as exc:
            checks.append(Check("local:run.json", False, str(exc)))
    else:
        checks.append(Check("local:run.json", False, "missing"))

    for rel, keys in (
        (SDK_LABELS_JSONL, ("clip_id", "labels")),
        (SDK_EMBEDDINGS_JSONL, ("clip_id", "embedding")),
        (SDK_VIDEOS_JSONL, ("clip_id",)),
    ):
        errs = validate_jsonl_row(root / rel, require_keys=keys)
        checks.append(Check(f"local:{rel}", not errs, "; ".join(errs) or "ok"))

    preview_mp4 = list((root / "preview").glob("clip_preview_*.mp4")) if (root / "preview").is_dir() else []
    checks.append(
        Check(
            "local:preview/clip_preview_*.mp4",
            len(preview_mp4) >= 1,
            f"count={len(preview_mp4)}",
        )
    )
    audio = root / "preview" / "audio.wav"
    checks.append(Check("local:preview/audio.wav", audio.is_file(), "ok" if audio.is_file() else "missing"))
    return checks


def verify_oss_sdk_v1(
    bucket: oss2.Bucket,
    run_prefix: str,
    *,
    clip_id: str,
    run_id: str,
) -> tuple[list[Check], dict[str, Any]]:
    checks: list[Check] = []
    meta: dict[str, Any] = {"payloads": {}}

    for rel in sdk_required_oss_files():
        key = f"{run_prefix}{rel}"
        head = _head_object(bucket, key)
        if head is None:
            checks.append(Check(f"oss:{rel}", False, "missing"))
            continue
        checks.append(Check(f"oss:{rel}", True, f"size={head.content_length}"))

    run_key = f"{run_prefix}{SDK_RUN_JSON_KEY}"
    head = _head_object(bucket, run_key)
    if head is not None:
        body = bucket.get_object(run_key).read()
        try:
            doc = json.loads(body)
            if isinstance(doc, dict):
                errs = validate_run_json(doc, clip_id=clip_id, run_id=run_id)
                checks.append(Check("oss:run.json#schema", not errs, "; ".join(errs) or "ok"))
                meta["payloads"][SDK_RUN_JSON_KEY] = {"model_backend": doc.get("model_backend")}
        except json.JSONDecodeError as exc:
            checks.append(Check("oss:run.json#json", False, str(exc)))

    preview_keys = [k for k in _list_prefix(bucket, f"{run_prefix}preview") if k.endswith(".mp4")]
    checks.append(
        Check(
            "oss:preview/*.mp4",
            len(preview_keys) >= 1,
            f"count={len(preview_keys)}",
        )
    )

    for rel, keys in (
        (SDK_LABELS_JSONL, ("clip_id", "labels")),
        (SDK_EMBEDDINGS_JSONL, ("clip_id", "embedding")),
    ):
        key = f"{run_prefix}{rel}"
        head = _head_object(bucket, key)
        if head is None:
            continue
        text = bucket.get_object(key).read().decode("utf-8", errors="replace")
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        if not first_line:
            checks.append(Check(f"oss:{rel}#rows", False, "empty"))
            continue
        try:
            row = json.loads(first_line)
            missing = [k for k in keys if k not in row]
            checks.append(Check(f"oss:{rel}#schema", not missing, f"missing={missing or 'none'}"))
            if rel == SDK_EMBEDDINGS_JSONL:
                emb = row.get("embedding") or []
                meta["embedding_dim"] = len(emb) if isinstance(emb, list) else 0
        except json.JSONDecodeError as exc:
            checks.append(Check(f"oss:{rel}#json", False, str(exc)))

    return checks, meta


def verify_dispatch(bucket: oss2.Bucket, *, clip_id: str, run_id: str) -> list[Check]:
    checks: list[Check] = []
    try:
        body = bucket.get_object(DISPATCH_MANIFEST_KEY).read()
        doc = json.loads(body)
    except Exception as exc:
        checks.append(Check("oss:dispatch/latest.json", False, str(exc)))
        return checks
    if not isinstance(doc, dict):
        checks.append(Check("oss:dispatch/latest.json", False, "not object"))
        return checks
    errs = validate_dispatch_manifest(doc, clip_id=clip_id, run_id=run_id)
    checks.append(Check("oss:dispatch/latest.json", not errs, "; ".join(errs) or "ok"))
    return checks


def verify_mc_sdk_v1(
    odps: ODPS,
    table_prefix: str,
    *,
    clip_id: str,
    run_id: str,
    ds: str | None,
) -> list[Check]:
    checks: list[Check] = []

    dim_sql = (
        f"SELECT active_run_id, layout_version FROM {table_prefix}dim_clip "
        f"WHERE clip_id={_sql_literal(clip_id)} LIMIT 1"
    )
    with odps.execute_sql(dim_sql).open_reader() as reader:
        dim_rows = list(reader)
    if not dim_rows:
        checks.append(Check("mc:dim_clip", False, "clip_id not found"))
    else:
        active_run_id, layout_version = dim_rows[0][0], dim_rows[0][1]
        checks.append(
            Check(
                "mc:dim_clip.active_run_id",
                str(active_run_id or "") == run_id,
                f"active_run_id={active_run_id!r}",
            )
        )
        checks.append(
            Check(
                "mc:dim_clip.layout_version",
                str(layout_version or "") == SDK_LAYOUT_VERSION,
                f"layout_version={layout_version!r}",
            )
        )

    run_count = _count_rows_for_run(odps, f"{table_prefix}pipeline_run", run_id=run_id, ds=ds, clip_id=clip_id)
    checks.append(Check("mc:pipeline_run", run_count >= 1, f"rows={run_count} ds={ds or 'any'}"))

    step_sql = f"SELECT step_id, status FROM {table_prefix}pipeline_step WHERE run_id={_sql_literal(run_id)}"
    if ds:
        step_sql += f" AND ds={_sql_literal(ds)}"
    steps: dict[str, str] = {}
    if odps.exist_table(f"{table_prefix}pipeline_step"):
        with odps.execute_sql(step_sql).open_reader() as reader:
            for row in reader:
                sid = str(row[0] if not hasattr(row, "step_id") else row.step_id)
                status = str(row[1] if not hasattr(row, "status") else row.status)
                steps[sid] = status
    expected = expected_sdk_steps()
    missing = [s for s in expected if s not in steps]
    checks.append(
        Check(
            "mc:pipeline_step.steps",
            not missing,
            f"missing={missing or 'none'} found={sorted(steps)}",
        )
    )
    bad = [f"{sid}:{st}" for sid, st in steps.items() if st not in STEP_OK_STATUSES]
    checks.append(
        Check(
            "mc:pipeline_step.status",
            not bad,
            f"bad={bad or 'none'}",
        )
    )

    for suffix in SDK_MC_TABLES:
        table = f"{table_prefix}{suffix}"
        count = _count_rows_for_run(odps, table, run_id=run_id, ds=ds, clip_id=clip_id)
        if not odps.exist_table(table):
            checks.append(Check(f"mc:{suffix}", False, "table missing"))
        else:
            checks.append(Check(f"mc:{suffix}", count >= 1, f"rows={count}"))

    return checks


def _print_checks(checks: list[Check]) -> None:
    width = max((len(c.name) for c in checks), default=10)
    for check in checks:
        mark = "OK" if check.ok else "FAIL"
        print(f"[{mark:4}] {check.name:<{width}}  {check.detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify SDK v1 cloud run (OSS + MC + dispatch).")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--clip-id", required=True)
    parser.add_argument("--run-id", help="Default: dim_clip.active_run_id")
    parser.add_argument("--ds", help="yyyyMMdd partition filter for MC step/fact tables")
    parser.add_argument("--local-artifacts", type=Path, help="Verify local artifact dir only (no cloud)")
    parser.add_argument("--oss-only", action="store_true")
    parser.add_argument("--mc-only", action="store_true")
    parser.add_argument("--skip-dispatch", action="store_true")
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()

    clip_id = args.clip_id.strip()
    run_id = (args.run_id or "").strip()

    if args.local_artifacts:
        root = args.local_artifacts.resolve()
        if not run_id:
            raise SystemExit("--local-artifacts requires --run-id")
        print("=== SDK v1 local verify ===")
        print(f"root={root}")
        checks = verify_local_artifacts(root, clip_id=clip_id, run_id=run_id)
        _print_checks(checks)
        failed = [c for c in checks if not c.ok]
        print(f"=== Summary: {len(checks) - len(failed)}/{len(checks)} passed ===")
        if failed:
            raise SystemExit(1)
        return

    if args.oss_only and args.mc_only:
        raise SystemExit("Use at most one of --oss-only and --mc-only")

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    settings = require_odps_settings(resolve_cloud_settings(config))
    table_prefix = settings.get("sdk_table_prefix") or settings.get("table_prefix") or "aig_sdk__"

    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )
    run_id = _resolve_run_id(odps, table_prefix, clip_id, run_id or None)
    run_prefix = _run_prefix(settings, clip_id, run_id)
    bucket_name = settings["oss_bucket"]

    print("=== SDK v1 cloud verify ===")
    print(f"project={settings['odps_project']} bucket={bucket_name}")
    print(f"table_prefix={table_prefix}")
    print(f"clip_id={clip_id}")
    print(f"run_id={run_id}")
    if args.ds:
        print(f"ds={args.ds}")
    print(f"oss_run_prefix={run_prefix}")
    print()

    all_checks: list[Check] = []
    meta: dict[str, Any] = {}

    if not args.mc_only:
        auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
        bucket = oss2.Bucket(auth, settings["oss_endpoint"], bucket_name)
        print("--- OSS run tree ---")
        oss_checks, meta = verify_oss_sdk_v1(bucket, run_prefix, clip_id=clip_id, run_id=run_id)
        _print_checks(oss_checks)
        all_checks.extend(oss_checks)
        if not args.skip_dispatch:
            print("--- OSS dispatch ---")
            dispatch_checks = verify_dispatch(bucket, clip_id=clip_id, run_id=run_id)
            _print_checks(dispatch_checks)
            all_checks.extend(dispatch_checks)
        print()

    if not args.oss_only:
        print("--- MaxCompute ---")
        mc_checks = verify_mc_sdk_v1(
            odps,
            table_prefix,
            clip_id=clip_id,
            run_id=run_id,
            ds=args.ds.strip() if args.ds else None,
        )
        _print_checks(mc_checks)
        all_checks.extend(mc_checks)
        print()

    passed = sum(1 for c in all_checks if c.ok)
    failed = [c for c in all_checks if not c.ok]
    print(f"=== Summary: {passed}/{len(all_checks)} passed ===")
    if failed:
        for check in failed:
            print(f"  - {check.name}: {check.detail}")

    if args.json_report:
        report = {
            "layout_version": SDK_LAYOUT_VERSION,
            "clip_id": clip_id,
            "run_id": run_id,
            "ds": args.ds,
            "passed": passed,
            "total": len(all_checks),
            "checks": [asdict(c) for c in all_checks],
            "meta": meta,
        }
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON report: {args.json_report}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
