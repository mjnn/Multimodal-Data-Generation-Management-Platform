"""Taxonomy version + node persistence (SQLite app.db)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

TAXONOMY_STATUSES = frozenset({"draft", "published", "archived"})


_TAXONOMY_SCHEMA = """
CREATE TABLE IF NOT EXISTS label_taxonomy_version (
  id TEXT PRIMARY KEY,
  version_code TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (status IN ('draft','published','archived')),
  published_at TEXT,
  created_by TEXT REFERENCES app_user(id),
  source_import TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS label_taxonomy_node (
  id TEXT PRIMARY KEY,
  taxonomy_version_id TEXT NOT NULL REFERENCES label_taxonomy_version(id),
  parent_id TEXT REFERENCES label_taxonomy_node(id),
  level_code TEXT NOT NULL,
  level_name TEXT,
  label_id TEXT NOT NULL,
  name TEXT NOT NULL,
  definition TEXT,
  dtype TEXT,
  value_schema_json TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  is_active INTEGER NOT NULL DEFAULT 1,
  UNIQUE(taxonomy_version_id, label_id)
);

CREATE INDEX IF NOT EXISTS idx_taxonomy_node_version
  ON label_taxonomy_node (taxonomy_version_id, sort_order);
"""


def _migrate_taxonomy_archive_reason(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(label_taxonomy_version)")}
    if "archive_reason" in cols:
        return
    conn.execute(
        "ALTER TABLE label_taxonomy_version ADD COLUMN archive_reason TEXT"
    )
    conn.execute(
        """
        UPDATE label_taxonomy_version
        SET archive_reason = 'superseded'
        WHERE status = 'archived'
          AND published_at IS NOT NULL
          AND archive_reason IS NULL
        """
    )
    conn.execute(
        """
        UPDATE label_taxonomy_version
        SET archive_reason = 'user'
        WHERE status = 'archived'
          AND published_at IS NULL
          AND archive_reason IS NULL
        """
    )


def ensure_taxonomy_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_TAXONOMY_SCHEMA)
        _migrate_taxonomy_archive_reason(conn)
        conn.commit()


def _version_row(row: sqlite3.Row) -> dict[str, Any]:
    keys = row.keys()
    archive_reason = row["archive_reason"] if "archive_reason" in keys else None
    return {
        "id": row["id"],
        "version_code": row["version_code"],
        "status": row["status"],
        "published_at": row["published_at"],
        "archive_reason": archive_reason,
        "created_by": row["created_by"],
        "source_import": row["source_import"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _enrich_node_value_schema(value_schema: Any) -> Any:
    if not isinstance(value_schema, dict):
        return value_schema
    try:
        from shared.taxonomy_i18n import enrich_value_schema

        return enrich_value_schema(value_schema)
    except ImportError:
        return value_schema


def _node_row(row: sqlite3.Row) -> dict[str, Any]:
    value_schema = None
    raw = row["value_schema_json"]
    if raw:
        try:
            value_schema = json.loads(raw)
        except json.JSONDecodeError:
            value_schema = raw
    value_schema = _enrich_node_value_schema(value_schema)
    return {
        "id": row["id"],
        "taxonomy_version_id": row["taxonomy_version_id"],
        "parent_id": row["parent_id"],
        "level_code": row["level_code"],
        "level_name": row["level_name"],
        "label_id": row["label_id"],
        "name": row["name"],
        "definition": row["definition"],
        "dtype": row["dtype"],
        "value_schema": value_schema,
        "value_schema_json": raw,
        "sort_order": row["sort_order"],
        "is_active": bool(row["is_active"]),
    }


def create_version(
    version_code: str,
    *,
    status: str = "draft",
    created_by: str | None = None,
    source_import: str | None = None,
) -> dict[str, Any]:
    version_code = version_code.strip()
    if not version_code:
        raise ValueError("version_code required")
    if status not in TAXONOMY_STATUSES:
        raise ValueError(f"invalid status: {status}")

    version_id = str(uuid.uuid4())
    now = _utc_now_iso()
    with db_conn() as conn:
        dup = conn.execute(
            "SELECT 1 FROM label_taxonomy_version WHERE version_code = ?",
            (version_code,),
        ).fetchone()
        if dup:
            raise ValueError(f"version_code already exists: {version_code}")

        conn.execute(
            """
            INSERT INTO label_taxonomy_version
              (id, version_code, status, published_at, created_by, source_import, created_at, updated_at)
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
            """,
            (version_id, version_code, status, created_by, source_import, now, now),
        )

    version = get_version(version_id)
    assert version is not None
    return version


def get_version(version_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM label_taxonomy_version WHERE id = ?",
            (version_id,),
        ).fetchone()
        return _version_row(row) if row else None


def get_version_by_code(version_code: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM label_taxonomy_version WHERE version_code = ?",
            (version_code.strip(),),
        ).fetchone()
        return _version_row(row) if row else None


def version_codes_by_ids(version_ids: set[str] | list[str]) -> dict[str, str]:
    """Map taxonomy version UUID -> version_code (batch, app.db)."""
    ids = sorted({str(i).strip() for i in version_ids if i and str(i).strip()})
    if not ids:
        return {}
    placeholders = ",".join("?" * len(ids))
    with db_conn() as conn:
        rows = conn.execute(
            f"SELECT id, version_code FROM label_taxonomy_version WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    return {str(r["id"]): str(r["version_code"]) for r in rows}


def list_versions(
    *,
    status: str | None = None,
    include_archived: bool = False,
) -> list[dict[str, Any]]:
    with db_conn() as conn:
        if status:
            rows = conn.execute(
                """
                SELECT * FROM label_taxonomy_version
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (status,),
            ).fetchall()
        elif include_archived:
            rows = conn.execute(
                "SELECT * FROM label_taxonomy_version ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM label_taxonomy_version
                WHERE status != 'archived'
                   OR archive_reason = 'superseded'
                ORDER BY created_at DESC
                """
            ).fetchall()
        return [_version_row(r) for r in rows]


def list_pipeline_taxonomy_versions() -> list[dict[str, Any]]:
    """Versions selectable for pipeline Job3 (draft, current published, historical published)."""
    return list_versions()


def get_published_version() -> dict[str, Any] | None:
    versions = list_versions(status="published")
    return versions[0] if versions else None


def taxonomy_version_display_label(version: dict[str, Any]) -> str:
    """Human-readable label for UI (version_code + status hint)."""
    code = str(version.get("version_code") or "").strip() or "—"
    status = str(version.get("status") or "")
    reason = version.get("archive_reason")
    if status == "published" or (status == "archived" and reason == "superseded"):
        return f"{code}（已发布）"
    if status == "draft":
        return f"{code}（草稿）"
    if status == "archived":
        return f"{code}（已归档）"
    return code


def resolve_taxonomy_display_for_version_id(version_id: str | None) -> str | None:
    if not version_id or not str(version_id).strip():
        return None
    tid = str(version_id).strip()
    version = get_version(tid)
    if version:
        return taxonomy_version_display_label(version)
    codes = version_codes_by_ids([tid])
    code = codes.get(tid)
    if code:
        return code
    return None


def require_draft_version(version_id: str, conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM label_taxonomy_version WHERE id = ?",
        (version_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"taxonomy version not found: {version_id}")
    if row["status"] != "draft":
        raise ValueError(f"taxonomy version is not draft: {row['status']}")
    return row


def list_nodes(
    version_id: str,
    *,
    active_only: bool = True,
) -> list[dict[str, Any]]:
    with db_conn() as conn:
        if active_only:
            rows = conn.execute(
                """
                SELECT * FROM label_taxonomy_node
                WHERE taxonomy_version_id = ? AND is_active = 1
                ORDER BY sort_order, label_id
                """,
                (version_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM label_taxonomy_node
                WHERE taxonomy_version_id = ?
                ORDER BY sort_order, label_id
                """,
                (version_id,),
            ).fetchall()
        return [_node_row(r) for r in rows]


