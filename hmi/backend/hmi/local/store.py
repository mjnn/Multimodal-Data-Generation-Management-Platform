"""SQLite access for local HMI data source."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from hmi.data_source import LOCAL_DB_PATH, LOCAL_ROOT

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(fact_image_label)")}
    for name, ddl in (
        ("sync_group_id", "ALTER TABLE fact_image_label ADD COLUMN sync_group_id TEXT"),
        ("anchor_timestamp_ns", "ALTER TABLE fact_image_label ADD COLUMN anchor_timestamp_ns INTEGER"),
        ("label_scope", "ALTER TABLE fact_image_label ADD COLUMN label_scope TEXT"),
        ("taxonomy_version_id", "ALTER TABLE fact_image_label ADD COLUMN taxonomy_version_id TEXT"),
    ):
        if cols and name not in cols:
            conn.execute(ddl)
    run_cols = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_run)")}
    if run_cols and "label_granularity" not in run_cols:
        conn.execute("ALTER TABLE pipeline_run ADD COLUMN label_granularity TEXT")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS fact_sample_sync_group (
          clip_id TEXT NOT NULL,
          run_id TEXT NOT NULL,
          ds TEXT NOT NULL,
          sync_group_id TEXT NOT NULL,
          anchor_timestamp_ns INTEGER,
          sample_policy TEXT,
          align_window_ms INTEGER,
          frame_ids_json TEXT,
          created_at TEXT,
          PRIMARY KEY (clip_id, run_id, ds, sync_group_id)
        );
        CREATE INDEX IF NOT EXISTS idx_fact_sample_sync_group_anchor
          ON fact_sample_sync_group (clip_id, run_id, ds, anchor_timestamp_ns);

        CREATE TABLE IF NOT EXISTS fact_clip_label (
          clip_id TEXT NOT NULL,
          run_id TEXT NOT NULL,
          ds TEXT NOT NULL,
          labels_json TEXT NOT NULL,
          taxonomy_version_id TEXT,
          model_version TEXT,
          label_source TEXT NOT NULL DEFAULT 'ai',
          anchor_timestamp_ns INTEGER,
          multi_ai_meta_json TEXT,
          created_at TEXT,
          updated_at TEXT,
          PRIMARY KEY (clip_id, run_id, ds)
        );
        CREATE INDEX IF NOT EXISTS idx_fact_clip_label_run
          ON fact_clip_label (clip_id, run_id);

        CREATE TABLE IF NOT EXISTS fact_clip_embedding (
          clip_id TEXT NOT NULL,
          run_id TEXT NOT NULL,
          ds TEXT NOT NULL,
          vector_json TEXT NOT NULL,
          dim INTEGER NOT NULL,
          model_version TEXT,
          aggregation_method TEXT,
          created_at TEXT,
          updated_at TEXT,
          PRIMARY KEY (clip_id, run_id, ds)
        );
        CREATE INDEX IF NOT EXISTS idx_fact_clip_embedding_run
          ON fact_clip_embedding (clip_id, run_id);
        """
    )
    clip_label_cols = {row[1] for row in conn.execute("PRAGMA table_info(fact_clip_label)")}
    if "multi_ai_meta_json" not in clip_label_cols:
        conn.execute("ALTER TABLE fact_clip_label ADD COLUMN multi_ai_meta_json TEXT")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS pipeline_execution (
          run_id TEXT PRIMARY KEY,
          label TEXT NOT NULL,
          started_at TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """
    )
    from hmi.local.pipeline_execution import backfill_executions_from_runs

    backfill_executions_from_runs(conn)

    step_cols = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_step)")}
    if step_cols and "clip_id" not in step_cols:
        conn.executescript(
            """
            CREATE TABLE pipeline_step_new (
              run_id TEXT NOT NULL,
              clip_id TEXT NOT NULL DEFAULT '',
              ds TEXT NOT NULL,
              step_id TEXT NOT NULL,
              status TEXT,
              started_at TEXT,
              finished_at TEXT,
              error_message TEXT,
              PRIMARY KEY (run_id, clip_id, ds, step_id)
            );
            INSERT INTO pipeline_step_new (
              run_id, clip_id, ds, step_id, status, started_at, finished_at, error_message
            )
            SELECT s.run_id,
              COALESCE(
                (SELECT r.clip_id FROM pipeline_run r
                 WHERE r.run_id = s.run_id AND r.ds = s.ds LIMIT 1),
                ''
              ),
              s.ds, s.step_id, s.status, s.started_at, s.finished_at, s.error_message
            FROM pipeline_step s;
            DROP TABLE pipeline_step;
            ALTER TABLE pipeline_step_new RENAME TO pipeline_step;
            """
        )


def ensure_db() -> Path:
    LOCAL_ROOT.mkdir(parents=True, exist_ok=True)
    init = not LOCAL_DB_PATH.exists()
    conn = sqlite3.connect(LOCAL_DB_PATH)
    try:
        if init:
            conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
        else:
            _migrate_schema(conn)
        conn.commit()
    finally:
        conn.close()
    return LOCAL_DB_PATH


def _connect() -> sqlite3.Connection:
    ensure_db()
    conn = sqlite3.connect(LOCAL_DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def query(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> dict[str, Any] | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> None:
    conn = _connect()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def execute_rowcount(sql: str, params: tuple[Any, ...] | list[Any] = ()) -> int:
    conn = _connect()
    try:
        cur = conn.execute(sql, params)
        conn.commit()
        return int(cur.rowcount)
    finally:
        conn.close()


def executemany(sql: str, rows: list[tuple[Any, ...]]) -> None:
    if not rows:
        return
    conn = _connect()
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def set_meta(key: str, value: str) -> None:
    execute(
        "INSERT INTO sync_meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(key: str) -> str | None:
    row = query_one("SELECT value FROM sync_meta WHERE key=?", (key,))
    return str(row["value"]) if row else None


def clear_clip_data(clip_id: str, run_id: str, ds: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "DELETE FROM pipeline_step WHERE run_id=? AND clip_id=? AND ds=?",
            (run_id, clip_id, ds),
        )
        for tbl in (
            "pipeline_run",
            "clip_parse_summary",
            "fact_frame",
            "fact_event",
            "fact_audio_segment",
            "fact_image_label",
            "fact_embedding",
            "fact_clip_label",
            "fact_clip_embedding",
            "fact_sample_sync_group",
        ):
            conn.execute(
                f"DELETE FROM {tbl} WHERE clip_id=? AND run_id=? AND ds=?",
                (clip_id, run_id, ds),
            )
        conn.commit()
    finally:
        conn.close()
