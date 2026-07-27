# =============================================================================
# DataWorks PyODPS 3 节点：Job2-写MC（MaxFrame + DPE）
# 粘贴整文件到 PyODPS3 节点；依赖 maxframe、pyodps、pandas。
# DPE pickle：禁止 @dataclass / 自定义 class（UDF 仅用 dict/list）；见 scripts/check_dpe_nodes.py
#
# 读 OSS：
#   clips/{clip_id}/runs/{run_id}/job2/job2_sample_payload.json
#   clips/{clip_id}/runs/{run_id}/job2/job2_asr_payload.json
# 合并写 OSS：.../job2/job2_mc_payload.json
# 写 MC：fact_sample_policy、fact_audio_segment、pipeline_step（job2_sample/job2_asr）
# 幂等：同 ds 分区下先 INSERT OVERWRITE 去掉本 (clip_id, run_id) 旧行再 append
# DataWorks 粘贴：python scripts/bundle_mc_write_node.py dataworks/job2_mc_write_node.py
#
# 依赖：Job2_sample + Job2_asr 均完成（可与 Job3 并行，Job2_mc_write 等两路产物）
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
#   run_id=<与 Job2_sample / Job2_asr 相同>
# =============================================================================

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import maxframe.dataframe as md
import pandas as pd
from maxframe.config import options as mf_options
from maxframe.session import new_session
from maxframe.udf import with_fs_mount, with_running_options

from mc_write_idempotent import purge_clip_run_rows, purge_pipeline_steps_run
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


def _apply_dpe_runtime_settings(dpe_image: str | None) -> None:
    sql_settings = dict(mf_options.sql.settings or {})
    sql_settings["odps.sql.python.version"] = "cp311"
    if dpe_image:
        sql_settings["odps.session.image"] = dpe_image
    mf_options.sql.settings = sql_settings


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


def _oss_internal_url(region: str, bucket: str, prefix: str) -> str:
    region_id = region.replace("_", "-")
    normalized = prefix.strip("/")
    if not normalized:
        return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/"
    return f"oss://oss-{region_id}-internal.aliyuncs.com/{bucket}/{normalized}/"


def _storage_options(role_arn: str | None, account: Any) -> dict[str, str]:
    if role_arn:
        return {"role_arn": role_arn}
    return {
        "oss_access_key_id": account.access_id,
        "oss_access_key_secret": account.secret_access_key,
    }


def _clip_prefix(template: str, clip_id: str) -> str:
    return template.format(clip_id=clip_id).strip("/")


def merge_job2_payloads(
    sample_payload: dict[str, Any],
    asr_payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "clip_id": str(sample_payload.get("clip_id") or asr_payload.get("clip_id") or ""),
        "run_id": str(sample_payload.get("run_id") or asr_payload.get("run_id") or ""),
        "bag_stem": str(sample_payload.get("bag_stem") or asr_payload.get("bag_stem") or ""),
        "sample_policy_name": str(sample_payload.get("sample_policy_name") or ""),
        "sample_policy_params": sample_payload.get("sample_policy_params") or {},
        "sample_sync_mode": bool(sample_payload.get("sample_sync_mode")),
        "sampled_frames": sample_payload.get("sampled_frames") or [],
        "sample_groups": sample_payload.get("sample_groups") or [],
        "asr_model": str(asr_payload.get("asr_model") or "none"),
        "asr_model_version": str(asr_payload.get("asr_model_version") or "none"),
        "language": str(asr_payload.get("language") or "zh-CN"),
        "audio_segments": asr_payload.get("audio_segments") or [],
        "processed_at": _utc_now_iso(),
    }


