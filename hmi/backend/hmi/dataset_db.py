"""Dataset snapshot persistence (SQLite app.db)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

DATASET_STATUSES = frozenset({"building", "ready", "failed", "archived"})
EXPORT_PRESETS = frozenset({"minimal", "full"})
AUGMENTATION_MODES = frozenset({"none", "oversample_only", "recipe_attached"})

DEFAULT_FEATURE_SPEC: dict[str, Any] = {
    "x": ["fact_clip_embedding", "fact_embedding"],
    "x_schema": ["clip_embedding_v1", "frame_embeddings_v1"],
}
DEFAULT_TARGET_SPEC: dict[str, Any] = {"y": ["clip_label_review.labels_json"]}

DEFAULT_FILTER: dict[str, Any] = {
    "review_status": "reviewed",
    "include_pending_review": False,
    "clip_ids": None,
    "taxonomy_version_id": None,
    "label_filters": None,
    "sample_size": None,
    "export_preset": "minimal",
    "balance_by_label": None,
    "min_per_class": None,
    "max_per_class": None,
    "oversample_policy": "none",
    "oversample_max_multiplier": 10,
}

_DATASET_SCHEMA = """
CREATE TABLE IF NOT EXISTS dataset_snapshot (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  status TEXT NOT NULL CHECK (status IN ('building','ready','failed','archived')),
  filter_json TEXT NOT NULL,
  clip_count INTEGER NOT NULL DEFAULT 0,
  feature_spec_json TEXT NOT NULL,
  target_spec_json TEXT NOT NULL,
  oss_manifest_uri TEXT,
  oss_x_uri TEXT,
  oss_y_uri TEXT,
  mc_table_name TEXT,
  error_message TEXT,
  created_by TEXT REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  ready_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_dataset_snapshot_status
  ON dataset_snapshot (status, updated_at DESC);
"""

_MIGRATION_COLUMNS: tuple[tuple[str, str], ...] = (
    ("export_preset", "TEXT NOT NULL DEFAULT 'minimal'"),
    ("build_report_json", "TEXT"),
    ("line_count", "INTEGER NOT NULL DEFAULT 0"),
    ("parent_snapshot_id", "TEXT"),
    ("derivation_json", "TEXT"),
    ("augmentation_mode", "TEXT NOT NULL DEFAULT 'none'"),
    ("aug_recipe_id", "TEXT"),
    ("schema_version", "TEXT"),
)


def ensure_dataset_schema() -> None:
    from hmi.app_db import APP_DB_PATH
    from hmi.dataset.aug_recipe_db import ensure_aug_recipe_schema

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_DATASET_SCHEMA)
        cols = {row[1] for row in conn.execute("PRAGMA table_info(dataset_snapshot)").fetchall()}
        if "oss_x_uri" not in cols:
            conn.execute("ALTER TABLE dataset_snapshot ADD COLUMN oss_x_uri TEXT")
        if "oss_y_uri" not in cols:
            conn.execute("ALTER TABLE dataset_snapshot ADD COLUMN oss_y_uri TEXT")
        for col_name, col_def in _MIGRATION_COLUMNS:
            if col_name not in cols:
                conn.execute(f"ALTER TABLE dataset_snapshot ADD COLUMN {col_name} {col_def}")
        conn.commit()
    ensure_aug_recipe_schema()


def _dump_json(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _load_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _snapshot_row(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "status": row["status"],
        "filter_json": _load_json(row["filter_json"]),
        "clip_count": int(row["clip_count"]),
        "line_count": int(row["line_count"]) if "line_count" in keys and row["line_count"] is not None else int(row["clip_count"]),
        "feature_spec_json": _load_json(row["feature_spec_json"]),
        "target_spec_json": _load_json(row["target_spec_json"]),
        "oss_manifest_uri": row["oss_manifest_uri"],
        "oss_x_uri": row["oss_x_uri"] if "oss_x_uri" in keys else None,
        "oss_y_uri": row["oss_y_uri"] if "oss_y_uri" in keys else None,
        "mc_table_name": row["mc_table_name"],
        "error_message": row["error_message"],
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "ready_at": row["ready_at"],
        "export_preset": row["export_preset"] if "export_preset" in keys else "minimal",
        "build_report": _load_json(row["build_report_json"]) if "build_report_json" in keys else None,
        "parent_snapshot_id": row["parent_snapshot_id"] if "parent_snapshot_id" in keys else None,
        "derivation_json": _load_json(row["derivation_json"]) if "derivation_json" in keys else None,
        "augmentation_mode": row["augmentation_mode"] if "augmentation_mode" in keys else "none",
        "aug_recipe_id": row["aug_recipe_id"] if "aug_recipe_id" in keys else None,
        "schema_version": row["schema_version"] if "schema_version" in keys else None,
    }


def create_snapshot(
    name: str,
    *,
    description: str | None = None,
    filter_json: dict[str, Any] | str | None = None,
    feature_spec_json: dict[str, Any] | str | None = None,
    target_spec_json: dict[str, Any] | str | None = None,
    status: str = "building",
    created_by: str | None = None,
    export_preset: str = "minimal",
    parent_snapshot_id: str | None = None,
    derivation_json: dict[str, Any] | str | None = None,
    augmentation_mode: str = "none",
    aug_recipe_id: str | None = None,
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("name required")
    if status not in DATASET_STATUSES:
        raise ValueError(f"invalid status: {status}")
    preset = str(export_preset or "minimal").strip()
    if preset not in EXPORT_PRESETS:
        raise ValueError(f"invalid export_preset: {preset}")
    aug_mode = str(augmentation_mode or "none").strip()
    if aug_mode not in AUGMENTATION_MODES:
        raise ValueError(f"invalid augmentation_mode: {aug_mode}")

    snapshot_id = str(uuid.uuid4())
    now = _utc_now_iso()
    resolved_filter = filter_json if filter_json is not None else DEFAULT_FILTER
    resolved_feature = feature_spec_json if feature_spec_json is not None else DEFAULT_FEATURE_SPEC
    resolved_target = target_spec_json if target_spec_json is not None else DEFAULT_TARGET_SPEC

    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO dataset_snapshot (
              id, name, description, status, filter_json, clip_count, line_count,
              feature_spec_json, target_spec_json, oss_manifest_uri, mc_table_name,
              error_message, created_by, created_at, updated_at, ready_at,
              export_preset, build_report_json, parent_snapshot_id, derivation_json,
              augmentation_mode, aug_recipe_id
            ) VALUES (?, ?, ?, ?, ?, 0, 0, ?, ?, NULL, NULL, NULL, ?, ?, ?, NULL,
                      ?, NULL, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                name,
                description,
                status,
                _dump_json(resolved_filter),
                _dump_json(resolved_feature),
                _dump_json(resolved_target),
                created_by,
                now,
                now,
                preset,
                parent_snapshot_id,
                _dump_json(derivation_json) if derivation_json is not None else None,
                aug_mode,
                aug_recipe_id,
            ),
        )

    snapshot = get_snapshot(snapshot_id)
    assert snapshot is not None
    return snapshot


def get_snapshot(snapshot_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dataset_snapshot WHERE id = ?",
            (snapshot_id.strip(),),
        ).fetchone()
        return _snapshot_row(row) if row else None


def list_snapshots(
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with db_conn() as conn:
        if status:
            if status not in DATASET_STATUSES:
                raise ValueError(f"invalid status: {status}")
            rows = conn.execute(
                """
                SELECT * FROM dataset_snapshot
                WHERE status = ?
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM dataset_snapshot
                WHERE status != 'archived'
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [_snapshot_row(r) for r in rows]


def count_snapshots(*, status: str | None = None, include_archived: bool = False) -> int:
    with db_conn() as conn:
        if status:
            if status not in DATASET_STATUSES:
                raise ValueError(f"invalid status: {status}")
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM dataset_snapshot WHERE status = ?",
                (status,),
            ).fetchone()
        elif include_archived:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM dataset_snapshot").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM dataset_snapshot WHERE status != 'archived'"
            ).fetchone()
    return int(row["cnt"]) if row else 0


