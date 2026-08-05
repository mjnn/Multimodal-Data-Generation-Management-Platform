# =============================================================================
# DataWorks PyODPS3：sdk_extract（DPE UDF × SDK extract_clips，支持 batch items[]）
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from pipeline_dispatch import exit_if_pipeline_idle, resolve_pipeline_batch_context
from sdk_dpe_common import (
    apply_dpe_runtime_settings,
    configure_dpe_engine,
    get_dw_arg,
    get_dw_float_arg,
    get_dw_int_arg,
    make_batch_input_df,
    oss_internal_url,
    print_batch_summary,
    require_dw_arg,
    run_dpe_batch_apply,
    storage_options,
    work_items_to_job_rows,
    wrap_dpe_udf,
)


def _build_sdk_extract_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
    clip_min_sec: float,
    clip_max_sec: float,
    sample_fps: float,
):
    def _sdk_extract_row(row: pd.Series) -> dict[str, Any]:
        from oms_multimodal import ClipConfig, OmsMultimodalClient, extract_clips

        bag_path = Path(mount_path) / str(row["bag_oss_key"])
        if not bag_path.is_file():
            raise FileNotFoundError(f"bag not found on mount: {bag_path}")

        run_out = Path(mount_path) / str(row["run_relpath"])
        run_out.mkdir(parents=True, exist_ok=True)
        client = OmsMultimodalClient(work_dir=run_out / "_sdk_work", load_dotenv=False)
        ctx = client.make_run_context(
            run_out,
            media_mode="local",
            clip_id=str(row["clip_id"]),
            run_id=str(row["run_id"]),
        )
        try:
            result = extract_clips(
                ctx,
                bag_path,
                client=client,
                clip_config=ClipConfig(
                    min_sec=clip_min_sec,
                    max_sec=clip_max_sec,
                    sample_fps=sample_fps,
                ),
            )
        finally:
            client.close()

        return {
            "clip_id": str(row["clip_id"]),
            "run_id": str(row["run_id"]),
            "clip_rows": int(result.clip_rows),
            "video_rows": int(result.video_rows),
            "clips_index_relpath": f"{row['run_relpath']}/clips_index.jsonl",
            "videos_relpath": f"{row['run_relpath']}/clip_videos.jsonl",
            "bag_oss_key": str(row["bag_oss_key"]),
        }

    return wrap_dpe_udf(
        _sdk_extract_row,
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def main() -> None:
    account = o.account  # type: ignore[name-defined]
    batch_ctx = resolve_pipeline_batch_context(
        get_dw_arg,
        odps_client=o,  # type: ignore[name-defined]
        oss_account=account,
        oss_bucket=get_dw_arg("oss_bucket"),
    )
    if exit_if_pipeline_idle(batch_ctx, node_name="sdk_extract"):
        return

    work_items = batch_ctx.get("items") or []
    job_rows = work_items_to_job_rows(work_items)
    for row in job_rows:
        if not row.get("bag_oss_key"):
            raise ValueError(f"bag_oss_key missing for clip_id={row.get('clip_id')}")

    oss_bucket = require_dw_arg("oss_bucket")
    cloud_region = get_dw_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    role_arn = get_dw_arg("oss_ram_role_arn")
    mount_path = get_dw_arg("dpe_mount_path", "/mnt/oss") or "/mnt/oss"
    dpe_cpu = get_dw_int_arg("dpe_cpu", 4)
    dpe_memory = get_dw_int_arg("dpe_memory_gb", 16)
    dpe_image = get_dw_arg("dpe_image", "rosbag_sdk_dpe")
    dpe_parallel = get_dw_int_arg("dpe_parallel", min(8, len(job_rows)))
    clip_min_sec = get_dw_float_arg("clip_min_sec", 15.0)
    clip_max_sec = get_dw_float_arg("clip_max_sec", 20.0)
    sample_fps = get_dw_float_arg("sample_fps", 1.0)

    oss_mount_url = oss_internal_url(cloud_region, oss_bucket, get_dw_arg("oss_mount_prefix", "") or "")
    apply_dpe_runtime_settings(dpe_image)
    configure_dpe_engine()
    print(
        f"sdk_extract DPE batch_size={len(job_rows)} parallel={min(dpe_parallel, len(job_rows))} "
        f"mode={batch_ctx.get('mode')}"
    )

    input_df, parallel = make_batch_input_df(job_rows, dpe_parallel)
    extract_udf = _build_sdk_extract_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options(role_arn, account),
        clip_min_sec=clip_min_sec,
        clip_max_sec=clip_max_sec,
        sample_fps=sample_fps,
    )
    result = run_dpe_batch_apply(
        o,  # type: ignore[name-defined]
        input_df,
        extract_udf,
        {
            "clip_id": "string",
            "run_id": "string",
            "clip_rows": "int64",
            "video_rows": "int64",
            "clips_index_relpath": "string",
            "videos_relpath": "string",
            "bag_oss_key": "string",
        },
    )
    print_batch_summary("extract", result, parallel=parallel)


if __name__ == "__main__":
    main()
