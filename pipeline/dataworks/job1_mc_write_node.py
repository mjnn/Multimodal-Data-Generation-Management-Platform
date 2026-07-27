# =============================================================================
# DataWorks PyODPS 3 节点：Job1-写MC（节点 2/2，Driver）
# 粘贴整文件到 PyODPS3 节点；依赖 pyodps、alibabacloud_oss_v2（或 oss2）。
#
# 流程：Driver 经 OSS SDK 读 job1_mc_payload.json → 写 aig_rosbag__*
# 禁止经 MaxFrame 回传整份 payload（ODPS STRING 上限 8MB，大 clip 会 Tunnel 失败）
# 幂等：同 ds 分区下先 INSERT OVERWRITE 去掉本 (clip_id, run_id) 旧行再 append
# DataWorks 粘贴：python scripts/bundle_mc_write_node.py dataworks/job1_mc_write_node.py
#
# 工作流参数：
#   oss_bucket=rosbag-labels-pipline-bucket
#   cloud_region=cn_shanghai
#   table_prefix=aig_rosbag__
#   oss_prefix_template=clips/{clip_id}/
#   oss_ram_role_arn=              # 推荐；留空则用 o.account AK/SK
#   oss_mount_prefix=
#   dpe_cpu=1
#   dpe_memory_gb=4
#   dpe_mount_path=/mnt/oss
#   ds=${bizdate}
#
# 节点参数：
#   clip_id=sha256:...
#   run_id=<uuid>
# =============================================================================

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from pipeline_dispatch import (
    exit_if_pipeline_idle,
    read_oss_json_object,
    resolve_oss_http_endpoint,
    resolve_pipeline_context,
)

from mc_write_idempotent import purge_clip_run_rows, purge_pipeline_step_run

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


def _sql_string_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _fetch_dim_clip_created_at(client: Any, table_name: str, clip_id: str) -> str | None:
    safe_clip_id = clip_id.replace("'", "''")
    sql = f"SELECT created_at FROM {table_name} WHERE clip_id = '{safe_clip_id}' LIMIT 1"
    with client.execute_sql(sql).open_reader() as reader:
        rows = list(reader)
    if not rows:
        return None
    value = rows[0][0]
    return None if value is None else str(value)


def _upsert_dim_clip(client: Any, table_name: str, row: list[Any]) -> None:
    """Non-transactional dim_clip: DELETE 不可用，用 INSERT OVERWRITE 合并行。"""
    clip_id = str(row[0]).replace("'", "''")
    columns = (
        "clip_id, clip_dir_name, content_hash, active_run_id, "
        "created_at, updated_at, bag_oss_key"
    )
    new_values = ", ".join(_sql_string_literal(value) for value in row)
    sql = f"""
INSERT OVERWRITE TABLE {table_name}
SELECT {columns} FROM {table_name} WHERE clip_id != '{clip_id}'
UNION ALL
SELECT {new_values}
"""
    client.execute_sql(sql).wait_for_success()


