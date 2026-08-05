# =============================================================================
# DataWorks PyODPS3: SDK single-driver (discover + pipeline apply_chunk)
# Production discovery uses two apply_chunk passes in this one Driver node:
# (1) hash bag bytes on the OSS mount; (2) run selected SDK pipeline stages.
# =============================================================================

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

from pipeline_dispatch import (
    DEFAULT_DISPATCH_OSS_KEY,
    resolve_oss_http_endpoint,
    utc_now_iso,
    write_dispatch_to_oss,
)
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
from sdk_mc_ingest import ingest_sdk_run
from sdk_pipeline_driver_lib import (
    batch_summary,
    build_job_rows,
    chunk_output_dtypes,
    content_hash_to_clip_id,
    filter_already_completed,
    make_run_id,
    run_oss_prefix_from_relpath,
    split_stages,
    trim_discovered_bags,
)


def _explicit_bag_from_args() -> list[dict[str, str]] | None:
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
    return None


def _debug_bag_keys_from_args() -> list[str]:
    raw_keys = get_dw_arg("bag_oss_keys", "") or ""
    return [
        key.strip()
        for key in re.split(r"[\r\n,]+", raw_keys)
        if key.strip().lower().endswith(".bag")
    ]


def _list_bag_keys_from_oss(
    account: Any,
    *,
    oss_bucket: str,
    cloud_region: str,
) -> list[str]:
    from oss_v2_dw import iter_object_keys, make_oss_client

    client = make_oss_client(
        access_key_id=str(account.access_id),
        access_key_secret=str(account.secret_access_key),
        region=cloud_region,
        endpoint=get_dw_arg("oss_endpoint"),
    )
    return list(
        iter_object_keys(
            client,
            bucket=oss_bucket,
            prefix=get_dw_arg("scan_prefix", "rosbags/") or "rosbags/",
            suffix=".bag",
            max_count=int(get_dw_arg("max_scan", "1000") or "1000"),
        )
    )


def _hash_chunk_output_dtypes() -> dict[str, str]:
    return {
        "clip_id": "string",
        "bag_oss_key": "string",
        "content_hash": "string",
    }


def _build_hash_chunk_udf(
    *,
    dpe_cpu: int,
    dpe_memory: int,
    oss_mount_url: str,
    mount_path: str,
    storage_options_dict: dict[str, str],
):
    def _hash_chunk(df: pd.DataFrame) -> pd.DataFrame:
        from pathlib import Path
        import hashlib

        rows_out: list[dict[str, str]] = []
        for _, row in df.iterrows():
            bag_oss_key = str(row["bag_oss_key"])
            hasher = hashlib.sha256()
            with (Path(mount_path) / bag_oss_key).open("rb") as bag_file:
                while True:
                    block = bag_file.read(1024 * 1024)
                    if not block:
                        break
                    hasher.update(block)
            content_hash = hasher.hexdigest()
            rows_out.append(
                {
                    "clip_id": f"sha256:{content_hash}",
                    "bag_oss_key": bag_oss_key,
                    "content_hash": content_hash,
                }
            )
        return pd.DataFrame(rows_out)

    return wrap_dpe_udf(
        _hash_chunk,
        dpe_cpu=dpe_cpu,
        dpe_memory=dpe_memory,
        oss_mount_url=oss_mount_url,
        mount_path=mount_path,
        storage_options_dict=storage_options_dict,
    )


