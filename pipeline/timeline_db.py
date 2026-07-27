"""SQLite persistence for Job1 timeline tables (MC schema 1:1)."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_COLUMN_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_TABLE_DEFINITIONS: dict[str, dict[str, str]] = {
  "dim_clip": {
    "clip_id": "TEXT NOT NULL",
    "clip_dir_name": "TEXT NOT NULL",
    "content_hash": "TEXT NOT NULL",
    "active_run_id": "TEXT",
    "created_at": "TEXT NOT NULL",
    "updated_at": "TEXT NOT NULL",
  },
  "pipeline_run": {
    "run_id": "TEXT NOT NULL",
    "clip_id": "TEXT NOT NULL",
    "status": "TEXT NOT NULL",
    "started_at": "TEXT NOT NULL",
    "updated_at": "TEXT NOT NULL",
    "completed_at": "TEXT",
  },
  "pipeline_step": {
    "run_id": "TEXT NOT NULL",
    "step_id": "TEXT NOT NULL",
    "status": "TEXT NOT NULL",
    "started_at": "TEXT",
    "finished_at": "TEXT",
    "error_message": "TEXT",
  },
  "fact_message_timeline": {
    "clip_id": "TEXT NOT NULL",
    "run_id": "TEXT NOT NULL",
    "bag_stem": "TEXT NOT NULL",
    "topic": "TEXT NOT NULL",
    "msgtype": "TEXT NOT NULL",
    "modality": "TEXT NOT NULL",
    "timestamp_ns": "INTEGER NOT NULL",
    "sequence_idx": "INTEGER NOT NULL",
  },
  "fact_frame": {
    "clip_id": "TEXT NOT NULL",
    "run_id": "TEXT NOT NULL",
    "bag_stem": "TEXT NOT NULL",
    "camera": "TEXT NOT NULL",
    "frame_idx": "INTEGER NOT NULL",
    "timestamp_ns": "INTEGER NOT NULL",
    "topic": "TEXT NOT NULL",
    "image_path": "TEXT NOT NULL",
  },
  "fact_audio_chunk": {
    "clip_id": "TEXT NOT NULL",
    "run_id": "TEXT NOT NULL",
    "bag_stem": "TEXT NOT NULL",
    "chunk_idx": "INTEGER NOT NULL",
    "timestamp_ns": "INTEGER NOT NULL",
    "byte_offset": "INTEGER NOT NULL",
    "byte_length": "INTEGER NOT NULL",
    "sample_count": "INTEGER NOT NULL",
    "duration_ns": "INTEGER NOT NULL",
    "pcm_bytes": "INTEGER NOT NULL",
  },
  "fact_event": {
    "clip_id": "TEXT NOT NULL",
    "run_id": "TEXT NOT NULL",
    "bag_stem": "TEXT NOT NULL",
    "timestamp_ns": "INTEGER NOT NULL",
    "event_data": "TEXT NOT NULL",
  },
  "clip_parse_summary": {
    "clip_id": "TEXT NOT NULL",
    "run_id": "TEXT NOT NULL",
    "bag_stem": "TEXT NOT NULL",
    "bag_file": "TEXT NOT NULL",
    "duration_ns": "INTEGER NOT NULL",
    "duration_sec": "REAL NOT NULL",
    "start_time_ns": "INTEGER NOT NULL",
    "end_time_ns": "INTEGER NOT NULL",
    "message_count": "INTEGER NOT NULL",
    "topics_json": "TEXT NOT NULL",
    "parsed_at": "TEXT NOT NULL",
  },
}

_TABLE_INDEXES: dict[str, list[str]] = {
  "fact_message_timeline": ["clip_id", "timestamp_ns", "modality"],
  "fact_frame": ["clip_id", "timestamp_ns", "camera"],
  "fact_audio_chunk": ["clip_id", "timestamp_ns"],
  "fact_event": ["clip_id", "timestamp_ns"],
  "clip_parse_summary": ["clip_id", "bag_stem"],
}


def _utc_now_iso() -> str:
  return datetime.now(timezone.utc).isoformat()


def _validate_column_name(column_name: str) -> str:
  if not _COLUMN_NAME_PATTERN.match(column_name):
    raise ValueError(f"Invalid SQL column name: {column_name}")
  return column_name


def get_timeline_config(config: dict[str, Any]) -> dict[str, Any]:
  db_config = config.get("database", {})
  timeline_config = db_config.get("timeline")
  if not isinstance(timeline_config, dict):
    raise ValueError("database.timeline must be defined")
  return timeline_config


def table_name(prefix: str, base_name: str) -> str:
  _validate_column_name(base_name.replace("__", "_"))
  full_name = f"{prefix}{base_name}"
  _validate_column_name(full_name.replace("__", "_"))
  return full_name


def init_timeline_db(db_path: Path, table_prefix: str) -> None:
  db_path.parent.mkdir(parents=True, exist_ok=True)
  with sqlite3.connect(db_path) as conn:
    for base_name, columns in _TABLE_DEFINITIONS.items():
      full_table = table_name(table_prefix, base_name)
      column_defs = ",\n          ".join(
        f"{name} {definition}" for name, definition in columns.items()
      )
      unique_clause = ""
      if base_name == "dim_clip":
        unique_clause = ",\n          UNIQUE(clip_id)"
      elif base_name == "pipeline_run":
        unique_clause = ",\n          UNIQUE(run_id)"
      elif base_name == "pipeline_step":
        unique_clause = ",\n          UNIQUE(run_id, step_id)"
      elif base_name == "fact_frame":
        unique_clause = ",\n          UNIQUE(clip_id, run_id, bag_stem, camera, frame_idx)"
      elif base_name == "fact_audio_chunk":
        unique_clause = ",\n          UNIQUE(clip_id, run_id, bag_stem, chunk_idx)"
      elif base_name == "clip_parse_summary":
        unique_clause = ",\n          UNIQUE(clip_id, run_id, bag_stem)"

      conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {full_table} (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          {column_defs}
          {unique_clause}
        )
        """
      )

      for index_column in _TABLE_INDEXES.get(base_name, []):
        index_name = f"idx_{full_table}_{index_column}"
        conn.execute(
          f"CREATE INDEX IF NOT EXISTS {index_name} ON {full_table}({index_column})"
        )