def write_job1_to_mc(
    client: Any,
    *,
    table_prefix: str,
    ds: str,
    clip_id: str,
    clip_dir_name: str,
    content_hash: str,
    bag_oss_key: str | None,
    run_id: str,
    bag_stem: str,
    parse_result: dict[str, Any],
) -> None:
    metadata = parse_result["metadata"]
    now = _utc_now_iso()
    partition = f"ds={ds}"

    dim_table_name = _table_name(table_prefix, "dim_clip")
    created_at = _fetch_dim_clip_created_at(client, dim_table_name, clip_id) or now
    _upsert_dim_clip(
        client,
        dim_table_name,
        [
            clip_id,
            clip_dir_name,
            content_hash,
            run_id,
            created_at,
            now,
            bag_oss_key or None,
        ],
    )

    run_table_name = _table_name(table_prefix, "pipeline_run")
    purge_clip_run_rows(
        client,
        table_name=run_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns="run_id, clip_id, status, started_at, updated_at, completed_at",
    )
    run_table = client.get_table(run_table_name)
    with run_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write([[run_id, clip_id, "completed", now, now, now]])

    step_table_name = _table_name(table_prefix, "pipeline_step")
    purge_pipeline_step_run(
        client,
        table_name=step_table_name,
        ds=ds,
        run_id=run_id,
        step_id="job1_parse",
    )
    step_table = client.get_table(step_table_name)
    with step_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write([[run_id, "job1_parse", "completed", now, now, None]])

    timeline_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            item["topic"],
            item["msgtype"],
            item["modality"],
            int(item["timestamp_ns"]),
            int(item["sequence_idx"]),
        ]
        for item in parse_result["timeline_messages"]
    ]
    timeline_table_name = _table_name(table_prefix, "fact_message_timeline")
    purge_clip_run_rows(
        client,
        table_name=timeline_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, topic, msgtype, modality, "
            "timestamp_ns, sequence_idx"
        ),
    )
    if timeline_rows:
        table = client.get_table(timeline_table_name)
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(timeline_rows)

    frame_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            item["camera"],
            int(item["frame_idx"]),
            int(item["timestamp_ns"]),
            item["topic"],
            item["image_path"],
        ]
        for item in parse_result["frames"]
    ]
    frame_table_name = _table_name(table_prefix, "fact_frame")
    purge_clip_run_rows(
        client,
        table_name=frame_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, camera, frame_idx, "
            "timestamp_ns, topic, image_path"
        ),
    )
    if frame_rows:
        table = client.get_table(frame_table_name)
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(frame_rows)

    audio_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            int(item["chunk_idx"]),
            int(item["timestamp_ns"]),
            int(item["byte_offset"]),
            int(item["byte_length"]),
            int(item["sample_count"]),
            int(item["duration_ns"]),
            int(item["pcm_bytes"]),
        ]
        for item in parse_result["audio_chunks"]
    ]
    audio_table_name = _table_name(table_prefix, "fact_audio_chunk")
    purge_clip_run_rows(
        client,
        table_name=audio_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, chunk_idx, timestamp_ns, byte_offset, "
            "byte_length, sample_count, duration_ns, pcm_bytes"
        ),
    )
    if audio_rows:
        table = client.get_table(audio_table_name)
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(audio_rows)

    event_rows = [
        [
            clip_id,
            run_id,
            bag_stem,
            int(item["timestamp_ns"]),
            item["event_data"],
        ]
        for item in parse_result["events"]
    ]
    event_table_name = _table_name(table_prefix, "fact_event")
    purge_clip_run_rows(
        client,
        table_name=event_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns="clip_id, run_id, bag_stem, timestamp_ns, event_data",
    )
    if event_rows:
        table = client.get_table(event_table_name)
        with table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(event_rows)

    summary_table_name = _table_name(table_prefix, "clip_parse_summary")
    purge_clip_run_rows(
        client,
        table_name=summary_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, bag_stem, bag_file, duration_ns, duration_sec, "
            "start_time_ns, end_time_ns, message_count, topics_json, parsed_at"
        ),
    )
    summary_table = client.get_table(summary_table_name)
    with summary_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write(
            [
                [
                    clip_id,
                    run_id,
                    bag_stem,
                    str(metadata["bag_file"]),
                    int(metadata["duration_ns"]),
                    float(metadata["duration_sec"]),
                    int(metadata["start_time_ns"]),
                    int(metadata["end_time_ns"]),
                    int(metadata["message_count"]),
                    json.dumps(metadata.get("topics", {}), ensure_ascii=False),
                    now,
                ]
            ]
        )


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    pipeline_ctx = resolve_pipeline_context(
        get_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job1_mc_write"):
        return
    clip_id = pipeline_ctx["clip_id"]
    run_id = pipeline_ctx["run_id"]
    ds = _resolve_ds()

    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    table_prefix = get_arg("table_prefix", "aig_rosbag__")
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/")

    clip_prefix = _clip_prefix(prefix_template, clip_id)
    payload_key = f"{clip_prefix}/runs/{run_id}/parsed/job1_mc_payload.json"
    oss_endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    print(f"Job1 MC write: reading oss://{oss_bucket}/{payload_key} via {oss_endpoint}")
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
            f"Job1 payload not found: oss://{oss_bucket}/{payload_key} (run job1_parse first)"
        )

    parse_result = payload["parse_result"]
    write_job1_to_mc(
        o,  # type: ignore[name-defined]
        table_prefix=table_prefix,
        ds=ds,
        clip_id=str(payload.get("clip_id", clip_id)),
        clip_dir_name=str(payload["clip_dir_name"]),
        content_hash=str(payload["content_hash"]),
        bag_oss_key=str(payload.get("bag_oss_key") or "") or None,
        run_id=str(payload.get("run_id", run_id)),
        bag_stem=str(payload["bag_stem"]),
        parse_result=parse_result,
    )
    print(
        f"MC write done: clip_id={clip_id} run_id={run_id} ds={ds} "
        f"frames={len(parse_result['frames'])} "
        f"audio_chunks={len(parse_result['audio_chunks'])}"
    )


main()
