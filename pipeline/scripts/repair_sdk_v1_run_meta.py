#!/usr/bin/env python3
"""One-shot repair for SDK v1 hybrid runs missing meta (run.json / dispatch / active_run_id).

Use after a successful DataWorks hybrid batch that wrote labels/embed/preview but
skipped run.json (no upload stage), left multi-item dispatch without top-level
clip_id/run_id, and/or appended dim_clip without overwriting active_run_id.

Does NOT re-run extract/ASR/label/embed.

Example (4-bag batch 20260810):

  py -3.11 pipeline/scripts/repair_sdk_v1_run_meta.py \\
    --ds 20260810 \\
    --pair sha256:9a4ac3a2704dd052630c9b3cd320760b9214febc22c53cf14b41b0806f4d81ed:bb319286-3cad-4b56-93f9-32cc25329bb9 \\
    --pair sha256:3f93ff544e06ff19a6ca8416b7471edceef7a7f69f458869d065627d9ab2d71e:66c9aa40-7bd0-45f3-aeac-c76f2c79bc66 \\
    --pair sha256:7cbdbb7f426ff74edd4aafdfa8158ac188dd8eeae0680358e5e225dbe02282af:12c0a501-3568-4001-89fa-6771e07deb92 \\
    --pair sha256:e1bfe3156892d35cdd3e855608366d4c73d028bb6b460bab8c22ba7f823928e9:bcc424e0-dc3c-4d99-bfa7-9b1f70c9bb34
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import oss2
from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
DATAWORKS_ROOT = PIPELINE_ROOT / "dataworks"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, DATAWORKS_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from repo_paths import CONFIG_PATH  # noqa: E402
from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings  # noqa: E402
from hmi.services.pipeline_status import DISPATCH_MANIFEST_KEY  # noqa: E402
from sdk_mc_ingest import (  # noqa: E402
    build_run_json_document,
    format_run_json_body,
    upsert_dim_clip_active_run,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_pair(raw: str) -> tuple[str, str]:
    text = raw.strip()
    # clip_id is sha256:{hex}; run_id is uuid — split on last colon-separated uuid-ish tail
    if ":sha256:" in text:
        raise SystemExit(f"bad --pair (unexpected): {raw!r}")
    # Prefer "clip_id=...;run_id=..." form
    if ";" in text or "=" in text:
        parts = dict(
            p.split("=", 1) for p in text.replace(";", ",").split(",") if "=" in p
        )
        clip_id = (parts.get("clip_id") or "").strip()
        run_id = (parts.get("run_id") or "").strip()
        if clip_id and run_id:
            return clip_id, run_id
    # Default: sha256:HEX:RUN_ID  → split after first "sha256:" hex block
    if text.startswith("sha256:"):
        rest = text[len("sha256:") :]
        if ":" not in rest:
            raise SystemExit(f"--pair needs clip_id:run_id, got {raw!r}")
        hex_part, run_id = rest.split(":", 1)
        return f"sha256:{hex_part}", run_id.strip()
    raise SystemExit(
        f"--pair format: sha256:{{hex}}:{{run_id}} or clip_id=...;run_id=... ; got {raw!r}"
    )


def _run_prefix(settings: dict[str, str], clip_id: str, run_id: str) -> str:
    clip_prefix = settings["oss_prefix_template"].format(clip_id=clip_id).strip("/")
    runs_subdir = settings["oss_runs_subdir"].format(run_id=run_id).strip("/")
    return f"{clip_prefix}/{runs_subdir}/"


def _load_bag_key_from_mc(odps: ODPS, table_prefix: str, clip_id: str) -> str:
    sql = (
        f"SELECT bag_oss_key FROM {table_prefix}dim_clip "
        f"WHERE clip_id = '{clip_id.replace(chr(39), chr(39)+chr(39))}' LIMIT 1"
    )
    with odps.execute_sql(sql).open_reader() as reader:
        rows = list(reader)
    if not rows or rows[0][0] is None:
        return ""
    return str(rows[0][0])


def _object_exists(bucket: oss2.Bucket, key: str) -> bool:
    try:
        bucket.head_object(key)
        return True
    except (oss2.exceptions.NoSuchKey, oss2.exceptions.NotFound):
        return False


def _infer_stages_done(bucket: oss2.Bucket, run_prefix: str) -> list[str]:
    done = ["extract"]
    if _object_exists(bucket, f"{run_prefix}preview/manifest.json") or any(
        True
        for obj in oss2.ObjectIterator(bucket, prefix=f"{run_prefix}preview/", max_keys=5)
    ):
        done.append("preview")
    if _object_exists(bucket, f"{run_prefix}asr.jsonl"):
        done.append("asr")
    if _object_exists(bucket, f"{run_prefix}labels.jsonl"):
        done.append("label")
    if _object_exists(bucket, f"{run_prefix}fusion_embeddings.jsonl"):
        done.append("embed")
    done.append("upload")
    return done


def repair_run_json(
    bucket: oss2.Bucket,
    *,
    settings: dict[str, str],
    clip_id: str,
    run_id: str,
    ds: str,
    bag_oss_key: str,
    dry_run: bool,
) -> str:
    run_prefix = _run_prefix(settings, clip_id, run_id)
    key = f"{run_prefix}run.json"
    if _object_exists(bucket, key):
        return f"skip run.json (exists) key={key}"
    stages = _infer_stages_done(bucket, run_prefix)
    doc = build_run_json_document(
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        bag_oss_key=bag_oss_key,
        stages_done=stages,
        model_backend="mc",
    )
    body = format_run_json_body(doc)
    if dry_run:
        return f"dry-run would put run.json key={key} stages={stages}"
    bucket.put_object(key, body.encode("utf-8"))
    return f"wrote run.json key={key}"


def repair_dispatch(
    bucket: oss2.Bucket,
    *,
    settings: dict[str, str],
    pairs: list[tuple[str, str]],
    ds: str,
    bag_by_clip: dict[str, str],
    dry_run: bool,
) -> str:
    key = DISPATCH_MANIFEST_KEY
    doc: dict[str, Any] = {}
    if _object_exists(bucket, key):
        raw = bucket.get_object(key).read().decode("utf-8")
        loaded = json.loads(raw)
        if isinstance(loaded, dict):
            doc = loaded

    items_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    existing_items = doc.get("items")
    if isinstance(existing_items, list):
        for item in existing_items:
            if isinstance(item, dict) and item.get("clip_id") and item.get("run_id"):
                items_by_key[(str(item["clip_id"]), str(item["run_id"]))] = dict(item)

    for clip_id, run_id in pairs:
        run_prefix = _run_prefix(settings, clip_id, run_id)
        items_by_key[(clip_id, run_id)] = {
            "clip_id": clip_id,
            "run_id": run_id,
            "bag_oss_key": bag_by_clip.get(clip_id, ""),
            "ds": ds,
            "run_relpath": run_prefix.rstrip("/"),
            "run_oss_prefix": run_prefix,
        }

    items = list(items_by_key.values())
    if not items:
        return "dispatch: no items"
    first = items[0]
    # Prefer first repaired pair as top-level compat pointer
    first_pair = pairs[0]
    for item in items:
        if item["clip_id"] == first_pair[0] and item["run_id"] == first_pair[1]:
            first = item
            break

    payload: dict[str, Any] = {
        "action": doc.get("action") or "run",
        "layout_version": "sdk_v1",
        "pipeline_version": doc.get("pipeline_version") or "sdk_v1",
        "batch_size": len(items),
        "items": items,
        "run_oss_prefix": first["run_oss_prefix"],
        "dispatched_at": doc.get("dispatched_at") or _utc_now(),
        "repaired_at": _utc_now(),
    }
    payload.update(first)

    if dry_run:
        return (
            f"dry-run would put dispatch key={key} "
            f"top clip_id={first['clip_id'][:20]}… items={len(items)}"
        )
    bucket.put_object(key, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    return f"wrote dispatch key={key} top={first['clip_id'][:24]}… items={len(items)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair SDK v1 run meta for HMI/verify")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--ds", required=True, help="yyyyMMdd")
    parser.add_argument(
        "--pair",
        action="append",
        default=[],
        help="sha256:{hex}:{run_id} (repeatable)",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-dispatch", action="store_true")
    parser.add_argument("--skip-run-json", action="store_true")
    parser.add_argument("--skip-dim-clip", action="store_true")
    args = parser.parse_args()

    if not args.pair:
        raise SystemExit("pass at least one --pair")

    pairs = [_parse_pair(p) for p in args.pair]
    load_cloud_env(args.env_file)
    import yaml

    with args.config.resolve().open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    settings = require_odps_settings(resolve_cloud_settings(config))
    table_prefix = settings.get("sdk_table_prefix") or settings.get("table_prefix") or "aig_sdk__"

    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )
    auth = oss2.Auth(settings["odps_access_id"], settings["odps_access_key"])
    bucket = oss2.Bucket(auth, settings["oss_endpoint"], settings["oss_bucket"])

    print(f"=== repair_sdk_v1_run_meta ds={args.ds} pairs={len(pairs)} dry_run={args.dry_run} ===")
    print(f"bucket={settings['oss_bucket']} table_prefix={table_prefix}")

    bag_by_clip: dict[str, str] = {}
    for clip_id, run_id in pairs:
        bag_key = _load_bag_key_from_mc(odps, table_prefix, clip_id)
        bag_by_clip[clip_id] = bag_key
        print(f"\n--- {clip_id[:40]}… / {run_id} ---")
        if not args.skip_run_json:
            msg = repair_run_json(
                bucket,
                settings=settings,
                clip_id=clip_id,
                run_id=run_id,
                ds=args.ds,
                bag_oss_key=bag_key,
                dry_run=args.dry_run,
            )
            print(msg)
        if not args.skip_dim_clip:
            if args.dry_run:
                print(f"dry-run would upsert dim_clip.active_run_id={run_id}")
            else:
                upsert_dim_clip_active_run(
                    odps,
                    clip_id=clip_id,
                    run_id=run_id,
                    table_prefix=table_prefix,
                    bag_oss_key=bag_key,
                    clip_dir_name=clip_id,
                )
                print(f"upserted dim_clip.active_run_id={run_id}")

    if not args.skip_dispatch:
        print("\n--- dispatch ---")
        print(
            repair_dispatch(
                bucket,
                settings=settings,
                pairs=pairs,
                ds=args.ds,
                bag_by_clip=bag_by_clip,
                dry_run=args.dry_run,
            )
        )

    print("\nDONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
