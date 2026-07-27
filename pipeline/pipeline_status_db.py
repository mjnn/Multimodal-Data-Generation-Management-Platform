"""SQLite persistence for clip pipeline run progress and rollback."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_COLUMN_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_RUN_COLUMNS: dict[str, str] = {
    "run_id": "TEXT NOT NULL",
    "clip_id": "TEXT NOT NULL",
    "clip_dir": "TEXT NOT NULL",
    "pipeline_name": "TEXT NOT NULL",
    "status": "TEXT NOT NULL",
    "current_step_id": "TEXT",
    "rollback_to_step": "TEXT",
    "steps_json": "TEXT NOT NULL",
    "error_message": "TEXT",
    "started_at": "TEXT NOT NULL",
    "updated_at": "TEXT NOT NULL",
    "completed_at": "TEXT",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_column_name(column_name: str) -> str:
    if not _COLUMN_NAME_PATTERN.match(column_name):
        raise ValueError(f"Invalid SQL column name: {column_name}")
    return column_name


def _validate_status(status: str, allowed: set[str], label: str) -> str:
    if status not in allowed:
        raise ValueError(f"Invalid {label}: {status}")
    return status


def get_pipeline_config(config: dict[str, Any]) -> dict[str, Any]:
    pipeline_config = config.get("pipeline")
    if not isinstance(pipeline_config, dict):
        raise ValueError("config.pipeline must be defined")
    return pipeline_config


def get_pipeline_steps(pipeline_config: dict[str, Any]) -> list[dict[str, Any]]:
    steps = pipeline_config.get("steps", [])
    if not isinstance(steps, list) or not steps:
        raise ValueError("pipeline.steps must be a non-empty list")

    validated: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each pipeline.steps item must be a mapping")
        step_id = str(step["id"])
        if step_id in seen_ids:
            raise ValueError(f"Duplicate pipeline step id: {step_id}")
        seen_ids.add(step_id)
        validated.append(step)
    return validated


def get_run_statuses(pipeline_config: dict[str, Any]) -> set[str]:
    statuses = pipeline_config.get("run_statuses", [])
    if not statuses:
        raise ValueError("pipeline.run_statuses must be a non-empty list")
    return {str(status) for status in statuses}


def get_step_statuses(pipeline_config: dict[str, Any]) -> set[str]:
    statuses = pipeline_config.get("step_statuses", [])
    if not statuses:
        raise ValueError("pipeline.step_statuses must be a non-empty list")
    return {str(status) for status in statuses}


def get_enabled_steps(pipeline_config: dict[str, Any]) -> list[dict[str, Any]]:
    return [step for step in get_pipeline_steps(pipeline_config) if step.get("enabled", True)]


def _initial_steps_state(steps: list[dict[str, Any]], pending_status: str) -> dict[str, dict[str, Any]]:
    return {
        str(step["id"]): {
            "name": str(step.get("name", step["id"])),
            "status": pending_status,
            "started_at": None,
            "finished_at": None,
            "error_message": None,
        }
        for step in steps
    }


def init_pipeline_db(db_path: Path, table_name: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_column_name(table_name)

    column_defs = ",\n                ".join(
        f"{name} {definition}" for name, definition in _RUN_COLUMNS.items()
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {column_defs},
                UNIQUE(run_id)
            )
            """
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_clip_id ON {table_name}(clip_id)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_status ON {table_name}(status)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_current_step ON {table_name}(current_step_id)"
        )


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _load_run(conn: sqlite3.Connection, table_name: str, run_id: str) -> sqlite3.Row:
    row = conn.execute(
        f"SELECT * FROM {table_name} WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Pipeline run not found: {run_id}")
    return row


def _dump_steps(steps: dict[str, dict[str, Any]]) -> str:
    return json.dumps(steps, ensure_ascii=False)


def _parse_steps(steps_json: str) -> dict[str, dict[str, Any]]:
    steps = json.loads(steps_json)
    if not isinstance(steps, dict):
        raise ValueError("steps_json must decode to an object")
    return steps


def create_pipeline_run(
    db_path: Path,
    table_name: str,
    pipeline_config: dict[str, Any],
    *,
    clip_id: str,
    clip_dir: Path,
) -> str:
    steps = get_pipeline_steps(pipeline_config)
    enabled_steps = get_enabled_steps(pipeline_config)
    if not enabled_steps:
        raise ValueError("No enabled pipeline steps configured")

    run_statuses = get_run_statuses(pipeline_config)
    step_statuses = get_step_statuses(pipeline_config)
    pending_run_status = str(pipeline_config["initial_run_status"])
    pending_step_status = str(pipeline_config["initial_step_status"])
    _validate_status(pending_run_status, run_statuses, "initial_run_status")
    _validate_status(pending_step_status, step_statuses, "initial_step_status")

    run_id = str(uuid.uuid4())
    now = _utc_now_iso()
    first_step_id = str(enabled_steps[0]["id"])
    steps_state = _initial_steps_state(steps, pending_step_status)

    row = {
        "run_id": run_id,
        "clip_id": clip_id,
        "clip_dir": str(clip_dir),
        "pipeline_name": str(pipeline_config["name"]),
        "status": pending_run_status,
        "current_step_id": first_step_id,
        "rollback_to_step": None,
        "steps_json": _dump_steps(steps_state),
        "error_message": None,
        "started_at": now,
        "updated_at": now,
        "completed_at": None,
    }

    columns = ", ".join(row.keys())
    placeholders = ", ".join(f":{key}" for key in row.keys())
    with _connect(db_path) as conn:
        conn.execute(
            f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
            row,
        )
    return run_id


