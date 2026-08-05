# =============================================================================
# DataWorks PyODPS3: SDK single-driver (discover + pipeline apply_chunk)
# =============================================================================

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import PurePosixPath
import re
from typing import Any

import pandas as pd

from sdk_dpe_common import (
    apply_dpe_runtime_settings,
    collect_sdk_env_for_dpe,
    configure_dpe_engine,
    get_dw_arg,
    get_dw_float_arg,
    oss_internal_url,
    storage_options,
    wrap_dpe_udf,
)
from sdk_pipeline_driver_lib import (
    batch_summary,
    build_job_rows,
    chunk_output_dtypes,
    make_run_id,
    split_stages,
)


def _pending_clip_id(bag_oss_key: str) -> str:
    """Return a placeholder; production discovery must replace it with a content hash."""
    stem = PurePosixPath(bag_oss_key).stem
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", stem).strip("._-") or "bag"
    return f"sha256:pending_{safe_name.lower()}"


def _bags_from_args() -> list[dict[str, str]]:
    bag_oss_key = get_dw_arg("bag_oss_key")
    clip_id = get_dw_arg("clip_id")
    run_id = get_dw_arg("run_id")
    explicit_values = (bag_oss_key, clip_id, run_id)
    if any(explicit_values):
        if not all(explicit_values):
            raise ValueError("bag_oss_key, clip_id, and run_id must be provided together")
        return [
            {
                "bag_oss_key": str(bag_oss_key),
                "clip_id": str(clip_id),
                "run_id": str(run_id),
            }
        ]

    # Skeleton-only list discovery. Use the explicit triplet for real execution
    # until Driver discovery hashes bag bytes in a later task.
    raw_keys = get_dw_arg("bag_oss_keys", "") or ""
    keys = [
        key.strip()
        for key in re.split(r"[\r\n,]+", raw_keys)
        if key.strip().lower().endswith(".bag")
    ]
    max_bags_raw = get_dw_arg("max_bags")
    if max_bags_raw is not None:
        keys = keys[: max(0, int(max_bags_raw))]
    return [
        {
            "bag_oss_key": key,
            "clip_id": _pending_clip_id(key),
            "run_id": make_run_id(),
        }
        for key in keys
    ]


