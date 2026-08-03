"""Augmentation recipe registry (platform stores spec only; no transform execution)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn

RECIPE_STATUSES = frozenset({"draft", "published", "archived"})

_AUG_RECIPE_SCHEMA = """
CREATE TABLE IF NOT EXISTS aug_recipe (
  id TEXT PRIMARY KEY,
  recipe_code TEXT NOT NULL,
  version INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('draft','published','archived')),
  spec_json TEXT NOT NULL,
  created_by TEXT REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (recipe_code, version)
);

CREATE INDEX IF NOT EXISTS idx_aug_recipe_status
  ON aug_recipe (status, updated_at DESC);
"""


def ensure_aug_recipe_schema() -> None:
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_AUG_RECIPE_SCHEMA)
        conn.commit()


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


def _recipe_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "recipe_code": row["recipe_code"],
        "version": int(row["version"]),
        "status": row["status"],
        "spec_json": _load_json(row["spec_json"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_recipe(
    recipe_code: str,
    spec_json: dict[str, Any] | str,
    *,
    version: int | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    code = recipe_code.strip()
    if not code:
        raise ValueError("recipe_code required")
    with db_conn() as conn:
        if version is None:
            row = conn.execute(
                "SELECT MAX(version) AS mv FROM aug_recipe WHERE recipe_code = ?",
                (code,),
            ).fetchone()
            version = int(row["mv"] or 0) + 1
        recipe_id = str(uuid.uuid4())
        now = _utc_now_iso()
        conn.execute(
            """
            INSERT INTO aug_recipe (
              id, recipe_code, version, status, spec_json, created_by, created_at, updated_at
            ) VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)
            """,
            (recipe_id, code, int(version), _dump_json(spec_json), created_by, now, now),
        )
    recipe = get_recipe(recipe_id)
    assert recipe is not None
    return recipe


def get_recipe(recipe_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM aug_recipe WHERE id = ?",
            (recipe_id.strip(),),
        ).fetchone()
        return _recipe_row(row) if row else None


def list_recipes(
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    with db_conn() as conn:
        if status:
            if status not in RECIPE_STATUSES:
                raise ValueError(f"invalid status: {status}")
            rows = conn.execute(
                """
                SELECT * FROM aug_recipe WHERE status = ?
                ORDER BY updated_at DESC LIMIT ? OFFSET ?
                """,
                (status, limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM aug_recipe WHERE status != 'archived'
                ORDER BY updated_at DESC LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
    return [_recipe_row(r) for r in rows]


def publish_recipe(recipe_id: str) -> dict[str, Any]:
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM aug_recipe WHERE id = ?",
            (recipe_id.strip(),),
        ).fetchone()
        if row is None:
            raise ValueError(f"recipe not found: {recipe_id}")
        if row["status"] != "draft":
            raise ValueError(f"only draft recipes can be published (current: {row['status']})")
        now = _utc_now_iso()
        conn.execute(
            "UPDATE aug_recipe SET status = 'published', updated_at = ? WHERE id = ?",
            (now, recipe_id.strip()),
        )
    recipe = get_recipe(recipe_id)
    assert recipe is not None
    return recipe


def get_published_recipe(recipe_id: str) -> dict[str, Any]:
    recipe = get_recipe(recipe_id)
    if recipe is None:
        raise ValueError(f"recipe not found: {recipe_id}")
    if recipe["status"] != "published":
        raise ValueError(f"recipe not published: {recipe_id}")
    return recipe
