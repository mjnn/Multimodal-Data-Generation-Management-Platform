"""Export dataset snapshot rows to MaxCompute (cloud mode only)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from hmi.config import get_settings, table_name
from hmi.data_source import is_local_mode
from hmi.dataset.assemble import AssemblyResult
from hmi.db import odps_client, sql_quote

MC_TABLE_SUFFIX = "dataset_snapshot_row"
DEFAULT_DS = "19700101"


def should_export_to_mc() -> bool:
    return not is_local_mode()


def resolve_mc_table_name() -> str:
    settings = get_settings()
    return table_name(settings, MC_TABLE_SUFFIX)


def _utc_ds_today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


def resolve_ds_for_row(clip_id: str, run_id: str) -> str:
    try:
        from hmi.local.clip_context import resolve_ds_for_run

        return resolve_ds_for_run(clip_id, run_id)
    except (ImportError, ValueError):
        pass

    try:
        from hmi.db import query

        settings = get_settings()
        run_table = table_name(settings, "pipeline_run")
        rows = query(
            f"""
            SELECT ds FROM {run_table}
            WHERE clip_id = {sql_quote(clip_id)} AND run_id = {sql_quote(run_id)}
            LIMIT 1
            """,
            cache=False,
        )
        if rows and rows[0].get("ds"):
            return str(rows[0]["ds"])
    except Exception:
        pass

    return _utc_ds_today() if should_export_to_mc() else DEFAULT_DS


def _mc_row(snapshot_id: str, row: dict[str, Any]) -> list[Any]:
    clip_id = str(row["clip_id"])
    run_id = str(row["run_id"])
    return [
        snapshot_id,
        clip_id,
        run_id,
        json.dumps(row.get("x_json") or [], ensure_ascii=False),
        json.dumps(row.get("y_json") or {}, ensure_ascii=False),
        row.get("taxonomy_version_id"),
        row.get("taxonomy_version_code"),
        resolve_ds_for_row(clip_id, run_id),
    ]


def clear_snapshot_partition(snapshot_id: str, *, client: Any | None = None) -> None:
    table_name_full = resolve_mc_table_name()
    odps = client or odps_client()
    odps.execute_sql(
        f"DELETE FROM {table_name_full} WHERE snapshot_id = {sql_quote(snapshot_id)};"
    )


def export_snapshot_rows_to_mc(
    snapshot_id: str,
    assembly: AssemblyResult,
    *,
    client: Any | None = None,
    clear_existing: bool = True,
) -> dict[str, Any]:
    if not should_export_to_mc():
        return {"mc_table_name": None, "row_count": 0, "skipped": True}

    if not assembly.rows:
        raise ValueError("no rows to export to MaxCompute")

    table_name_full = resolve_mc_table_name()
    odps = client or odps_client()
    mc_rows = [_mc_row(snapshot_id, row) for row in assembly.rows]

    if clear_existing:
        clear_snapshot_partition(snapshot_id, client=odps)

    table = odps.get_table(table_name_full)
    partition = f"snapshot_id={snapshot_id}"
    with table.open_writer(partition=partition, create_partition=True) as writer:
        writer.write(mc_rows)

    return {
        "mc_table_name": table_name_full,
        "row_count": len(mc_rows),
        "skipped": False,
    }
