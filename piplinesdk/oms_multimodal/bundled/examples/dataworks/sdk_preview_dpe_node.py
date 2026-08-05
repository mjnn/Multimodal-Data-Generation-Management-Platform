# =============================================================================
# DataWorks PyODPS3：sdk_preview（DPE UDF × materialize_preview，支持 batch items[]）
# 前置：sdk_extract_dpe 已写 _sdk_work/
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


def _build_sdk_preview_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    def _sdk_preview_row(row: pd.Series) -> dict[str, Any]:
        from oms_multimodal import OmsMultimodalClient, materialize_preview

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
            preview_dir = materialize_preview(ctx)
        finally:
            client.close()
        mp4_count = len(list(preview_dir.glob("clip_preview_*.mp4")))
        return {
            "clip_id": str(row["clip_id"]),
            "run_id": str(row["run_id"]),
            "mp4_count": mp4_count,
            "preview_relpath": f"{row['run_relpath']}/preview",
        }

    return wrap_dpe_udf(
        _sdk_preview_row,
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
    if exit_if_pipeline_idle(batch_ctx, node_name="sdk_preview"):
        return

    job_rows = work_items_to_job_rows(batch_ctx.get("items") or [])

    oss_bucket = require_dw_arg("oss_bucket")
    cloud_region = get_dw_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    role_arn = get_dw_arg("oss_ram_role_arn")
    mount_path = get_dw_arg("dpe_mount_path", "/mnt/oss") or "/mnt/oss"
    dpe_cpu = get_dw_int_arg("dpe_cpu", 2)
    dpe_memory = get_dw_int_arg("dpe_memory_gb", 8)
    dpe_image = get_dw_arg("dpe_image", "rosbag_sdk_dpe")
    dpe_parallel = get_dw_int_arg("dpe_parallel", min(8, len(job_rows)))

    oss_mount_url = oss_internal_url(cloud_region, oss_bucket, get_dw_arg("oss_mount_prefix", "") or "")
    apply_dpe_runtime_settings(dpe_image)
    configure_dpe_engine()
    print(f"sdk_preview DPE batch_size={len(job_rows)} parallel={min(dpe_parallel, len(job_rows))}")

    input_df, parallel = make_batch_input_df(job_rows, dpe_parallel)
    preview_udf = _build_sdk_preview_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options(role_arn, account),
    )
    result = run_dpe_batch_apply(
        o,  # type: ignore[name-defined]
        input_df,
        preview_udf,
        {
            "clip_id": "string",
            "run_id": "string",
            "mp4_count": "int64",
            "preview_relpath": "string",
        },
    )
    print_batch_summary("preview", result, parallel=parallel)


if __name__ == "__main__":
    main()
