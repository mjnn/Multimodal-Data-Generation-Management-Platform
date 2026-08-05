# =============================================================================
# DataWorks PyODPS3：sdk_asr（DPE UDF × transcribe_clips，支持 batch items[]）
# 前置：sdk_extract_dpe 已写 clips_index.jsonl
# 粘贴：与 pipeline_dispatch.py、sdk_dpe_common.py 一并 bundle 或同目录
# =============================================================================

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from pipeline_dispatch import exit_if_pipeline_idle, resolve_pipeline_batch_context
from sdk_dpe_common import (
    apply_dpe_runtime_settings,
    collect_sdk_env_for_dpe,
    configure_dpe_engine,
    get_dw_int_arg,
    make_batch_input_df,
    oss_internal_url,
    print_batch_summary,
    require_dw_arg,
    run_dpe_batch_apply,
    storage_options,
    get_dw_arg,
    work_items_to_job_rows,
    wrap_dpe_udf,
)


def _build_sdk_asr_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
    sdk_env: dict[str, str],
    media_mode: str,
):
    def _sdk_asr_row(row: pd.Series) -> dict[str, Any]:
        import os

        for key, value in sdk_env.items():
            if value:
                os.environ.setdefault(key, str(value))

        from oms_multimodal import ClientConfig, McBackendConfig, OmsMultimodalClient, transcribe_clips

        backend = os.environ.get("MODEL_BACKEND", "api").strip().lower()
        mc_config = McBackendConfig.from_env(odps_entry=None) if backend == "mc" else None
        cfg = ClientConfig.from_env()
        cfg.model_backend = "mc" if backend == "mc" else "api"
        cfg.mc_config = mc_config

        run_out = Path(mount_path) / str(row["run_relpath"])
        run_out.mkdir(parents=True, exist_ok=True)
        client = OmsMultimodalClient(config=cfg, work_dir=run_out / "_sdk_work", load_dotenv=False)
        ctx = client.make_run_context(
            run_out,
            media_mode=media_mode if media_mode in {"local", "oss", "auto"} else "local",
            clip_id=str(row["clip_id"]),
            run_id=str(row["run_id"]),
        )
        try:
            result = transcribe_clips(ctx, client)
        finally:
            client.close()

        return {
            "clip_id": str(row["clip_id"]),
            "run_id": str(row["run_id"]),
            "row_count": int(result.row_count),
            "error_count": len(result.errors or []),
            "asr_relpath": f"{row['run_relpath']}/asr.jsonl",
        }

    return wrap_dpe_udf(
        _sdk_asr_row,
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
    if exit_if_pipeline_idle(batch_ctx, node_name="sdk_asr"):
        return

    work_items = batch_ctx.get("items") or []
    job_rows = work_items_to_job_rows(work_items)

    oss_bucket = require_dw_arg("oss_bucket")
    cloud_region = get_dw_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    role_arn = get_dw_arg("oss_ram_role_arn")
    mount_path = get_dw_arg("dpe_mount_path", "/mnt/oss") or "/mnt/oss"
    dpe_cpu = get_dw_int_arg("dpe_cpu", 2)
    dpe_memory = get_dw_int_arg("dpe_memory_gb", 8)
    dpe_image = get_dw_arg("dpe_image", "rosbag_sdk_dpe")
    dpe_parallel = get_dw_int_arg("dpe_parallel", min(8, len(job_rows)))
    media_mode = (get_dw_arg("media_mode") or "local").strip().lower()

    oss_mount_url = oss_internal_url(cloud_region, oss_bucket, get_dw_arg("oss_mount_prefix", "") or "")
    apply_dpe_runtime_settings(dpe_image)
    configure_dpe_engine()
    print(
        f"sdk_asr DPE batch_size={len(job_rows)} parallel={min(dpe_parallel, len(job_rows))} "
        f"media_mode={media_mode}"
    )

    input_df, parallel = make_batch_input_df(job_rows, dpe_parallel)
    sdk_env = collect_sdk_env_for_dpe(account)
    asr_udf = _build_sdk_asr_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options(role_arn, account),
        sdk_env=sdk_env,
        media_mode=media_mode,
    )
    result = run_dpe_batch_apply(
        o,  # type: ignore[name-defined]
        input_df,
        asr_udf,
        {
            "clip_id": "string",
            "run_id": "string",
            "row_count": "int64",
            "error_count": "int64",
            "asr_relpath": "string",
        },
    )
    print_batch_summary("transcribe", result, parallel=parallel)


if __name__ == "__main__":
    main()