def count_nodes(version_id: str) -> int:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM label_taxonomy_node WHERE taxonomy_version_id = ?",
            (version_id,),
        ).fetchone()
        return int(row["c"]) if row else 0


def replace_nodes(version_id: str, nodes: list[dict[str, Any]]) -> int:
    """Replace all nodes for a draft version. Returns inserted count."""
    if not nodes:
        raise ValueError("nodes list must not be empty")

    label_ids = [str(n.get("label_id") or "") for n in nodes]
    if any(not lid for lid in label_ids):
        raise ValueError("each node requires label_id")
    if len(set(label_ids)) != len(label_ids):
        raise ValueError("duplicate label_id in nodes batch")

    with db_conn() as conn:
        require_draft_version(version_id, conn)
        conn.execute(
            "DELETE FROM label_taxonomy_node WHERE taxonomy_version_id = ?",
            (version_id,),
        )
        now = _utc_now_iso()
        conn.execute(
            "UPDATE label_taxonomy_version SET updated_at = ? WHERE id = ?",
            (now, version_id),
        )

        for idx, node in enumerate(nodes):
            value_schema = node.get("value_schema")
            if value_schema is None and node.get("value_schema_json") is not None:
                value_schema_json = node["value_schema_json"]
                if isinstance(value_schema_json, str):
                    value_schema_json = value_schema_json
                else:
                    value_schema_json = json.dumps(value_schema_json, ensure_ascii=False)
            elif value_schema is not None:
                value_schema_json = json.dumps(value_schema, ensure_ascii=False)
            else:
                value_schema_json = None

            conn.execute(
                """
                INSERT INTO label_taxonomy_node (
                  id, taxonomy_version_id, parent_id, level_code, level_name,
                  label_id, name, definition, dtype, value_schema_json,
                  sort_order, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(node.get("id") or uuid.uuid4()),
                    version_id,
                    node.get("parent_id"),
                    str(node.get("level_code") or "other"),
                    node.get("level_name"),
                    str(node["label_id"]),
                    str(node.get("name") or node["label_id"]),
                    node.get("definition"),
                    node.get("dtype"),
                    value_schema_json,
                    int(node.get("sort_order", idx)),
                    1 if node.get("is_active", True) else 0,
                ),
            )

    return len(nodes)


def clone_nodes(source_version_id: str, target_version_id: str) -> int:
    nodes = list_nodes(source_version_id, active_only=False)
    if not nodes:
        return 0
    payload = []
    for n in nodes:
        payload.append(
            {
                "parent_id": n["parent_id"],
                "level_code": n["level_code"],
                "level_name": n["level_name"],
                "label_id": n["label_id"],
                "name": n["name"],
                "definition": n["definition"],
                "dtype": n["dtype"],
                "value_schema": n["value_schema"],
                "sort_order": n["sort_order"],
                "is_active": n["is_active"],
            }
        )
    return replace_nodes(target_version_id, payload)


def publish_version(version_id: str) -> dict[str, Any]:
    """Promote draft → published; archive any existing published version."""
    now = _utc_now_iso()
    with db_conn() as conn:
        require_draft_version(version_id, conn)
        conn.execute(
            """
            UPDATE label_taxonomy_version
            SET status = 'archived', archive_reason = 'superseded', updated_at = ?
            WHERE status = 'published'
            """,
            (now,),
        )
        conn.execute(
            """
            UPDATE label_taxonomy_version
            SET status = 'published', published_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, version_id),
        )

    version = get_version(version_id)
    assert version is not None
    return version


