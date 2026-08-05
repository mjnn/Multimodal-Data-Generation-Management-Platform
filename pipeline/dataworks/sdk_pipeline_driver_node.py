# =============================================================================
# DataWorks PyODPS3: SDK single-driver skeleton (discover + echo apply_chunk)
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
    configure_dpe_engine,
    get_dw_arg,
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
    """Return an echo-only placeholder; production discovery must hash bag bytes."""
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

    # Skeleton-only list discovery. These pending IDs are safe only because Task 3
    # runs an echo UDF; production execution must hash bag bytes before SDK stages.
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


def _build_echo_chunk_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    def _echo_chunk(df: pd.DataFrame) -> pd.DataFrame:
        out: list[dict[str, Any]] = []
        for _, row in df.iterrows():
            run_relpath = str(row["run_relpath"])
            out.append(
                {
                    "clip_id": str(row["clip_id"]),
                    "run_id": str(row["run_id"]),
                    "bag_oss_key": str(row["bag_oss_key"]),
                    "ok": True,
                    "error": "",
                    "stages_done": "echo",
                    "run_relpath": run_relpath,
                    "labels_relpath": f"{run_relpath}/labels.jsonl",
                    "embeddings_relpath": f"{run_relpath}/fusion_embeddings.jsonl",
                    "videos_relpath": f"{run_relpath}/clip_videos.jsonl",
                    "preview_ok": False,
                }
            )
        return pd.DataFrame(out)

    return wrap_dpe_udf(
        _echo_chunk,
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
            "no bags discovered; provide bag_oss_key+clip_id+run_id or echo-only bag_oss_keys"
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

    apply_dpe_runtime_settings(dpe_image)
    configure_dpe_engine()

    import maxframe.dataframe as md
    from maxframe.session import new_session

    input_df = md.DataFrame(pd.DataFrame(job_rows))
    echo_udf = _build_echo_chunk_udf(
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_internal_url(
            cloud_region,
            oss_bucket,
            get_dw_arg("oss_mount_prefix", "") or "",
        ),
        mount_path=mount_path,
        storage_options_dict=storage_options(get_dw_arg("oss_ram_role_arn"), account),
    )
    session = new_session(o)  # type: ignore[name-defined]
    try:
        print(f"Logview: {session.get_logview_address()}")
        result = (
            input_df.mf.apply_chunk(
                echo_udf,
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
