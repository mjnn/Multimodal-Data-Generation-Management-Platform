# =============================================================================
# DataWorks PyODPS 3 节点：Job3-写MC（Driver）
# 粘贴整文件到 PyODPS3 节点；依赖 pyodps、alibabacloud_oss_v2（或 oss2）。
#
# 读 OSS：clips/{clip_id}/runs/{run_id}/job3/job3_mc_payload.json（Driver SDK，不经 MaxFrame Tunnel）
# 写 MC：fact_image_label、pipeline_step（job3_label）
# 幂等：同 ds 分区下先 INSERT OVERWRITE 去掉本 (clip_id, run_id) 旧行再 append
# DataWorks 粘贴：python scripts/bundle_mc_write_node.py dataworks/job3_mc_write_node.py
#
# 工作流参数：
#   oss_bucket=rosbag-labels-pipline-bucket
#   cloud_region=cn_shanghai
#   table_prefix=aig_rosbag__
#   oss_prefix_template=clips/{clip_id}/
#   oss_ram_role_arn=
#   oss_mount_prefix=
#   dpe_cpu=1
#   dpe_memory_gb=4
#   dpe_mount_path=/mnt/oss
#   ds=${bizdate}
#
# 节点参数：
#   clip_id=sha256:...
#   run_id=<与 Job3 打标相同>
# =============================================================================

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from mc_write_idempotent import purge_clip_run_rows, purge_pipeline_step_run
from pipeline_dispatch import (
    exit_if_pipeline_idle,
    read_oss_json_object,
    resolve_oss_http_endpoint,
    resolve_pipeline_context,
)

_PROJECT_DEFAULTS: dict[str, str] = {
    "oss_bucket": "rosbag-labels-pipline-bucket",
    "cloud_region": "cn_shanghai",
    "table_prefix": "aig_rosbag__",
    "oss_prefix_template": "clips/{clip_id}/",
    "oss_mount_prefix": "",
    "dpe_mount_path": "/mnt/oss",
    "dpe_image": "sq_maxframe",
}


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


def _all_arg_sources() -> dict[str, str]:
    merged: dict[str, str] = {}
    merged.update(_parse_skynet_args(os.environ.get("SKYNET_ARGS", "")))
    for env_name, arg_name in (("OSS_BUCKET", "oss_bucket"), ("CLOUD_REGION", "cloud_region")):
        env_value = os.environ.get(env_name, "").strip()
        if env_value:
            merged[arg_name] = env_value
    try:
        node_args = args  # type: ignore[name-defined]
        if isinstance(node_args, dict):
            for key, value in node_args.items():
                if value is not None and str(value).strip():
                    merged[str(key)] = str(value).strip()
    except NameError:
        pass
    return merged


def get_arg(name: str, default: str | None = None) -> str | None:
    if default is None:
        default = _PROJECT_DEFAULTS.get(name)
    value = _all_arg_sources().get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip()


def require_arg(name: str) -> str:
    value = get_arg(name)
    if not value:
        resolved = _all_arg_sources()
        raise ValueError(
            f"Missing required parameter: {name}. "
            f"Resolved keys: {sorted(resolved.keys()) or '(empty)'}"
        )
    return value


def get_int_arg(name: str, default: int) -> int:
    value = get_arg(name)
    return default if value is None else int(value)


def _resolve_ds() -> str:
    ds = get_arg("ds") or get_arg("bizdate") or ""
    if not ds or "${" in ds:
        ds = os.environ.get("SKYNET_BIZDATE", "").strip()
    if not ds:
        raise ValueError(
            "Missing partition parameter: ds or bizdate "
            "(DataWorks 手动跑时 ${bizdate} 可能未展开，需 SKYNET_BIZDATE 或写死 ds=20260608)"
        )
    return ds


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table_name(prefix: str, base: str) -> str:
    return f"{prefix}{base}"


def _clip_prefix(template: str, clip_id: str) -> str:
    return template.format(clip_id=clip_id).strip("/")


def write_job3_to_mc(
    client: Any,
    *,
    table_prefix: str,
    ds: str,
    clip_id: str,
    run_id: str,
    payload: dict[str, Any],
) -> None:
    now = _utc_now_iso()
    partition = f"ds={ds}"
    model_version = str(payload.get("label_model_version") or "none")

    label_rows = [
        [
            clip_id,
            run_id,
            str(item["frame_id"]),
            int(item["timestamp_ns"]),
            json.dumps(item.get("labels_json") or {}, ensure_ascii=False),
            model_version,
            str(item.get("sync_group_id") or ""),
            int(item.get("anchor_timestamp_ns") or 0),
            str(item.get("label_scope") or ("sync_group" if item.get("sync_group_id") else "frame")),
        ]
        for item in payload.get("labeled_frames") or []
    ]
    label_table_name = _table_name(table_prefix, "fact_image_label")
    purge_clip_run_rows(
        client,
        table_name=label_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, frame_id, timestamp_ns, labels_json, model_version, "
            "sync_group_id, anchor_timestamp_ns, label_scope"
        ),
    )
    if label_rows:
        label_table = client.get_table(label_table_name)
        with label_table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(label_rows)

    step_table_name = _table_name(table_prefix, "pipeline_step")
    purge_pipeline_step_run(
        client,
        table_name=step_table_name,
        ds=ds,
        run_id=run_id,
        step_id="job3_label",
    )
    step_table = client.get_table(step_table_name)
    with step_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write([[run_id, "job3_label", "completed", now, now, None]])


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job3_mc_write"):
        return
    clip_id = pipeline_ctx["clip_id"]
    run_id = pipeline_ctx["run_id"]
    ds = _resolve_ds()

    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    table_prefix = get_arg("table_prefix", "aig_rosbag__")
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/")

    clip_prefix = _clip_prefix(prefix_template, clip_id)
    payload_key = f"{clip_prefix}/runs/{run_id}/job3/job3_mc_payload.json"
    oss_endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    print(f"Job3 MC write: reading oss://{oss_bucket}/{payload_key} via {oss_endpoint}")
    payload = read_oss_json_object(
        bucket_name=oss_bucket,
        object_key=payload_key,
        endpoint=oss_endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if payload is None:
        raise FileNotFoundError(
            f"Job3 payload not found: oss://{oss_bucket}/{payload_key} (run job3_label first)"
        )

    resolved_clip_id = str(payload.get("clip_id", clip_id))
    resolved_run_id = str(payload.get("run_id", run_id))
    write_job3_to_mc(
        o,  # type: ignore[name-defined]
        table_prefix=table_prefix,
        ds=ds,
        clip_id=resolved_clip_id,
        run_id=resolved_run_id,
        payload=payload,
    )
    print(
        f"Job3 MC write done: clip_id={resolved_clip_id} run_id={resolved_run_id} ds={ds} "
        f"labeled_frames={len(payload.get('labeled_frames') or [])} "
        f"model={payload.get('label_model_version')}"
    )


main()