def update_version_source_import(version_id: str, source_import: str) -> None:
    now = _utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            UPDATE label_taxonomy_version
            SET source_import = ?, updated_at = ?
            WHERE id = ?
            """,
            (source_import, now, version_id),
        )


def archive_version(version_id: str) -> dict[str, Any]:
    now = _utc_now_iso()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM label_taxonomy_version WHERE id = ?",
            (version_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"taxonomy version not found: {version_id}")
        if row["status"] == "archived":
            raise ValueError("taxonomy version already archived")
        conn.execute(
            """
            UPDATE label_taxonomy_version
            SET status = 'archived', archive_reason = 'user', updated_at = ?
            WHERE id = ?
            """,
            (now, version_id),
        )

    version = get_version(version_id)
    assert version is not None
    return version


def clone_version(
    source_version_id: str,
    version_code: str,
    *,
    created_by: str | None = None,
) -> dict[str, Any]:
    source = get_version(source_version_id)
    if source is None:
        raise ValueError(f"taxonomy version not found: {source_version_id}")

    version_code = version_code.strip()
    if not version_code:
        raise ValueError("version_code required")

    target = create_version(
        version_code,
        created_by=created_by,
        source_import=f"clone:{source_version_id}",
    )
    clone_nodes(source_version_id, target["id"])
    cloned = get_version(target["id"])
    assert cloned is not None
    return cloned