def _build_pipeline_chunk_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
    sdk_env: dict[str, str],
    udf_stages_frozen: frozenset[str],
    clip_min_sec: float,
    clip_max_sec: float,
    sample_fps: float,
    model_backend: str,
    cleanup_work: bool,
):
    def _pipeline_chunk(df: pd.DataFrame) -> pd.DataFrame:
        import os
        from pathlib import Path

        from oms_multimodal import ClipConfig, OmsMultimodalClient, run_stages

        for key, value in sdk_env.items():
            if value:
                os.environ[key] = str(value)

        rows_out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            clip_id = str(row["clip_id"])
            run_id = str(row["run_id"])
            bag_oss_key = str(row["bag_oss_key"])
            run_relpath = str(row["run_relpath"])
            ds = str(row["ds"])
            try:
                bag_path = Path(mount_path) / bag_oss_key
                run_out = Path(mount_path) / run_relpath
                run_out.mkdir(parents=True, exist_ok=True)
                client = OmsMultimodalClient(
                    work_dir=run_out / "_sdk_work",
                    load_dotenv=False,
                )
                try:
                    ctx = client.make_run_context(
                        run_out,
                        media_mode="local",
                        clip_id=clip_id,
                        run_id=run_id,
                    )
                    result = run_stages(
                        ctx,
                        bag_path,
                        client,
                        stages=udf_stages_frozen,
                        clip_config=ClipConfig(
                            min_sec=clip_min_sec,
                            max_sec=clip_max_sec,
                            sample_fps=sample_fps,
                        ),
                        bag_oss_key=bag_oss_key,
                        ds=ds,
                        model_backend=model_backend,
                        cleanup_work=cleanup_work,
                    )
                finally:
                    client.close()

                # Any capability error blocks Driver-side mc_write for this row.
                ok = len(result.errors) == 0
                error = str(result.errors[0])[:500] if result.errors else ""
                rows_out.append(
                    {
                        "clip_id": clip_id,
                        "run_id": run_id,
                        "bag_oss_key": bag_oss_key,
                        "ok": ok,
                        "error": error,
                        "stages_done": ",".join(result.stages_done),
                        "run_relpath": run_relpath,
                        "labels_relpath": f"{run_relpath}/labels.jsonl",
                        "embeddings_relpath": f"{run_relpath}/fusion_embeddings.jsonl",
                        "videos_relpath": f"{run_relpath}/clip_videos.jsonl",
                        "preview_ok": bool(result.preview_ok),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                rows_out.append(
                    {
                        "clip_id": clip_id,
                        "run_id": run_id,
                        "bag_oss_key": bag_oss_key,
                        "ok": False,
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                        "stages_done": "",
                        "run_relpath": run_relpath,
                        "labels_relpath": f"{run_relpath}/labels.jsonl",
                        "embeddings_relpath": f"{run_relpath}/fusion_embeddings.jsonl",
                        "videos_relpath": f"{run_relpath}/clip_videos.jsonl",
                        "preview_ok": False,
                    }
                )
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _pipeline_chunk,
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def main() -> None:
    stages_raw = get_dw_arg("stages")
    driver_stages, udf_stages = split_stages(stages_raw)
    ds = get_dw_arg("ds") or datetime.now(timezone.utc).strftime("%Y%m%d")
    job_rows = build_job_rows(_bags_from_args(), ds=ds)
    if not job_rows:
        raise ValueError(
            "no bags discovered; provide bag_oss_key+clip_id+run_id or bag_oss_keys"
        )

    print(
        "DISCOVERED_ROWS_JSON="
        + json.dumps(
            {"driver_stages": sorted(driver_stages), "items": job_rows},
            ensure_ascii=False,
        )
    )
    if not udf_stages:
        print("No UDF stages selected; skipping apply_chunk")
        return

    account = o.account  # type: ignore[name-defined]
    oss_bucket = get_dw_arg("oss_bucket")
    if not oss_bucket:
        raise ValueError("Missing required parameter: oss_bucket")
    cloud_region = get_dw_arg("cloud_region", "cn_shanghai") or "cn_shanghai"
    dpe_image = get_dw_arg("dpe_image")
    mount_path = get_dw_arg("mount_path", get_dw_arg("dpe_mount_path", "/mnt/oss")) or "/mnt/oss"
    batch_rows = int(get_dw_arg("batch_rows", "1") or "1")
    if batch_rows < 1:
        raise ValueError("batch_rows must be >= 1")
    dpe_cpu = int(get_dw_arg("dpe_cpu", "4") or "4")
    dpe_memory = int(get_dw_arg("dpe_memory_gb", "16") or "16")
    clip_min_sec = get_dw_float_arg("clip_min_sec", 15.0)
    clip_max_sec = get_dw_float_arg("clip_max_sec", 20.0)
    sample_fps = get_dw_float_arg("sample_fps", 1.0)
    cleanup_work = (get_dw_arg("cleanup_work", "false") or "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    sdk_env = collect_sdk_env_for_dpe(account)
    # Workflow secret args override account-derived values; project/endpoint
    # fall back to the current Driver ODPS entry when available.
    odps_env_values = {
        "ODPS_ACCESS_ID": get_dw_arg("odps_access_id"),
        "ODPS_ACCESS_KEY": get_dw_arg("odps_access_key"),
        "ODPS_PROJECT": get_dw_arg("odps_project") or getattr(o, "project", ""),  # type: ignore[name-defined]
        "ODPS_ENDPOINT": get_dw_arg("odps_endpoint") or getattr(o, "endpoint", ""),  # type: ignore[name-defined]
    }
    for env_name, value in odps_env_values.items():
        if value:
            sdk_env[env_name] = str(value)
    model_backend = sdk_env["MODEL_BACKEND"]

    apply_dpe_runtime_settings(dpe_image)
    configure_dpe_engine()

    import maxframe.dataframe as md
    from maxframe.session import new_session

    input_df = md.DataFrame(pd.DataFrame(job_rows))
    pipeline_udf = _build_pipeline_chunk_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_internal_url(
            cloud_region,
            oss_bucket,
            get_dw_arg("oss_mount_prefix", "") or "",
        ),
        mount_path=mount_path,
        storage_options_dict=storage_options(get_dw_arg("oss_ram_role_arn"), account),
        sdk_env=sdk_env,
        udf_stages_frozen=frozenset(udf_stages),
        clip_min_sec=clip_min_sec,
        clip_max_sec=clip_max_sec,
        sample_fps=sample_fps,
        model_backend=model_backend,
        cleanup_work=cleanup_work,
    )
    session = new_session(o)  # type: ignore[name-defined]
    try:
        print(f"Logview: {session.get_logview_address()}")
        result = (
            input_df.mf.apply_chunk(
                pipeline_udf,
                batch_rows=batch_rows,
                output_type="dataframe",
                dtypes=chunk_output_dtypes(),
                skip_infer=True,
            )
            .execute()
            .fetch()
        )
        result_rows = [row.to_dict() for _, row in result.iterrows()]
        print(
            "BATCH_SUMMARY_JSON="
            + json.dumps(batch_summary(result_rows), ensure_ascii=False, default=str)
        )
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


if __name__ == "__main__":
    main()
