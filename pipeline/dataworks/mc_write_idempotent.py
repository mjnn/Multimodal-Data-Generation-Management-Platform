"""Idempotent MaxCompute partition writes for Job1~4 mc_write nodes.

DataWorks paste: run `python scripts/bundle_mc_write_node.py dataworks/jobN_mc_write_node.py`
"""

from __future__ import annotations

from typing import Any


def sql_string_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def purge_partition_rows(
    client: Any,
    *,
    table_name: str,
    ds: str,
    columns: str,
    exclude_where: str,
) -> None:
    """INSERT OVERWRITE ds partition, excluding rows matching exclude_where."""
    safe_ds = ds.replace("'", "''")
    sql = f"""
INSERT OVERWRITE TABLE {table_name} PARTITION (ds={sql_string_literal(safe_ds)})
SELECT {columns}
FROM {table_name}
WHERE ds = {sql_string_literal(safe_ds)}
  AND NOT ({exclude_where})
"""
    client.execute_sql(sql).wait_for_success()


def purge_clip_run_rows(
    client: Any,
    *,
    table_name: str,
    ds: str,
    clip_id: str,
    run_id: str,
    columns: str,
) -> None:
    exclude_where = (
        f"clip_id = {sql_string_literal(clip_id)} "
        f"AND run_id = {sql_string_literal(run_id)}"
    )
    purge_partition_rows(
        client,
        table_name=table_name,
        ds=ds,
        columns=columns,
        exclude_where=exclude_where,
    )


def purge_pipeline_step_run(
    client: Any,
    *,
    table_name: str,
    ds: str,
    run_id: str,
    step_id: str,
) -> None:
    columns = "run_id, step_id, status, started_at, finished_at, error_message"
    exclude_where = (
        f"run_id = {sql_string_literal(run_id)} "
        f"AND step_id = {sql_string_literal(step_id)}"
    )
    purge_partition_rows(
        client,
        table_name=table_name,
        ds=ds,
        columns=columns,
        exclude_where=exclude_where,
    )


def purge_pipeline_steps_run(
    client: Any,
    *,
    table_name: str,
    ds: str,
    run_id: str,
    step_ids: tuple[str, ...],
) -> None:
    if not step_ids:
        return
    columns = "run_id, step_id, status, started_at, finished_at, error_message"
    step_clause = ", ".join(sql_string_literal(step_id) for step_id in step_ids)
    exclude_where = (
        f"run_id = {sql_string_literal(run_id)} "
        f"AND step_id IN ({step_clause})"
    )
    purge_partition_rows(
        client,
        table_name=table_name,
        ds=ds,
        columns=columns,
        exclude_where=exclude_where,
    )
