#!/usr/bin/env python3
"""Verify uniform_sync pipeline run: OSS payloads + MC sync tables."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import oss2
from odps import ODPS

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
from scripts.apply_mc_ddl import load_config

DEFAULT_CLIP_ID = "sha256:3cd012197d1f2112f51c7414500bb9770a143d1bbd1e1a2aaa84d9eccb51fc7b"


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _list_recent_runs(odps: ODPS, prefix: str, clip_id: str, limit: int = 10) -> list[tuple[str, str, str]]:
    table = f"{prefix}pipeline_run"
    if not odps.exist_table(table):
        return []
    # scan partitions - list ds and query each
    runs: list[tuple[str, str, str]] = []
    table_obj = odps.get_table(table)
    ds_list = sorted(
        {p.name.split("=", 1)[-1].strip("'\"") for p in table_obj.partitions},
        reverse=True,
    )
    for ds in ds_list[:5]:
        sql = (
            f"SELECT run_id, status, started_at FROM {table} "
            f"WHERE clip_id={_lit(clip_id)} AND ds={_lit(ds)} "
            f"ORDER BY started_at DESC LIMIT {limit}"
        )
        with odps.execute_sql(sql).open_reader() as reader:
            for row in reader:
                runs.append((str(row[0]), str(row[1]), str(row[2])))
    return runs


def _labels_fingerprint(labels_json: Any) -> str:
    text = json.dumps(labels_json, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _pick_run_with_uniform_sync(
    bucket: oss2.Bucket,
    settings: dict[str, str],
    clip_id: str,
    candidates: list[str],
) -> str | None:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    for run_id in candidates:
        key = f"{clip_prefix}/runs/{run_id}/job2/job2_sample_payload.json"
        try:
            payload = json.loads(bucket.get_object(key).read())
        except Exception:
            continue
        if str(payload.get("sample_policy_name") or "") == "uniform_sync" and payload.get("sample_sync_mode"):
            return run_id
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip-id", default=DEFAULT_CLIP_ID)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    cfg = load_config(PROJECT_ROOT / "config.yaml")
    settings = require_odps_settings(resolve_cloud_settings(cfg))
    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )
    prefix = settings["table_prefix"] or "aig_rosbag__"
    bucket_name = settings["oss_bucket"]
    auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
    endpoint = settings.get("oss_endpoint") or "https://oss-cn-shanghai.aliyuncs.com"
    bucket = oss2.Bucket(auth, endpoint, bucket_name)

    clip_id = args.clip_id
    run_id = args.run_id.strip()
    if not run_id:
        recent = _list_recent_runs(odps, prefix, clip_id)
        if recent:
            print("Recent pipeline_run:")
            for rid, status, started in recent[:8]:
                print(f"  {rid} status={status} started={started}")
            candidate_ids = [r[0] for r in recent]
            picked = _pick_run_with_uniform_sync(bucket, settings, clip_id, candidate_ids)
            if picked:
                run_id = picked
                print(f"auto-selected uniform_sync run_id={run_id}")
        if not run_id:
            sql = (
                f"SELECT active_run_id FROM {prefix}dim_clip "
                f"WHERE clip_id={_lit(clip_id)} LIMIT 1"
            )
            with odps.execute_sql(sql).open_reader() as reader:
                rows = list(reader)
            if not rows or not rows[0][0]:
                print("FAIL: no run_id; pass --run-id")
                return 1
            run_id = str(rows[0][0])
            print(f"fallback active_run_id={run_id}")

    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    run_prefix = f"{clip_prefix}/runs/{run_id}/"
    print(f"clip_id={clip_id}")
    print(f"run_id={run_id}")
    print(f"oss_prefix={run_prefix}")

    failures: list[str] = []

    def load_json(key: str) -> dict[str, Any]:
        obj = bucket.get_object(key)
        return json.loads(obj.read())

    job2_key = f"{run_prefix}job2/job2_sample_payload.json"
    job3_key = f"{run_prefix}job3/job3_mc_payload.json"
    job2_mc_key = f"{run_prefix}job2/job2_mc_payload.json"

    try:
        job2 = load_json(job2_key)
    except Exception as exc:
        print(f"FAIL: cannot read {job2_key}: {exc}")
        return 1

    policy = str(job2.get("sample_policy_name") or "")
    sync_mode = bool(job2.get("sample_sync_mode"))
    groups = job2.get("sample_groups") or []
    frames = job2.get("sampled_frames") or []

    print("\n=== Job2 OSS ===")
    print(f"sample_policy_name={policy!r} sample_sync_mode={sync_mode}")
    print(f"sampled_frames={len(frames)} sample_groups={len(groups)}")

    if policy != "uniform_sync":
        failures.append(f"sample_policy_name={policy!r}, expected uniform_sync")
    if not sync_mode:
        failures.append("sample_sync_mode is false")
    if not groups:
        failures.append("sample_groups empty")
    if frames and groups and len(frames) != len(groups) * 4:
        failures.append(
            f"frame/group ratio: {len(frames)} frames vs {len(groups)} groups (expected groups*4)"
        )

    by_group: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for frame in frames:
        sg = str(frame.get("sync_group_id") or "").strip()
        if sg:
            by_group[sg].append(frame)

    bad_group_size = [sg for sg, items in by_group.items() if len(items) != 4]
    if bad_group_size:
        failures.append(f"groups without 4 frames: {bad_group_size[:5]}")

    cameras_ok = 0
    for sg, items in by_group.items():
        cams = {str(i.get("camera")) for i in items}
        if cams == {"camera0", "camera1", "camera2", "camera3"}:
            cameras_ok += 1
    print(f"groups_with_4_cameras={cameras_ok}/{len(by_group)}")

    anchor_mismatch = 0
    for frame in frames:
        sg = str(frame.get("sync_group_id") or "")
        anchor = int(frame.get("anchor_timestamp_ns") or 0)
        for group in groups:
            if group.get("sync_group_id") == sg:
                if int(group.get("anchor_timestamp_ns") or 0) != anchor:
                    anchor_mismatch += 1
                break
    if anchor_mismatch:
        failures.append(f"anchor_timestamp_ns mismatch count={anchor_mismatch}")

    try:
        job3 = load_json(job3_key)
    except Exception as exc:
        failures.append(f"job3 payload missing/unreadable: {exc}")
        job3 = {}

    print("\n=== Job3 OSS ===")
    labeled = job3.get("labeled_frames") or []
    print(f"sample_sync_mode={job3.get('sample_sync_mode')} labeled_frames={len(labeled)}")

    if labeled and len(labeled) != len(frames):
        failures.append(
            f"job3 labeled_frames={len(labeled)} != job2 sampled_frames={len(frames)}"
        )

    label_by_group: dict[str, set[str]] = defaultdict(set)
    scope_by_group: dict[str, set[str]] = defaultdict(set)
    for item in labeled:
        sg = str(item.get("sync_group_id") or item.get("labels_json", {}).get("sync_group_id") or "")
        if not sg:
            failures.append("labeled frame missing sync_group_id")
            continue
        fp = _labels_fingerprint(item.get("labels_json"))
        label_by_group[sg].add(fp)
        scope = str(item.get("label_scope") or item.get("labels_json", {}).get("label_scope") or "")
        scope_by_group[sg].add(scope)

    multi_label_groups = [sg for sg, fps in label_by_group.items() if len(fps) > 1]
    if multi_label_groups:
        failures.append(
            f"sync groups with differing labels_json: {multi_label_groups[:5]} "
            f"(count={len(multi_label_groups)})"
        )
    else:
        print(f"all_sync_groups_share_one_labels_json: {len(label_by_group)} groups OK")

    bad_scope = [
        sg for sg, scopes in scope_by_group.items()
        if scopes != {"sync_group"} and "sync_group" not in scopes
    ]
    if bad_scope:
        failures.append(f"unexpected label_scope in groups: {bad_scope[:5]}")

    # Sample one group values preview
    if labeled:
        sample = labeled[0]
        values = (sample.get("labels_json") or {}).get("values") or {}
        non_empty = sum(1 for v in values.values() if v not in (None, "", [], {}))
        print(f"sample labels values non_empty={non_empty} anchor_ns={sample.get('anchor_timestamp_ns')}")

    print("\n=== MC ===")
    # resolve ds from pipeline_step or sync group table
    ds_candidates: list[str] = []
    step_table = f"{prefix}pipeline_step"
    if odps.exist_table(step_table):
        t = odps.get_table(step_table)
        for part in sorted(t.partitions, key=lambda p: p.name, reverse=True)[:8]:
            ds_val = part.name.split("=", 1)[-1].strip("'\"")
            sql = (
                f"SELECT 1 FROM {step_table} "
                f"WHERE run_id={_lit(run_id)} AND ds={_lit(ds_val)} LIMIT 1"
            )
            with odps.execute_sql(sql).open_reader() as reader:
                if list(reader):
                    ds_candidates.append(ds_val)
    ds_filter = ds_candidates[0] if ds_candidates else ""
    if ds_filter:
        print(f"mc_ds={ds_filter}")

    def mc_count(table_suffix: str) -> int:
        table = f"{prefix}{table_suffix}"
        if not odps.exist_table(table):
            return -1
        where = f"clip_id={_lit(clip_id)} AND run_id={_lit(run_id)}"
        if ds_filter:
            where += f" AND ds={_lit(ds_filter)}"
        sql = f"SELECT COUNT(*) FROM {table} WHERE {where}"
        with odps.execute_sql(sql).open_reader() as reader:
            return int(list(reader)[0][0])

    for suffix in ("fact_sample_policy", "fact_sample_sync_group", "fact_image_label"):
        count = mc_count(suffix)
        print(f"aig_rosbag__{suffix}: rows={count}")
        if suffix == "fact_sample_sync_group" and count == 0:
            failures.append("fact_sample_sync_group has 0 rows")
        if suffix == "fact_image_label" and labeled and count >= 0 and count != len(labeled):
            failures.append(f"fact_image_label rows={count} != labeled_frames={len(labeled)}")

    if odps.exist_table(f"{prefix}fact_sample_policy") and ds_filter:
        sql = (
            f"SELECT policy_name FROM {prefix}fact_sample_policy "
            f"WHERE clip_id={_lit(clip_id)} AND run_id={_lit(run_id)} AND ds={_lit(ds_filter)} LIMIT 5"
        )
        with odps.execute_sql(sql).open_reader() as reader:
            policies = [str(r[0]) for r in reader]
        print(f"fact_sample_policy names={policies}")
        if policies and "uniform_sync" not in policies:
            failures.append(f"MC policy_name not uniform_sync: {policies}")

    if odps.exist_table(f"{prefix}fact_image_label") and ds_filter:
        sql = (
            f"SELECT sync_group_id, label_scope, COUNT(*) AS c "
            f"FROM {prefix}fact_image_label "
            f"WHERE clip_id={_lit(clip_id)} AND run_id={_lit(run_id)} AND ds={_lit(ds_filter)} "
            f"GROUP BY sync_group_id, label_scope LIMIT 20"
        )
        try:
            with odps.execute_sql(sql).open_reader() as reader:
                print("fact_image_label group sample:")
                for row in reader:
                    print(f"  sync_group_id={row[0]!r} label_scope={row[1]!r} count={row[2]}")
        except Exception as exc:
            failures.append(f"fact_image_label sync columns query failed: {exc}")

    if odps.exist_table(step_table):
        steps: dict[str, str] = {}
        for ds_val in ds_candidates[:3]:
            sql = (
                f"SELECT step_id, status FROM {step_table} "
                f"WHERE run_id={_lit(run_id)} AND ds={_lit(ds_val)}"
            )
            with odps.execute_sql(sql).open_reader() as reader:
                for row in reader:
                    steps[str(row[0])] = str(row[1])
        print(f"pipeline_step={steps}")
        for step in ("job2_sample", "job3_label", "job4_embed"):
            if steps.get(step) != "completed":
                failures.append(f"pipeline_step {step}={steps.get(step)!r}")

    print("\n=== Summary ===")
    if failures:
        print("FAIL")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("PASS: uniform_sync run looks consistent (OSS + MC)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
