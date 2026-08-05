# =============================================================================
# DataWorks PyODPS3：sdk_dispatch_batch（Driver）
#
# 默认 batch_source=upload_run：每次只调度 **一个 upload_run**（一次用户上传），
# 其下 N 个 bag（N 个 clip_id）共享同一个 pipeline run_id。
#
# OSS 上传约定：
#   rosbags/uploads/{upload_run_id}/*.bag
#   rosbags/uploads/{upload_run_id}/.upload_complete   ← 上传完成标记
#
# 粘贴：python scripts/bundle_pipeline_dispatch.py dataworks/sdk_dispatch_batch_node.py
# =============================================================================

from __future__ import annotations

import json
import os
import re
from typing import Any

from pipeline_dispatch import (
    DEFAULT_DISCOVER_OSS_KEY,
    DEFAULT_DISPATCH_OSS_KEY,
    attach_taxonomy_to_dispatch_payload,
    pick_dispatch_batch,
    pick_dispatch_upload_run,
    read_discover_manifest_from_oss,
    resolve_oss_http_endpoint,
    write_dispatch_to_oss,
    write_upload_run_state_to_oss,
)


def _parse_skynet_args(raw: str) -> dict[str, str]:
    text = raw.strip()
    if not text:
        return {}
    if text.startswith("{"):
        loaded = json.loads(text)
        if isinstance(loaded, dict):
            return {str(k): str(v) for k, v in loaded.items()}
    parsed: dict[str, str] = {}
    for token in re.split(r"[;\s]+", text):
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def get_arg(name: str, default: str | None = None) -> str | None:
    merged = _parse_skynet_args(os.environ.get("SKYNET_ARGS", ""))
    try:
        node_args = args  # type: ignore[name-defined]
        if isinstance(node_args, dict):
            merged.update({str(k): str(v) for k, v in node_args.items() if v is not None})
    except NameError:
        pass
    value = merged.get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def require_arg(name: str) -> str:
    value = get_arg(name)
    if not value:
        raise ValueError(f"Missing required parameter: {name}")
    return value


def get_int_arg(name: str, default: int) -> int:
    value = get_arg(name)
    return default if value is None else int(value)


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    table_prefix = get_arg("table_prefix", "aig_sdk__") or "aig_sdk__"
    dispatch_key = get_arg("dispatch_oss_key", DEFAULT_DISPATCH_OSS_KEY) or DEFAULT_DISPATCH_OSS_KEY
    discover_key = get_arg("discover_oss_key", DEFAULT_DISCOVER_OSS_KEY) or DEFAULT_DISCOVER_OSS_KEY
    batch_source = get_arg("batch_source", "upload_run") or "upload_run"
    max_batch = get_int_arg("max_batch", 32)
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/") or "clips/{clip_id}/"
    runs_subdir = get_arg("oss_runs_subdir", "runs/{run_id}/") or "runs/{run_id}/"
    dry_run = str(get_arg("dry_run", "false") or "false").lower() in {"1", "true", "yes"}

    endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    discover_payload = read_discover_manifest_from_oss(
        bucket_name=oss_bucket,
        object_key=discover_key,
        endpoint=endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if discover_payload:
        upload_runs = discover_payload.get("upload_runs") or []
        print(
            f"sdk_dispatch_batch: discover upload_runs={len(upload_runs)} "
            f"new={discover_payload.get('new_count')}"
        )
    else:
        print(f"sdk_dispatch_batch: no discover manifest at oss://{oss_bucket}/{discover_key}")

    if batch_source in {"upload_run", "upload"}:
        payload = pick_dispatch_upload_run(
            o,  # type: ignore[name-defined]
            table_prefix,
            get_arg=get_arg,
            discover_payload=discover_payload,
            oss_account=account,
            oss_bucket=oss_bucket,
            oss_endpoint=endpoint,
            prefix_template=prefix_template,
            runs_subdir_template=runs_subdir,
        )
    else:
        payload = pick_dispatch_batch(
            o,  # type: ignore[name-defined]
            table_prefix,
            get_arg=get_arg,
            discover_payload=discover_payload,
            max_batch=max_batch,
            prefix_template=prefix_template,
            runs_subdir_template=runs_subdir,
        )

    payload = attach_taxonomy_to_dispatch_payload(
        payload,
        o,  # type: ignore[name-defined]
        get_arg=get_arg,
        oss_account=account,
        oss_bucket=oss_bucket,
        oss_endpoint=endpoint,
    )

    print(
        f"sdk_dispatch_batch: action={payload.get('action')} mode={payload.get('mode')} "
        f"upload_run_id={payload.get('upload_run_id', '')} batch_size={payload.get('batch_size', 0)}"
    )
    if payload.get("action") != "run":
        print(f"DISPATCH_BATCH_JSON={json.dumps(payload, ensure_ascii=False)}")
        return

    items = payload.get("items") or []
    for item in items:
        print(
            f"BATCH_ITEM upload_run={item.get('upload_run_id')} clip_id={item.get('clip_id')} "
            f"run_id={item.get('run_id')} bag={item.get('bag_oss_key')}"
        )

    upload_run_state = payload.pop("upload_run_state", None)
    if dry_run:
        print("sdk_dispatch_batch dry_run: skip OSS write")
        print(f"DISPATCH_BATCH_JSON={json.dumps(payload, ensure_ascii=False)}")
        return

    write_dispatch_to_oss(
        bucket_name=oss_bucket,
        object_key=dispatch_key,
        endpoint=endpoint,
        account=account,
        payload=payload,
        region=cloud_region,
        get_arg=get_arg,
    )
    if upload_run_state:
        write_upload_run_state_to_oss(
            payload=upload_run_state,
            bucket_name=oss_bucket,
            endpoint=endpoint,
            account=account,
            region=cloud_region,
            get_arg=get_arg,
        )
    print(f"sdk_dispatch_batch OSS manifest: oss://{oss_bucket}/{dispatch_key}")
    print(f"DISPATCH_BATCH_JSON={json.dumps(payload, ensure_ascii=False)}")
    print(f"NEXT_NODE_PARAM upload_run_id={payload.get('upload_run_id', '')}")
    print(f"NEXT_NODE_PARAM pipeline_run_id={payload.get('pipeline_run_id', payload.get('run_id', ''))}")
    print(f"NEXT_NODE_PARAM batch_size={len(items)}")
    print(f"NEXT_NODE_PARAM dpe_parallel={get_int_arg('dpe_parallel', min(8, max(1, len(items))))}")


if __name__ == "__main__":
    main()