def _completed_clip_ids(
    client: Any,
    *,
    table_prefix: str,
    clip_ids: list[str],
) -> set[str]:
    """Find clips whose active SDK run is completed; failures are handled by caller."""
    completed: set[str] = set()
    for start in range(0, len(clip_ids), 50):
        batch = clip_ids[start : start + 50]
        quoted = ",".join("'" + cid.replace("'", "''") + "'" for cid in batch)
        sql = (
            f"SELECT d.clip_id FROM {table_prefix}dim_clip d "
            f"JOIN {table_prefix}pipeline_run r "
            "ON d.clip_id = r.clip_id AND d.active_run_id = r.run_id "
            f"WHERE d.clip_id IN ({quoted}) AND r.status = 'completed'"
        )
        with client.execute_sql(sql).open_reader() as reader:
            for record in reader:
                completed.add(str(record[0]))
    return completed


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
                    close = getattr(client, "close", None)
                    if callable(close):
                        close()

                # Any capability error blocks Driver-side mc_write for this row.
                ok = len(result.errors) == 0
                error = str(result.errors[0])[:500] if result.errors else ""
                rows_out.append(
                    {
                        "clip_id": clip_id,
                        "run_id": run_id,
                        "bag_oss_key": bag_oss_key,
                        "ds": ds,
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
                        "ds": ds,
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
    hash_batch_rows = int(get_dw_arg("hash_batch_rows", "32") or "32")
    if hash_batch_rows < 1:
        raise ValueError("hash_batch_rows must be >= 1")
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

    mount_url = oss_internal_url(
        cloud_region,
        oss_bucket,
        get_dw_arg("oss_mount_prefix", "") or "",
    )
    mount_storage = storage_options(get_dw_arg("oss_ram_role_arn"), account)
    session = new_session(o)  # type: ignore[name-defined]
    try:
        print(f"Logview: {session.get_logview_address()}")
        explicit_bags = _explicit_bag_from_args()
        if explicit_bags is not None:
            discovered_bags: list[dict[str, Any]] = explicit_bags
            print("DEBUG_OVERRIDE: using explicit clip_id/run_id/bag_oss_key")
        else:
            bag_keys = _debug_bag_keys_from_args()
            if not bag_keys:
                bag_keys = _list_bag_keys_from_oss(
                    account,
                    oss_bucket=oss_bucket,
                    cloud_region=cloud_region,
                )
            if not bag_keys:
                raise ValueError(
                    "no bags discovered from OSS; set scan_prefix or bag_oss_keys"
                )
            hash_input_df = md.DataFrame(
                pd.DataFrame([{"bag_oss_key": key} for key in bag_keys])
            )
            hash_udf = _build_hash_chunk_udf(
                dpe_cpu=dpe_cpu,
                dpe_memory=dpe_memory,
                oss_mount_url=mount_url,
                mount_path=mount_path,
                storage_options_dict=mount_storage,
            )
            hash_result = (
                hash_input_df.mf.apply_chunk(
                    hash_udf,
                    batch_rows=hash_batch_rows,
                    output_type="dataframe",
                    dtypes=_hash_chunk_output_dtypes(),
                    skip_infer=True,
                )
                .execute()
                .fetch()
            )
            discovered_bags = [
                {
                    "clip_id": content_hash_to_clip_id(str(row["content_hash"])),
                    "bag_oss_key": str(row["bag_oss_key"]),
                    "content_hash": str(row["content_hash"]),
                }
                for _, row in hash_result.iterrows()
            ]

        force_rerun = (get_dw_arg("force_rerun", "false") or "false").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        completed_clip_ids: set[str] = set()
        if not force_rerun:
            table_prefix = (
                get_dw_arg("sdk_table_prefix")
                or get_dw_arg("table_prefix")
                or "aig_sdk__"
            )
            try:
                completed_clip_ids = _completed_clip_ids(
                    o,  # type: ignore[name-defined]
                    table_prefix=table_prefix,
                    clip_ids=[str(bag["clip_id"]) for bag in discovered_bags],
                )
            except Exception as exc:  # noqa: BLE001
                # A first deployment may run before SDK tables exist. Discovery
                # remains usable and mc_write can create/populate them later.
                print(
                    "WARNING: completed-run lookup failed; continuing without skip: "
                    f"{type(exc).__name__}: {exc}"
                )
        runnable_bags = filter_already_completed(
            discovered_bags,
            completed_clip_ids=completed_clip_ids,
            force_rerun=force_rerun,
        )
        max_bags_raw = get_dw_arg("max_bags")
        runnable_bags = trim_discovered_bags(
            runnable_bags,
            max_bags=None if max_bags_raw is None else int(max_bags_raw),
        )
        for bag in runnable_bags:
            bag.setdefault("run_id", make_run_id())
        job_rows = build_job_rows(runnable_bags, ds=ds)
        print(
            "DISCOVERED_ROWS_JSON="
            + json.dumps(
                {
                    "driver_stages": sorted(driver_stages),
                    "hashed_count": len(discovered_bags),
                    "skipped_completed": len(discovered_bags) - len(
                        filter_already_completed(
                            discovered_bags,
                            completed_clip_ids=completed_clip_ids,
                            force_rerun=force_rerun,
                        )
                    ),
                    "items": job_rows,
                },
                ensure_ascii=False,
            )
        )
        if not job_rows:
            print("No runnable bags after completed-run skip/max_bags")
            return
        if not udf_stages:
            print("No UDF stages selected; skipping pipeline apply_chunk")
            return

        input_df = md.DataFrame(pd.DataFrame(job_rows))
        pipeline_udf = _build_pipeline_chunk_udf(
            dpe_cpu=dpe_cpu,
            dpe_memory=dpe_memory,
            oss_mount_url=mount_url,
            mount_path=mount_path,
            storage_options_dict=mount_storage,
            sdk_env=sdk_env,
            udf_stages_frozen=frozenset(udf_stages),
            clip_min_sec=clip_min_sec,
            clip_max_sec=clip_max_sec,
            sample_fps=sample_fps,
            model_backend=model_backend,
            cleanup_work=cleanup_work,
        )
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
        ok_rows = [
            row
            for row in result_rows
            if row.get("ok") is True
            or row.get("ok") == 1
            or str(row.get("ok")).lower() == "true"
        ]
        postprocess_stages = driver_stages & {"mc_write", "dispatch"}
        if postprocess_stages and not ok_rows:
            print(
                "WARNING: no successful rows; skipping Driver stages "
                + ",".join(sorted(postprocess_stages))
            )

        if "mc_write" in driver_stages:
            table_prefix = (
                get_dw_arg("sdk_table_prefix")
                or get_dw_arg("table_prefix")
                or "aig_sdk__"
            )
            for row in ok_rows:
                ingest_sdk_run(
                    o,  # type: ignore[name-defined]
                    clip_id=str(row["clip_id"]),
                    run_id=str(row["run_id"]),
                    ds=str(row["ds"]),
                    run_dir=Path(mount_path) / str(row["run_relpath"]),
                    table_prefix=table_prefix,
                    bag_oss_key=str(row["bag_oss_key"]),
                )

        if "dispatch" in driver_stages and ok_rows:
            items = [
                {
                    "clip_id": str(row["clip_id"]),
                    "run_id": str(row["run_id"]),
                    "bag_oss_key": str(row["bag_oss_key"]),
                    "ds": str(row["ds"]),
                    "run_relpath": str(row["run_relpath"]),
                    "run_oss_prefix": run_oss_prefix_from_relpath(
                        str(row["run_relpath"])
                    ),
                }
                for row in ok_rows
            ]
            payload: dict[str, Any] = {
                "action": "run",
                "layout_version": "sdk_v1",
                "pipeline_version": "sdk_v1",
                "batch_size": len(items),
                "items": items,
                "run_oss_prefix": items[0]["run_oss_prefix"],
                "dispatched_at": utc_now_iso(),
            }
            if len(items) == 1:
                payload.update(items[0])
            dispatch_key = (
                get_dw_arg("dispatch_oss_key", DEFAULT_DISPATCH_OSS_KEY)
                or DEFAULT_DISPATCH_OSS_KEY
            )
            dispatch_endpoint = resolve_oss_http_endpoint(
                cloud_region,
                get_arg=get_dw_arg,
                explicit_endpoint=get_dw_arg("oss_endpoint"),
            )
            write_dispatch_to_oss(
                bucket_name=oss_bucket,
                object_key=dispatch_key,
                endpoint=dispatch_endpoint,
                account=account,
                payload=payload,
                region=cloud_region,
                get_arg=get_dw_arg,
            )
            print(
                "DISPATCH_JSON="
                + json.dumps(payload, ensure_ascii=False, default=str)
            )
    except Exception:
        print(f"Logview: {session.get_logview_address()}")
        raise
    finally:
        session.destroy()


if __name__ == "__main__":
    main()