def write_job2_to_mc(
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

    policy_table_name = _table_name(table_prefix, "fact_sample_policy")
    purge_clip_run_rows(
        client,
        table_name=policy_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns="clip_id, run_id, policy_name, policy_params, created_at",
    )
    policy_table = client.get_table(policy_table_name)
    with policy_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write(
            [
                [
                    clip_id,
                    run_id,
                    str(payload["sample_policy_name"]),
                    json.dumps(payload.get("sample_policy_params") or {}, ensure_ascii=False),
                    now,
                ]
            ]
        )

    segment_rows = [
        [
            clip_id,
            run_id,
            int(item["segment_id"]),
            int(item["start_ns"]),
            int(item["end_ns"]),
            str(item.get("asr_text") or ""),
            float(item.get("confidence") or 0.0),
            str(item.get("model_version") or "none"),
            int(item["source_chunk_from"]),
            int(item["source_chunk_to"]),
        ]
        for item in payload.get("audio_segments") or []
    ]
    segment_table_name = _table_name(table_prefix, "fact_audio_segment")
    purge_clip_run_rows(
        client,
        table_name=segment_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, segment_id, start_ns, end_ns, asr_text, confidence, "
            "model_version, source_chunk_from, source_chunk_to"
        ),
    )
    if segment_rows:
        segment_table = client.get_table(segment_table_name)
        with segment_table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(segment_rows)

    sync_group_rows = [
        [
            clip_id,
            run_id,
            str(item.get("sync_group_id") or ""),
            int(item.get("anchor_timestamp_ns") or 0),
            str(payload.get("sample_policy_name") or ""),
            int((payload.get("sample_policy_params") or {}).get("align_window_ms") or 0),
            json.dumps(
                [
                    f"{frame.get('camera')}:{frame.get('frame_idx')}"
                    for frame in (item.get("frames") or [])
                ],
                ensure_ascii=False,
            ),
            now,
        ]
        for item in payload.get("sample_groups") or []
        if str(item.get("sync_group_id") or "").strip()
    ]
    sync_table_name = _table_name(table_prefix, "fact_sample_sync_group")
    purge_clip_run_rows(
        client,
        table_name=sync_table_name,
        ds=ds,
        clip_id=clip_id,
        run_id=run_id,
        columns=(
            "clip_id, run_id, sync_group_id, anchor_timestamp_ns, sample_policy, "
            "align_window_ms, frame_ids_json, created_at"
        ),
    )
    if sync_group_rows:
        sync_table = client.get_table(sync_table_name)
        with sync_table.open_writer(partition=partition, create_partition=True) as writer:
            writer.write(sync_group_rows)

    step_table_name = _table_name(table_prefix, "pipeline_step")
    purge_pipeline_steps_run(
        client,
        table_name=step_table_name,
        ds=ds,
        run_id=run_id,
        step_ids=("job2_sample", "job2_asr"),
    )
    step_table = client.get_table(step_table_name)
    with step_table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write(
            [
                [run_id, "job2_sample", "completed", now, now, None],
                [run_id, "job2_asr", "completed", now, now, None],
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
    if exit_if_pipeline_idle(pipeline_ctx, node_name="job2_mc_write"):
        return
    clip_id = pipeline_ctx["clip_id"]
    run_id = pipeline_ctx["run_id"]
    ds = _resolve_ds()

    oss_bucket = require_arg("oss_bucket")
    cloud_region = get_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    table_prefix = get_arg("table_prefix", "aig_rosbag__")
    prefix_template = get_arg("oss_prefix_template", "clips/{clip_id}/")
    role_arn = get_arg("oss_ram_role_arn")
    oss_mount_prefix = get_arg("oss_mount_prefix", "") or ""
    mount_path = get_arg("dpe_mount_path", "/mnt/oss")
    dpe_cpu = get_int_arg("dpe_cpu", 1)
    dpe_memory = get_int_arg("dpe_memory_gb", 4)

    clip_prefix = _clip_prefix(prefix_template, clip_id)
    job2_relpath = f"{clip_prefix}/runs/{run_id}/job2"
    sample_payload_relpath = f"{job2_relpath}/job2_sample_payload.json"
    asr_payload_relpath = f"{job2_relpath}/job2_asr_payload.json"
    merged_payload_relpath = f"{job2_relpath}/job2_mc_payload.json"

    mf_options.dag.settings = {
        "engine_order": ["DPE"],
        "unavailable_engines": ["MCSQL", "SPE"],
    }
    mf_options.local_execution.enabled = False

    dpe_image = get_arg("dpe_image")
    _apply_dpe_runtime_settings(dpe_image)
    print(f"Job2 MC write DPE image: {dpe_image}")

    session = new_session(o)  # type: ignore[name-defined]
    input_df = md.DataFrame(
        pd.DataFrame(
            [
                {
                    "sample_payload_relpath": sample_payload_relpath,
                    "asr_payload_relpath": asr_payload_relpath,
                    "merged_payload_relpath": merged_payload_relpath,
                }
            ]
        )
    )
    oss_mount_url = _oss_internal_url(cloud_region, oss_bucket, oss_mount_prefix)
    storage_options = _storage_options(role_arn, account)

    @with_running_options(engine="dpe", cpu=dpe_cpu, memory=dpe_memory)
    @with_fs_mount(oss_mount_url, mount_path, storage_options=storage_options)
    def _job2_merge_payload_row(row):
        sample_path = Path(mount_path) / row["sample_payload_relpath"]
        asr_path = Path(mount_path) / row["asr_payload_relpath"]
        if not sample_path.is_file():
            raise FileNotFoundError(
                f"Job2 sample payload not found: {sample_path} (run job2_sample_node first)"
            )
        if not asr_path.is_file():
            raise FileNotFoundError(
                f"Job2 ASR payload not found: {asr_path} (run job2_asr_node first)"
            )
        sample_payload = json.loads(sample_path.read_text(encoding="utf-8"))
        asr_payload = json.loads(asr_path.read_text(encoding="utf-8"))
        merged = merge_job2_payloads(sample_payload, asr_payload)
        merged_path = Path(mount_path) / row["merged_payload_relpath"]
        merged_path.parent.mkdir(parents=True, exist_ok=True)
        merged_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": "1"}

    try:
        print(f"Logview: {session.get_logview_address()}")
        result_df = input_df.apply(
            _job2_merge_payload_row,
            axis=1,
            output_type="dataframe",
            result_type="expand",
            dtypes={"ok": "string"},
            skip_infer=True,
        )
        row = result_df.execute().fetch().iloc[0]
        if str(row.get("ok", "")).strip() != "1":
            raise RuntimeError("Job2 merge payload DPE step failed")
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()

    oss_endpoint = resolve_oss_http_endpoint(cloud_region, get_arg=get_arg)
    print(f"Job2 MC write: reading oss://{oss_bucket}/{merged_payload_relpath} via {oss_endpoint}")
    payload = read_oss_json_object(
        bucket_name=oss_bucket,
        object_key=merged_payload_relpath,
        endpoint=oss_endpoint,
        account=account,
        region=cloud_region,
        get_arg=get_arg,
    )
    if payload is None:
        raise FileNotFoundError(
            f"Job2 merged payload not found: oss://{oss_bucket}/{merged_payload_relpath}"
        )

    resolved_clip_id = str(payload.get("clip_id", clip_id))
    resolved_run_id = str(payload.get("run_id", run_id))
    write_job2_to_mc(
        o,  # type: ignore[name-defined]
        table_prefix=table_prefix,
        ds=ds,
        clip_id=resolved_clip_id,
        run_id=resolved_run_id,
        payload=payload,
    )
    print(
        f"Job2 MC write done: clip_id={resolved_clip_id} run_id={resolved_run_id} ds={ds} "
        f"sampled_frames={len(payload.get('sampled_frames') or [])} "
        f"sync_groups={len(payload.get('sample_groups') or [])} "
        f"audio_segments={len(payload.get('audio_segments') or [])} "
        f"policy={payload.get('sample_policy_name')} "
        f"merged_payload={merged_payload_relpath}"
    )


main()
