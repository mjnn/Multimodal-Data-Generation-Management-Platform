"""Resolve clip_id + run_id + ds partition for MC queries."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from hmi.config import get_settings, table_name
from hmi.db import query, sql_quote


@dataclass
class ClipContext:
    clip_id: str
    run_id: str
    ds: str
    bag_oss_key: str
    clip_dir_name: str
    start_time_ns: int
    end_time_ns: int
    duration_sec: float


def _partition_ds(part_name: str) -> str:
    part_name = part_name.strip()
    if part_name.startswith("ds="):
        return part_name.split("=", 1)[1].strip().strip("'").strip('"')
    return part_name


@lru_cache(maxsize=8)
def list_ds_partitions(table_suffix: str) -> list[str]:
    settings = get_settings()
    client = __import__("hmi.db", fromlist=["odps_client"]).odps_client()
    name = table_name(settings, table_suffix)
    if not client.exist_table(name):
        return []
    table = client.get_table(name)
    if not table.table_schema.partitions:
        return []
    return sorted({_partition_ds(p.name) for p in table.partitions}, reverse=True)


def resolve_active_run_id(clip_id: str, run_id: str | None = None) -> str:
    if run_id:
        return run_id
    settings = get_settings()
    rows = query(
        f"SELECT active_run_id FROM {table_name(settings, 'dim_clip')} "
        f"WHERE clip_id={sql_quote(clip_id)} LIMIT 1"
    )
    if not rows or not rows[0].get("active_run_id"):
        raise ValueError(f"No active_run_id for clip_id={clip_id}")
    return str(rows[0]["active_run_id"])


def resolve_ds_for_run(clip_id: str, run_id: str) -> str:
    """MC partitioned tables require ds predicate — scan partition list (newest first)."""
    settings = get_settings()
    run_tbl = table_name(settings, "pipeline_run")
    for ds in list_ds_partitions("pipeline_run"):
        rows = query(
            f"SELECT ds FROM {run_tbl} WHERE ds={sql_quote(ds)} "
            f"AND clip_id={sql_quote(clip_id)} AND run_id={sql_quote(run_id)} LIMIT 1"
        )
        if rows:
            return ds
    step_tbl = table_name(settings, "pipeline_step")
    for ds in list_ds_partitions("pipeline_step"):
        rows = query(
            f"SELECT ds FROM {step_tbl} WHERE ds={sql_quote(ds)} "
            f"AND run_id={sql_quote(run_id)} LIMIT 1"
        )
        if rows:
            return ds
    raise ValueError(f"No ds partition found for clip={clip_id} run={run_id}")


def get_dim_clip(clip_id: str) -> dict[str, Any]:
    settings = get_settings()
    rows = query(
        f"SELECT clip_id, clip_dir_name, bag_oss_key, active_run_id "
        f"FROM {table_name(settings, 'dim_clip')} "
        f"WHERE clip_id={sql_quote(clip_id)} LIMIT 1"
    )
    if not rows:
        raise ValueError(f"clip not found: {clip_id}")
    return rows[0]


@lru_cache(maxsize=64)
def resolve_clip_context(clip_id: str, run_id: str | None = None) -> ClipContext:
    dim = get_dim_clip(clip_id)
    resolved_run = resolve_active_run_id(clip_id, run_id or dim.get("active_run_id"))
    ds = resolve_ds_for_run(clip_id, resolved_run)
    settings = get_settings()
    summary_tbl = table_name(settings, "clip_parse_summary")
    summary_rows = query(
        f"SELECT start_time_ns, end_time_ns, duration_sec FROM {summary_tbl} "
        f"WHERE ds={sql_quote(ds)} AND clip_id={sql_quote(clip_id)} "
        f"AND run_id={sql_quote(resolved_run)} LIMIT 1"
    )
    if summary_rows:
        start_ns = int(summary_rows[0]["start_time_ns"])
        end_ns = int(summary_rows[0]["end_time_ns"])
        duration = float(summary_rows[0]["duration_sec"])
    else:
        start_ns, end_ns, duration = 0, 0, 0.0
    return ClipContext(
        clip_id=clip_id,
        run_id=resolved_run,
        ds=ds,
        bag_oss_key=str(dim.get("bag_oss_key") or ""),
        clip_dir_name=str(dim.get("clip_dir_name") or clip_id[:24]),
        start_time_ns=start_ns,
        end_time_ns=end_ns,
        duration_sec=duration,
    )


def context_cache_clear() -> None:
    resolve_clip_context.cache_clear()
    list_ds_partitions.cache_clear()


def find_clip_id_by_bag_key(bag_oss_key: str) -> str | None:
    settings = get_settings()
    rows = query(
        f"SELECT clip_id FROM {table_name(settings, 'dim_clip')} "
        f"WHERE bag_oss_key={sql_quote(bag_oss_key)} LIMIT 1",
        cache=False,
    )
    return str(rows[0]["clip_id"]) if rows else None
