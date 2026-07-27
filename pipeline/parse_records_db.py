"""SQLite persistence for clip parse records."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_COLUMN_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_BASE_COLUMNS: dict[str, str] = {
    "clip_id": "TEXT NOT NULL",
    "clip_dir": "TEXT NOT NULL",
    "parsed_data_dir": "TEXT NOT NULL",
    "summary_path": "TEXT NOT NULL",
    "metadata_path": "TEXT NOT NULL",
    "bag_file": "TEXT NOT NULL",
    "bag_stem": "TEXT NOT NULL",
    "bag_output_dir": "TEXT NOT NULL",
    "duration_ns": "INTEGER NOT NULL",
    "duration_sec": "REAL NOT NULL",
    "start_time_ns": "INTEGER NOT NULL",
    "end_time_ns": "INTEGER NOT NULL",
    "message_count": "INTEGER NOT NULL",
    "parsed_at": "TEXT NOT NULL",
    "updated_at": "TEXT NOT NULL",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_column_name(column_name: str) -> str:
    if not _COLUMN_NAME_PATTERN.match(column_name):
        raise ValueError(f"Invalid SQL column name: {column_name}")
    return column_name


def get_topic_column_specs(db_config: dict[str, Any]) -> list[dict[str, str]]:
    specs = db_config.get("topic_columns", [])
    if not isinstance(specs, list) or not specs:
        raise ValueError("database.topic_columns must be a non-empty list")

    validated: list[dict[str, str]] = []
    seen_columns: set[str] = set()
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError("Each database.topic_columns item must be a mapping")

        topic = str(spec["topic"])
        count_column = _validate_column_name(str(spec["count_column"]))
        if count_column in seen_columns:
            raise ValueError(f"Duplicate topic column name: {count_column}")
        seen_columns.add(count_column)

        item: dict[str, str] = {
            "topic": topic,
            "count_column": count_column,
        }

        msgtype_column = spec.get("msgtype_column")
        if msgtype_column is not None:
            msgtype_column = _validate_column_name(str(msgtype_column))
            if msgtype_column in seen_columns:
                raise ValueError(f"Duplicate topic column name: {msgtype_column}")
            seen_columns.add(msgtype_column)
            item["msgtype_column"] = msgtype_column

        validated.append(item)

    return validated


def _topic_column_definitions(topic_specs: list[dict[str, str]]) -> dict[str, str]:
    columns: dict[str, str] = {}
    for spec in topic_specs:
        columns[spec["count_column"]] = "INTEGER"
        if "msgtype_column" in spec:
            columns[spec["msgtype_column"]] = "TEXT"
    return columns


def _flatten_topics(topics: dict[str, Any], topic_specs: list[dict[str, str]]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for spec in topic_specs:
        topic_data = topics.get(spec["topic"], {})
        flattened[spec["count_column"]] = (
            int(topic_data["count"]) if isinstance(topic_data, dict) and "count" in topic_data else None
        )
        if "msgtype_column" in spec:
            flattened[spec["msgtype_column"]] = (
                str(topic_data["msgtype"])
                if isinstance(topic_data, dict) and "msgtype" in topic_data
                else None
            )
    return flattened


def _existing_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    _validate_column_name(table_name)
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] for row in rows}


def _rebuild_table(conn: sqlite3.Connection, table_name: str, all_columns: dict[str, str]) -> None:
    _validate_column_name(table_name)
    temp_table = f"{table_name}_new"
    _validate_column_name(temp_table)

    column_defs = ",\n                ".join(f"{name} {definition}" for name, definition in all_columns.items())
    shared_columns = [name for name in all_columns if name in _existing_columns(conn, table_name)]

    conn.execute(f"DROP TABLE IF EXISTS {temp_table}")
    conn.execute(
        f"""
        CREATE TABLE {temp_table} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            {column_defs},
            UNIQUE(clip_id, bag_file)
        )
        """
    )

    if shared_columns:
        shared = ", ".join(shared_columns)
        conn.execute(
            f"""
            INSERT INTO {temp_table} ({shared})
            SELECT {shared} FROM {table_name}
            """
        )

    conn.execute(f"DROP TABLE {table_name}")
    conn.execute(f"ALTER TABLE {temp_table} RENAME TO {table_name}")


def init_db(db_path: Path, table_name: str, topic_specs: list[dict[str, str]]) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _validate_column_name(table_name)

    topic_columns = _topic_column_definitions(topic_specs)
    all_columns = {**_BASE_COLUMNS, **topic_columns}
    column_defs = ",\n                ".join(f"{name} {definition}" for name, definition in all_columns.items())

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {column_defs},
                UNIQUE(clip_id, bag_file)
            )
            """
        )

        existing = _existing_columns(conn, table_name)
        if "topics_json" in existing:
            _rebuild_table(conn, table_name, all_columns)
            existing = _existing_columns(conn, table_name)

        for column_name, column_type in all_columns.items():
            if column_name not in existing:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")

        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_clip_id ON {table_name}(clip_id)"
        )
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table_name}_bag_file ON {table_name}(bag_file)"
        )