def get_latest_run(db_path: Path, table_name: str, clip_id: str) -> dict[str, Any] | None:
    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT * FROM {table_name}
            WHERE clip_id = ?
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (clip_id,),
        ).fetchone()
    return dict(row) if row else None


def get_latest_run_for_clip_dir(
    db_path: Path,
    table_name: str,
    clip_dir: Path,
) -> dict[str, Any] | None:
    clip_dir_text = str(clip_dir.resolve())
    clip_dir_name = clip_dir.name
    with _connect(db_path) as conn:
        row = conn.execute(
            f"""
            SELECT * FROM {table_name}
            WHERE clip_dir = ? OR clip_dir LIKE ?
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            (clip_dir_text, f"%{clip_dir_name}"),
        ).fetchone()
    return dict(row) if row else None


def get_run(db_path: Path, table_name: str, run_id: str) -> dict[str, Any]:
    with _connect(db_path) as conn:
        return dict(_load_run(conn, table_name, run_id))


def list_runs(
    db_path: Path,
    table_name: str,
    *,
    clip_id: str | None = None,
    status: str | None = None,
    current_step_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = f"SELECT * FROM {table_name} WHERE 1=1"
    params: list[Any] = []

    if clip_id is not None:
        query += " AND clip_id = ?"
        params.append(clip_id)
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    if current_step_id is not None:
        query += " AND current_step_id = ?"
        params.append(current_step_id)

    query += " ORDER BY updated_at DESC, id DESC LIMIT ?"
    params.append(limit)

    with _connect(db_path) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _save_run(
    conn: sqlite3.Connection,
    table_name: str,
    run_id: str,
    *,
    status: str,
    current_step_id: str | None,
    steps: dict[str, dict[str, Any]],
    error_message: str | None,
    rollback_to_step: str | None = None,
    completed_at: str | None = None,
) -> None:
    now = _utc_now_iso()
    conn.execute(
        f"""
        UPDATE {table_name}
        SET status = ?,
            current_step_id = ?,
            rollback_to_step = ?,
            steps_json = ?,
            error_message = ?,
            updated_at = ?,
            completed_at = ?
        WHERE run_id = ?
        """,
        (
            status,
            current_step_id,
            rollback_to_step,
            _dump_steps(steps),
            error_message,
            now,
            completed_at,
            run_id,
        ),
    )


def mark_run_running(
    db_path: Path,
    table_name: str,
    pipeline_config: dict[str, Any],
    run_id: str,
) -> None:
    running_status = str(pipeline_config["running_status"])
    _validate_status(running_status, get_run_statuses(pipeline_config), "running_status")

    with _connect(db_path) as conn:
        row = _load_run(conn, table_name, run_id)
        steps = _parse_steps(row["steps_json"])
        _save_run(
            conn,
            table_name,
            run_id,
            status=running_status,
            current_step_id=row["current_step_id"],
            steps=steps,
            error_message=None,
            rollback_to_step=row["rollback_to_step"],
            completed_at=row["completed_at"],
        )


def mark_step_running(
    db_path: Path,
    table_name: str,
    pipeline_config: dict[str, Any],
    run_id: str,
    step_id: str,
) -> None:
    running_status = str(pipeline_config["running_status"])
    step_running_status = str(pipeline_config["step_running_status"])
    _validate_status(running_status, get_run_statuses(pipeline_config), "running_status")
    _validate_status(step_running_status, get_step_statuses(pipeline_config), "step_running_status")

    with _connect(db_path) as conn:
        row = _load_run(conn, table_name, run_id)
        steps = _parse_steps(row["steps_json"])
        if step_id not in steps:
            raise KeyError(f"Unknown pipeline step: {step_id}")

        steps[step_id]["status"] = step_running_status
        steps[step_id]["started_at"] = _utc_now_iso()
        steps[step_id]["finished_at"] = None
        steps[step_id]["error_message"] = None

        _save_run(
            conn,
            table_name,
            run_id,
            status=running_status,
            current_step_id=step_id,
            steps=steps,
            error_message=None,
            rollback_to_step=row["rollback_to_step"],
            completed_at=None,
        )


def mark_step_completed(
    db_path: Path,
    table_name: str,
    pipeline_config: dict[str, Any],
    run_id: str,
    step_id: str,
) -> None:
    completed_step_status = str(pipeline_config["step_completed_status"])
    completed_run_status = str(pipeline_config["completed_status"])
    _validate_status(completed_step_status, get_step_statuses(pipeline_config), "step_completed_status")
    _validate_status(completed_run_status, get_run_statuses(pipeline_config), "completed_status")

    enabled_steps = get_enabled_steps(pipeline_config)
    step_ids = [str(step["id"]) for step in enabled_steps]

    with _connect(db_path) as conn:
        row = _load_run(conn, table_name, run_id)
        steps = _parse_steps(row["steps_json"])
        if step_id not in steps:
            raise KeyError(f"Unknown pipeline step: {step_id}")

        now = _utc_now_iso()
        steps[step_id]["status"] = completed_step_status
        steps[step_id]["finished_at"] = now
        steps[step_id]["error_message"] = None

        if step_id not in step_ids:
            raise KeyError(f"Step is disabled: {step_id}")

        step_index = step_ids.index(step_id)
        if step_index + 1 < len(step_ids):
            next_step_id = step_ids[step_index + 1]
            run_status = str(pipeline_config["running_status"])
            current_step_id = next_step_id
            completed_at = None
        else:
            run_status = completed_run_status
            current_step_id = step_id
            completed_at = now

        _save_run(
            conn,
            table_name,
            run_id,
            status=run_status,
            current_step_id=current_step_id,
            steps=steps,
            error_message=None,
            rollback_to_step=row["rollback_to_step"],
            completed_at=completed_at,
        )


def mark_step_failed(
    db_path: Path,
    table_name: str,
    pipeline_config: dict[str, Any],
    run_id: str,
    step_id: str,
    error_message: str,
) -> None:
    failed_run_status = str(pipeline_config["failed_status"])
    failed_step_status = str(pipeline_config["step_failed_status"])
    _validate_status(failed_run_status, get_run_statuses(pipeline_config), "failed_status")
    _validate_status(failed_step_status, get_step_statuses(pipeline_config), "step_failed_status")

    with _connect(db_path) as conn:
        row = _load_run(conn, table_name, run_id)
        steps = _parse_steps(row["steps_json"])
        if step_id not in steps:
            raise KeyError(f"Unknown pipeline step: {step_id}")

        steps[step_id]["status"] = failed_step_status
        steps[step_id]["finished_at"] = _utc_now_iso()
        steps[step_id]["error_message"] = error_message

        _save_run(
            conn,
            table_name,
            run_id,
            status=failed_run_status,
            current_step_id=step_id,
            steps=steps,
            error_message=error_message,
            rollback_to_step=row["rollback_to_step"],
            completed_at=None,
        )


def rollback_run(
    db_path: Path,
    table_name: str,
    pipeline_config: dict[str, Any],
    run_id: str,
    to_step_id: str,
) -> None:
    pending_run_status = str(pipeline_config["initial_run_status"])
    pending_step_status = str(pipeline_config["initial_step_status"])
    rolled_back_status = str(pipeline_config["rolled_back_status"])
    _validate_status(pending_run_status, get_run_statuses(pipeline_config), "initial_run_status")
    _validate_status(pending_step_status, get_step_statuses(pipeline_config), "initial_step_status")
    _validate_status(rolled_back_status, get_run_statuses(pipeline_config), "rolled_back_status")

    enabled_steps = get_enabled_steps(pipeline_config)
    step_ids = [str(step["id"]) for step in enabled_steps]
    if to_step_id not in step_ids:
        raise KeyError(f"Unknown enabled pipeline step: {to_step_id}")

    rollback_index = step_ids.index(to_step_id)

    with _connect(db_path) as conn:
        row = _load_run(conn, table_name, run_id)
        steps = _parse_steps(row["steps_json"])

        for index, step_id in enumerate(step_ids):
            if index >= rollback_index:
                steps[step_id]["status"] = pending_step_status
                steps[step_id]["started_at"] = None
                steps[step_id]["finished_at"] = None
                steps[step_id]["error_message"] = None

        _save_run(
            conn,
            table_name,
            run_id,
            status=rolled_back_status,
            current_step_id=to_step_id,
            steps=steps,
            error_message=None,
            rollback_to_step=to_step_id,
            completed_at=None,
        )


def get_next_step_id(pipeline_config: dict[str, Any], steps: dict[str, dict[str, Any]]) -> str | None:
    pending_step_status = str(pipeline_config["initial_step_status"])
    for step in get_enabled_steps(pipeline_config):
        step_id = str(step["id"])
        if steps[step_id]["status"] == pending_step_status:
            return step_id
    return None