def _delete_bag_rows(
  conn: sqlite3.Connection,
  table_prefix: str,
  *,
  clip_id: str,
  run_id: str,
  bag_stem: str,
  base_tables: list[str],
) -> None:
  for base_name in base_tables:
    full_table = table_name(table_prefix, base_name)
    conn.execute(
      f"DELETE FROM {full_table} WHERE clip_id = ? AND run_id = ? AND bag_stem = ?",
      (clip_id, run_id, bag_stem),
    )


def get_dim_clip(
  db_path: Path,
  table_prefix: str,
  clip_id: str,
) -> dict[str, Any] | None:
  init_timeline_db(db_path, table_prefix)
  full_table = table_name(table_prefix, "dim_clip")
  with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
      f"SELECT * FROM {full_table} WHERE clip_id = ?",
      (clip_id,),
    ).fetchone()
  return dict(row) if row else None


def list_clip_run_versions(
  db_path: Path,
  table_prefix: str,
  clip_id: str,
) -> list[dict[str, Any]]:
  """List known run_id versions for a clip from timeline summary rows."""
  init_timeline_db(db_path, table_prefix)
  summary_table = table_name(table_prefix, "clip_parse_summary")
  dim_clip = get_dim_clip(db_path, table_prefix, clip_id)
  active_run_id = dim_clip["active_run_id"] if dim_clip else None

  with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
      f"""
      SELECT
        run_id,
        COUNT(*) AS bag_count,
        MIN(parsed_at) AS first_parsed_at,
        MAX(parsed_at) AS last_parsed_at
      FROM {summary_table}
      WHERE clip_id = ?
      GROUP BY run_id
      ORDER BY last_parsed_at DESC, run_id DESC
      """,
      (clip_id,),
    ).fetchall()

  return [
    {
      **dict(row),
      "is_active": row["run_id"] == active_run_id,
    }
    for row in rows
  ]


def run_id_has_timeline_data(
  conn: sqlite3.Connection,
  table_prefix: str,
  *,
  clip_id: str,
  run_id: str,
) -> bool:
  summary_table = table_name(table_prefix, "clip_parse_summary")
  row = conn.execute(
    f"SELECT 1 FROM {summary_table} WHERE clip_id = ? AND run_id = ? LIMIT 1",
    (clip_id, run_id),
  ).fetchone()
  return row is not None