def upsert_parse_record(
    db_path: Path,
    table_name: str,
    topic_specs: list[dict[str, str]],
    *,
    clip_id: str,
    clip_dir: Path,
    parsed_data_dir: Path,
    summary_path: Path,
    metadata_path: Path,
    bag_output_dir: Path,
    metadata: dict[str, Any],
    parsed_at: str | None = None,
) -> None:
    now = parsed_at or _utc_now_iso()
    bag_file = str(metadata["bag_file"])
    bag_stem = Path(bag_file).stem
    topics = metadata.get("topics", {})
    if not isinstance(topics, dict):
        raise ValueError("metadata.topics must be an object")

    row = {
        "clip_id": clip_id,
        "clip_dir": str(clip_dir),
        "parsed_data_dir": str(parsed_data_dir),
        "summary_path": str(summary_path),
        "metadata_path": str(metadata_path),
        "bag_file": bag_file,
        "bag_stem": bag_stem,
        "bag_output_dir": str(bag_output_dir),
        "duration_ns": int(metadata["duration_ns"]),
        "duration_sec": float(metadata["duration_sec"]),
        "start_time_ns": int(metadata["start_time_ns"]),
        "end_time_ns": int(metadata["end_time_ns"]),
        "message_count": int(metadata["message_count"]),
        **(_flatten_topics(topics, topic_specs)),
        "parsed_at": now,
        "updated_at": now,
    }

    columns = ", ".join(row.keys())
    placeholders = ", ".join(f":{key}" for key in row.keys())
    updates = ", ".join(
        f"{key}=excluded.{key}"
        for key in row.keys()
        if key not in {"clip_id", "bag_file", "parsed_at"}
    )

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            f"""
            INSERT INTO {table_name} ({columns})
            VALUES ({placeholders})
            ON CONFLICT(clip_id, bag_file) DO UPDATE SET
                {updates},
                parsed_at=excluded.parsed_at
            """,
            row,
        )


def sync_clip_records(
    db_path: Path,
    table_name: str,
    topic_specs: list[dict[str, str]],
    *,
    clip_id: str,
    clip_dir: Path,
    parsed_data_dir: Path,
    summary_path: Path,
    output_config: dict[str, Any],
) -> int:
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary file not found: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(summary, list):
        raise ValueError(f"Summary file must contain a JSON array: {summary_path}")

    synced = 0
    for metadata in summary:
        if not isinstance(metadata, dict):
            continue

        bag_stem = Path(str(metadata["bag_file"])).stem
        bag_output_dir = parsed_data_dir / output_config["bag_output_dir"].format(bag_stem=bag_stem)
        metadata_path = bag_output_dir / output_config["metadata_file"]

        upsert_parse_record(
            db_path,
            table_name,
            topic_specs,
            clip_id=clip_id,
            clip_dir=clip_dir,
            parsed_data_dir=parsed_data_dir,
            summary_path=summary_path,
            metadata_path=metadata_path,
            bag_output_dir=bag_output_dir,
            metadata=metadata,
        )
        synced += 1

    return synced