def update_snapshot(
    snapshot_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    status: str | None = None,
    filter_json: dict[str, Any] | str | None = None,
    clip_count: int | None = None,
    line_count: int | None = None,
    feature_spec_json: dict[str, Any] | str | None = None,
    target_spec_json: dict[str, Any] | str | None = None,
    oss_manifest_uri: str | None = None,
    oss_x_uri: str | None = None,
    oss_y_uri: str | None = None,
    mc_table_name: str | None = None,
    error_message: str | None = None,
    ready_at: str | None = None,
    clear_error: bool = False,
    export_preset: str | None = None,
    build_report: dict[str, Any] | str | None = None,
    parent_snapshot_id: str | None = None,
    derivation_json: dict[str, Any] | str | None = None,
    augmentation_mode: str | None = None,
    aug_recipe_id: str | None = None,
    schema_version: str | None = None,
) -> dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM dataset_snapshot WHERE id = ?",
            (snapshot_id.strip(),),
        ).fetchone()
        if row is None:
            raise ValueError(f"snapshot not found: {snapshot_id}")

        keys = row.keys()
        if status is not None and status not in DATASET_STATUSES:
            raise ValueError(f"invalid status: {status}")

        now = _utc_now_iso()
        new_name = name.strip() if name is not None else row["name"]
        if not new_name:
            raise ValueError("name required")

        new_description = description if description is not None else row["description"]
        new_status = status if status is not None else row["status"]
        new_filter = _dump_json(filter_json) if filter_json is not None else row["filter_json"]
        new_clip_count = clip_count if clip_count is not None else int(row["clip_count"])
        if line_count is not None:
            new_line_count = line_count
        elif "line_count" in keys:
            new_line_count = int(row["line_count"])
        else:
            new_line_count = new_clip_count
        new_feature = (
            _dump_json(feature_spec_json)
            if feature_spec_json is not None
            else row["feature_spec_json"]
        )
        new_target = (
            _dump_json(target_spec_json)
            if target_spec_json is not None
            else row["target_spec_json"]
        )
        if oss_manifest_uri is not None:
            new_oss = oss_manifest_uri or None
        else:
            new_oss = row["oss_manifest_uri"]
        if oss_x_uri is not None:
            new_x = oss_x_uri or None
        else:
            new_x = row["oss_x_uri"] if "oss_x_uri" in keys else None
        if oss_y_uri is not None:
            new_y = oss_y_uri or None
        else:
            new_y = row["oss_y_uri"] if "oss_y_uri" in keys else None
        if mc_table_name is not None:
            new_mc = mc_table_name or None
        else:
            new_mc = row["mc_table_name"]
        if clear_error:
            new_error = None
        elif error_message is not None:
            new_error = error_message
        else:
            new_error = row["error_message"]

        if ready_at is not None:
            new_ready_at = ready_at
        elif status == "ready" and row["status"] != "ready":
            new_ready_at = now
        else:
            new_ready_at = row["ready_at"]

        if export_preset is not None:
            preset = str(export_preset).strip()
            if preset not in EXPORT_PRESETS:
                raise ValueError(f"invalid export_preset: {preset}")
            new_export_preset = preset
        else:
            new_export_preset = row["export_preset"] if "export_preset" in keys else "minimal"

        if build_report is not None:
            new_build_report = _dump_json(build_report)
        else:
            new_build_report = row["build_report_json"] if "build_report_json" in keys else None

        if parent_snapshot_id is not None:
            new_parent = parent_snapshot_id or None
        else:
            new_parent = row["parent_snapshot_id"] if "parent_snapshot_id" in keys else None

        if derivation_json is not None:
            new_derivation = _dump_json(derivation_json)
        else:
            new_derivation = row["derivation_json"] if "derivation_json" in keys else None

        if augmentation_mode is not None:
            aug_mode = str(augmentation_mode).strip()
            if aug_mode not in AUGMENTATION_MODES:
                raise ValueError(f"invalid augmentation_mode: {aug_mode}")
            new_augmentation_mode = aug_mode
        else:
            new_augmentation_mode = row["augmentation_mode"] if "augmentation_mode" in keys else "none"

        if aug_recipe_id is not None:
            new_aug_recipe_id = aug_recipe_id or None
        else:
            new_aug_recipe_id = row["aug_recipe_id"] if "aug_recipe_id" in keys else None

        if schema_version is not None:
            new_schema_version = schema_version or None
        else:
            new_schema_version = row["schema_version"] if "schema_version" in keys else None

        conn.execute(
            """
            UPDATE dataset_snapshot
            SET name = ?, description = ?, status = ?, filter_json = ?,
                clip_count = ?, line_count = ?, feature_spec_json = ?, target_spec_json = ?,
                oss_manifest_uri = ?, oss_x_uri = ?, oss_y_uri = ?, mc_table_name = ?,
                error_message = ?, updated_at = ?, ready_at = ?,
                export_preset = ?, build_report_json = ?, parent_snapshot_id = ?,
                derivation_json = ?, augmentation_mode = ?, aug_recipe_id = ?,
                schema_version = ?
            WHERE id = ?
            """,
            (
                new_name,
                new_description,
                new_status,
                new_filter,
                new_clip_count,
                new_line_count,
                new_feature,
                new_target,
                new_oss,
                new_x,
                new_y,
                new_mc,
                new_error,
                now,
                new_ready_at,
                new_export_preset,
                new_build_report,
                new_parent,
                new_derivation,
                new_augmentation_mode,
                new_aug_recipe_id,
                new_schema_version,
                snapshot_id.strip(),
            ),
        )

    snapshot = get_snapshot(snapshot_id)
    assert snapshot is not None
    return snapshot