def set_active_run_id(
  db_path: Path,
  table_prefix: str,
  *,
  clip_id: str,
  run_id: str,
) -> dict[str, Any]:
  """Switch dim_clip.active_run_id to an existing timeline run version."""
  init_timeline_db(db_path, table_prefix)
  full_table = table_name(table_prefix, "dim_clip")

  with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    dim_row = conn.execute(
      f"SELECT * FROM {full_table} WHERE clip_id = ?",
      (clip_id,),
    ).fetchone()
    if dim_row is None:
      raise KeyError(f"Clip not found in dim_clip: {clip_id}")
    if not run_id_has_timeline_data(conn, table_prefix, clip_id=clip_id, run_id=run_id):
      raise KeyError(
        f"Run has no timeline data for clip {clip_id}: {run_id}"
      )

    now = _utc_now_iso()
    conn.execute(
      f"""
      UPDATE {full_table}
      SET active_run_id = ?, updated_at = ?
      WHERE clip_id = ?
      """,
      (run_id, now, clip_id),
    )

  updated = get_dim_clip(db_path, table_prefix, clip_id)
  if updated is None:
    raise RuntimeError(f"Failed to reload dim_clip after update: {clip_id}")
  return updated


def resolve_active_run_id(
  db_path: Path,
  table_prefix: str,
  clip_id: str,
) -> str | None:
  dim_clip = get_dim_clip(db_path, table_prefix, clip_id)
  if dim_clip is None:
    return None
  active_run_id = dim_clip.get("active_run_id")
  return str(active_run_id) if active_run_id else None


def upsert_dim_clip(
  conn: sqlite3.Connection,
  table_prefix: str,
  *,
  clip_id: str,
  clip_dir_name: str,
  content_hash: str,
  active_run_id: str | None = None,
) -> None:
  full_table = table_name(table_prefix, "dim_clip")
  now = _utc_now_iso()
  conn.execute(
    f"""
    INSERT INTO {full_table} (
      clip_id, clip_dir_name, content_hash, active_run_id, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(clip_id) DO UPDATE SET
      clip_dir_name = excluded.clip_dir_name,
      content_hash = excluded.content_hash,
      active_run_id = COALESCE(excluded.active_run_id, {full_table}.active_run_id),
      updated_at = excluded.updated_at
    """,
    (clip_id, clip_dir_name, content_hash, active_run_id, now, now),
  )


def write_job1_timeline(
  db_path: Path,
  table_prefix: str,
  *,
  clip_id: str,
  clip_dir_name: str,
  content_hash: str,
  run_id: str,
  bag_stem: str,
  metadata: dict[str, Any],
  timeline_messages: list[dict[str, Any]],
  frames: list[dict[str, Any]],
  audio_chunks: list[dict[str, Any]],
  events: list[dict[str, Any]],
  parsed_at: str | None = None,
) -> None:
  now = parsed_at or _utc_now_iso()
  init_timeline_db(db_path, table_prefix)

  with sqlite3.connect(db_path) as conn:
    upsert_dim_clip(
      conn,
      table_prefix,
      clip_id=clip_id,
      clip_dir_name=clip_dir_name,
      content_hash=content_hash,
      active_run_id=run_id,
    )

    _delete_bag_rows(
      conn,
      table_prefix,
      clip_id=clip_id,
      run_id=run_id,
      bag_stem=bag_stem,
      base_tables=[
        "fact_message_timeline",
        "fact_frame",
        "fact_audio_chunk",
        "fact_event",
        "clip_parse_summary",
      ],
    )

    timeline_table = table_name(table_prefix, "fact_message_timeline")
    conn.executemany(
      f"""
      INSERT INTO {timeline_table} (
        clip_id, run_id, bag_stem, topic, msgtype, modality, timestamp_ns, sequence_idx
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      """,
      [
        (
          clip_id,
          run_id,
          bag_stem,
          item["topic"],
          item["msgtype"],
          item["modality"],
          int(item["timestamp_ns"]),
          int(item["sequence_idx"]),
        )
        for item in timeline_messages
      ],
    )

    frame_table = table_name(table_prefix, "fact_frame")
    conn.executemany(
      f"""
      INSERT INTO {frame_table} (
        clip_id, run_id, bag_stem, camera, frame_idx, timestamp_ns, topic, image_path
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      """,
      [
        (
          clip_id,
          run_id,
          bag_stem,
          item["camera"],
          int(item["frame_idx"]),
          int(item["timestamp_ns"]),
          item["topic"],
          item["image_path"],
        )
        for item in frames
      ],
    )

    audio_table = table_name(table_prefix, "fact_audio_chunk")
    conn.executemany(
      f"""
      INSERT INTO {audio_table} (
        clip_id, run_id, bag_stem, chunk_idx, timestamp_ns, byte_offset, byte_length,
        sample_count, duration_ns, pcm_bytes
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      [
        (
          clip_id,
          run_id,
          bag_stem,
          int(item["chunk_idx"]),
          int(item["timestamp_ns"]),
          int(item["byte_offset"]),
          int(item["byte_length"]),
          int(item["sample_count"]),
          int(item["duration_ns"]),
          int(item["pcm_bytes"]),
        )
        for item in audio_chunks
      ],
    )

    event_table = table_name(table_prefix, "fact_event")
    conn.executemany(
      f"""
      INSERT INTO {event_table} (
        clip_id, run_id, bag_stem, timestamp_ns, event_data
      ) VALUES (?, ?, ?, ?, ?)
      """,
      [
        (
          clip_id,
          run_id,
          bag_stem,
          int(item["timestamp_ns"]),
          item["event_data"],
        )
        for item in events
      ],
    )

    summary_table = table_name(table_prefix, "clip_parse_summary")
    conn.execute(
      f"""
      INSERT INTO {summary_table} (
        clip_id, run_id, bag_stem, bag_file, duration_ns, duration_sec,
        start_time_ns, end_time_ns, message_count, topics_json, parsed_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(clip_id, run_id, bag_stem) DO UPDATE SET
        bag_file = excluded.bag_file,
        duration_ns = excluded.duration_ns,
        duration_sec = excluded.duration_sec,
        start_time_ns = excluded.start_time_ns,
        end_time_ns = excluded.end_time_ns,
        message_count = excluded.message_count,
        topics_json = excluded.topics_json,
        parsed_at = excluded.parsed_at
      """,
      (
        clip_id,
        run_id,
        bag_stem,
        str(metadata["bag_file"]),
        int(metadata["duration_ns"]),
        float(metadata["duration_sec"]),
        int(metadata["start_time_ns"]),
        int(metadata["end_time_ns"]),
        int(metadata["message_count"]),
        json.dumps(metadata.get("topics", {}), ensure_ascii=False),
        now,
      ),
    )


def query_nearby(
  db_path: Path,
  table_prefix: str,
  *,
  clip_id: str,
  timestamp_ns: int,
  window_ns: int,
  run_id: str | None = None,
  use_active_run: bool = True,
) -> dict[str, list[dict[str, Any]]]:
  """Return frames, events, and audio chunks within ±window_ns of timestamp_ns."""
  init_timeline_db(db_path, table_prefix)
  effective_run_id = run_id
  if effective_run_id is None and use_active_run:
    effective_run_id = resolve_active_run_id(db_path, table_prefix, clip_id)

  start_ns = timestamp_ns - window_ns
  end_ns = timestamp_ns + window_ns
  run_filter = "AND run_id = ?" if effective_run_id else ""
  params_suffix: tuple[Any, ...] = (effective_run_id,) if effective_run_id else ()

  result: dict[str, list[dict[str, Any]]] = {
    "frames": [],
    "events": [],
    "audio_chunks": [],
  }

  with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    for key, base_name in (
      ("frames", "fact_frame"),
      ("events", "fact_event"),
      ("audio_chunks", "fact_audio_chunk"),
    ):
      full_table = table_name(table_prefix, base_name)
      rows = conn.execute(
        f"""
        SELECT * FROM {full_table}
        WHERE clip_id = ? {run_filter}
          AND timestamp_ns BETWEEN ? AND ?
        ORDER BY timestamp_ns
        """,
        (clip_id, *params_suffix, start_ns, end_ns),
      ).fetchall()
      result[key] = [dict(row) for row in rows]

  return result
