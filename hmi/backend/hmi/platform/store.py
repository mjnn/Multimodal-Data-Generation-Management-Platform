"""平台内核 SQLite（写入 app.db）。

表：platform_source / sample / sample_source / data_type / run / product。
配方种子与校验走 recipe.py；开跑多选绑定走 run_bind / create_run_from_sources。
产物 cache_key = 输入 + 算子 + 参数，供血缘查询。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

from hmi.app_db import _utc_now_iso, db_conn
from hmi.platform.cache import product_cache_key
from hmi.platform.file_kinds import modality_of, resolve_source_kind
from hmi.platform.operators import SOURCE_KINDS, get_operator
from hmi.platform.preflight import preflight
from hmi.platform.recipe import (
    AUDIO_DEFECT_VERSION_CODE,
    SEED_DATA_TYPE_IDS,
    eligible_kinds_for_recipe,
    seed_recipes,
    validate_recipe,
)

_PLATFORM_SCHEMA = """
CREATE TABLE IF NOT EXISTS platform_source (
  source_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  filename TEXT,
  text_schema_id TEXT,
  content_hash TEXT,
  local_oss_key TEXT,
  local_path TEXT,
  collection_id TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_sample (
  sample_id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_sample_source (
  sample_id TEXT NOT NULL REFERENCES platform_sample(sample_id),
  source_id TEXT NOT NULL REFERENCES platform_source(source_id),
  PRIMARY KEY (sample_id, source_id)
);

CREATE TABLE IF NOT EXISTS platform_data_type (
  id TEXT PRIMARY KEY,
  recipe_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_run (
  run_id TEXT PRIMARY KEY,
  sample_id TEXT NOT NULL REFERENCES platform_sample(sample_id),
  data_type_id TEXT NOT NULL,
  taxonomy_id TEXT NOT NULL,
  taxonomy_version_id TEXT,
  status TEXT NOT NULL,
  y_json TEXT,
  preflight_json TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_run_sample_type
  ON platform_run (sample_id, data_type_id);

CREATE TABLE IF NOT EXISTS platform_product (
  cache_key TEXT PRIMARY KEY,
  op_id TEXT NOT NULL,
  input_ids_json TEXT NOT NULL,
  params_json TEXT NOT NULL,
  artifact_path TEXT,
  run_id TEXT,
  skipped INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""

TEXT_SCHEMAS = (
    {"schema_id": "generic_json", "title": "通用 JSON"},
    {"schema_id": "generic_text", "title": "通用文本（包一层 raw）"},
)


def _row_recipe(row: sqlite3.Row) -> dict[str, Any]:
    rec = json.loads(row["recipe_json"])
    if not isinstance(rec, dict):
        return rec
    try:
        from hmi.platform.recipe_graph import hydrate_graph

        rec["graph"] = hydrate_graph(rec)
    except (ValueError, TypeError, KeyError):
        pass
    return rec


def ensure_platform_schema() -> None:
    """Create platform tables. Must not call db_conn() (ensure_schema re-entry)."""
    from hmi.app_db import APP_DB_PATH

    APP_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.executescript(_PLATFORM_SCHEMA)
        src_cols = {row[1] for row in conn.execute("PRAGMA table_info(platform_source)")}
        for name, ddl in (
            ("content_hash", "ALTER TABLE platform_source ADD COLUMN content_hash TEXT"),
            ("local_oss_key", "ALTER TABLE platform_source ADD COLUMN local_oss_key TEXT"),
            ("local_path", "ALTER TABLE platform_source ADD COLUMN local_path TEXT"),
            ("collection_id", "ALTER TABLE platform_source ADD COLUMN collection_id TEXT"),
        ):
            if src_cols and name not in src_cols:
                conn.execute(ddl)
        prod_cols = {row[1] for row in conn.execute("PRAGMA table_info(platform_product)")}
        for name, ddl in (
            ("artifact_path", "ALTER TABLE platform_product ADD COLUMN artifact_path TEXT"),
            ("run_id", "ALTER TABLE platform_product ADD COLUMN run_id TEXT"),
        ):
            if prod_cols and name not in prod_cols:
                conn.execute(ddl)
        # Backfill missing collection_id to source_id (each source is its own batch).
        conn.execute(
            """
            UPDATE platform_source
            SET collection_id = source_id
            WHERE collection_id IS NULL OR TRIM(collection_id) = ''
            """
        )
        _seed_builtin_data_types(conn)
        _seed_ivi_taxonomy(conn)
        _seed_audio_nvh_taxonomy(conn)
        _seed_audio_defect_taxonomy(conn)
        conn.commit()


def _seed_builtin_data_types(conn: sqlite3.Connection) -> None:
    now = _utc_now_iso()
    for recipe in seed_recipes().values():
        conn.execute(
            """
            INSERT INTO platform_data_type (id, recipe_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              recipe_json = excluded.recipe_json,
              updated_at = excluded.updated_at
            """,
            (recipe["id"], json.dumps(recipe, ensure_ascii=False), now),
        )


def _seed_ivi_taxonomy(conn: sqlite3.Connection) -> None:
    """Draft tree for ivi_ui_stub. Do not publish (would archive OMS published)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='label_taxonomy_version'"
    ).fetchone()
    if exists is None:
        return
    if conn.execute(
        "SELECT 1 FROM label_taxonomy_version WHERE version_code = ?",
        ("ivi_ui_stub-v1",),
    ).fetchone():
        return
    now = _utc_now_iso()
    version_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO label_taxonomy_version
          (id, version_code, status, published_at, created_by, source_import, created_at, updated_at)
        VALUES (?, ?, 'draft', NULL, NULL, 'platform-kernel-seed', ?, ?)
        """,
        (version_id, "ivi_ui_stub-v1", now, now),
    )
    for idx, node in enumerate(
        (
            ("ivi.control", "控件"),
            ("ivi.screen", "界面"),
        )
    ):
        conn.execute(
            """
            INSERT INTO label_taxonomy_node (
              id, taxonomy_version_id, parent_id, level_code, level_name,
              label_id, name, definition, dtype, value_schema_json, sort_order, is_active
            ) VALUES (?, ?, NULL, 'domain', NULL, ?, ?, NULL, 'enum_tree', NULL, ?, 1)
            """,
            (str(uuid.uuid4()), version_id, node[0], node[1], idx),
        )


def _seed_audio_nvh_taxonomy(conn: sqlite3.Connection) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='label_taxonomy_version'"
    ).fetchone()
    if exists is None:
        return
    now = _utc_now_iso()
    if not conn.execute(
        "SELECT 1 FROM label_taxonomy_version WHERE version_code = ?",
        ("audio_nvh-v1",),
    ).fetchone():
        version_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO label_taxonomy_version
              (id, version_code, status, published_at, created_by, source_import, created_at, updated_at)
            VALUES (?, ?, 'draft', NULL, NULL, 'platform-kernel-seed', ?, ?)
            """,
            (version_id, "audio_nvh-v1", now, now),
        )
        for idx, node in enumerate(
            (
                ("nvh.spl", "声压级"),
                ("nvh.band", "频带"),
                ("nvh.channel", "通道"),
            )
        ):
            conn.execute(
                """
                INSERT INTO label_taxonomy_node (
                  id, taxonomy_version_id, parent_id, level_code, level_name,
                  label_id, name, definition, dtype, value_schema_json, sort_order, is_active
                ) VALUES (?, ?, NULL, 'domain', NULL, ?, ?, NULL, 'enum_tree', NULL, ?, 1)
                """,
                (str(uuid.uuid4()), version_id, node[0], node[1], idx),
            )
    if conn.execute(
        "SELECT 1 FROM label_taxonomy_version WHERE version_code = ?",
        ("audio_nvh-v2",),
    ).fetchone():
        return
    from hmi.platform.audio_nvh_v2 import VERSION_CODE, yaml_labels_for_import
    from hmi.taxonomy_import import yaml_labels_to_nodes

    version_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO label_taxonomy_version
          (id, version_code, status, published_at, created_by, source_import, created_at, updated_at)
        VALUES (?, ?, 'draft', NULL, NULL, 'TAX-AUDIO-NVH-v2', ?, ?)
        """,
        (version_id, VERSION_CODE, now, now),
    )
    for node in yaml_labels_to_nodes(yaml_labels_for_import()):
        schema = node.get("value_schema")
        conn.execute(
            """
            INSERT INTO label_taxonomy_node (
              id, taxonomy_version_id, parent_id, level_code, level_name,
              label_id, name, definition, dtype, value_schema_json, sort_order, is_active
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                str(uuid.uuid4()),
                version_id,
                node["level_code"],
                node.get("level_name"),
                node["label_id"],
                node["name"],
                node.get("definition"),
                node.get("dtype"),
                json.dumps(schema, ensure_ascii=False) if schema is not None else None,
                int(node.get("sort_order") or 0),
            ),
        )


def _seed_audio_defect_taxonomy(conn: sqlite3.Connection) -> None:
    """Draft bool tree for audio_defect. Do not publish (would archive OMS published)."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='label_taxonomy_version'"
    ).fetchone()
    if exists is None:
        return
    if conn.execute(
        "SELECT 1 FROM label_taxonomy_version WHERE version_code = ?",
        (AUDIO_DEFECT_VERSION_CODE,),
    ).fetchone():
        return
    now = _utc_now_iso()
    version_id = str(uuid.uuid4())
    conn.execute(
        """
        INSERT INTO label_taxonomy_version
          (id, version_code, status, published_at, created_by, source_import, created_at, updated_at)
        VALUES (?, ?, 'draft', NULL, NULL, 'platform-kernel-seed', ?, ?)
        """,
        (version_id, AUDIO_DEFECT_VERSION_CODE, now, now),
    )
    schema = {"type": "bool", "values": ["true", "false"]}
    conn.execute(
        """
        INSERT INTO label_taxonomy_node (
          id, taxonomy_version_id, parent_id, level_code, level_name,
          label_id, name, definition, dtype, value_schema_json, sort_order, is_active
        ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            str(uuid.uuid4()),
            version_id,
            "L1",
            "片段判定",
            "audio.defect.has_problem",
            "是否有问题音频",
            "这段录音是否存在问题噪音（异响 / 异常噪声）。true=有问题，false=正常。",
            "bool",
            json.dumps(schema, ensure_ascii=False),
            0,
        ),
    )


def reset_platform_kernel_to_seeds(conn: sqlite3.Connection) -> dict[str, Any]:
    """Wipe lake/sample/run/product rows, drop extra DataTypes, re-seed builtins.

    Does not commit. Does not touch OSS files (caller clears ``sources/`` etc.).
    Re-inserts draft IVI / audio_nvh / audio_defect taxonomies if those tables exist.
    """
    counts: dict[str, int] = {}
    extra_ids: list[str] = []
    tables = (
        "platform_product",
        "platform_run",
        "platform_sample_source",
        "platform_sample",
        "platform_source",
    )
    for table in tables:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
            n = int(row[0]) if row else 0
        except sqlite3.OperationalError:
            n = 0
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass
        counts[table] = n

    try:
        placeholders = ",".join("?" * len(SEED_DATA_TYPE_IDS))
        extra_ids = [
            str(r[0])
            for r in conn.execute(
                f"SELECT id FROM platform_data_type WHERE id NOT IN ({placeholders})",
                SEED_DATA_TYPE_IDS,
            ).fetchall()
        ]
        conn.execute("DELETE FROM platform_data_type")
    except sqlite3.OperationalError:
        extra_ids = []

    _seed_builtin_data_types(conn)
    _seed_ivi_taxonomy(conn)
    _seed_audio_nvh_taxonomy(conn)
    _seed_audio_defect_taxonomy(conn)
    return {
        "sqlite_rows_removed": counts,
        "extra_data_types_removed": extra_ids,
        "seeded_data_type_ids": list(SEED_DATA_TYPE_IDS),
    }


def list_data_types() -> list[dict[str, Any]]:
    ensure_platform_schema()
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_json FROM platform_data_type ORDER BY id"
        ).fetchall()
    return [_row_recipe(r) for r in rows]


def get_data_type(data_type_id: str) -> dict[str, Any] | None:
    ensure_platform_schema()
    with db_conn() as conn:
        row = conn.execute(
            "SELECT recipe_json FROM platform_data_type WHERE id = ?",
            (data_type_id,),
        ).fetchone()
    return _row_recipe(row) if row else None


def upsert_data_type(recipe: dict[str, Any]) -> dict[str, Any]:
    rec = validate_recipe(recipe)
    now = _utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO platform_data_type (id, recipe_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET recipe_json = excluded.recipe_json, updated_at = excluded.updated_at
            """,
            (rec["id"], json.dumps(rec, ensure_ascii=False), now),
        )
    return rec


def _source_row(row: Any) -> dict[str, Any]:
    item = dict(row)
    kind = resolve_source_kind(kind=str(item.get("kind") or ""), filename=str(item.get("filename") or ""))
    if kind:
        item["kind"] = kind
    if not item.get("collection_id"):
        item["collection_id"] = item.get("source_id")
    return item


def get_source(source_id: str) -> dict[str, Any] | None:
    sid = str(source_id or "").strip()
    if not sid:
        return None
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT source_id, kind, filename, text_schema_id, content_hash,
                   local_oss_key, local_path, collection_id, created_at
            FROM platform_source WHERE source_id = ?
            """,
            (sid,),
        ).fetchone()
    return _source_row(row) if row else None


def put_source(
    *,
    content: bytes,
    kind: str,
    filename: str | None = None,
    text_schema_id: str | None = None,
    collection_id: str | None = None,
) -> dict[str, Any]:
    from hmi.data_source import is_local_mode

    kind_n = resolve_source_kind(kind=kind, filename=filename)
    if kind_n is None or kind_n not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind={kind!r}")
    mod = modality_of(kind_n)
    if mod == "text" and not (text_schema_id or "").strip():
        raise ValueError("text source requires text_schema_id")
    digest = hashlib.sha256(content).hexdigest()
    source_id = "sha256:" + digest
    coll = (collection_id or "").strip() or source_id
    fname = (filename or "").strip() or f"{source_id}{kind_n}"
    local_oss_key: str | None = None
    local_path: str | None = None
    if is_local_mode():
        if mod == "rosbag":
            from hmi.local.bag_upload import persist_local_rosbag_source

            persisted = persist_local_rosbag_source(fname, content)
        else:
            from hmi.local.source_upload import persist_local_media_source

            persisted = persist_local_media_source(
                filename=fname,
                data=content,
                text_schema_id=text_schema_id,
            )
        local_oss_key = str(persisted.get("local_oss_key") or "").strip() or None
        local_path = str(persisted.get("local_path") or "").strip() or None
    now = _utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO platform_source (
              source_id, kind, filename, text_schema_id, content_hash,
              local_oss_key, local_path, collection_id, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
              kind = excluded.kind,
              filename = excluded.filename,
              text_schema_id = excluded.text_schema_id,
              content_hash = excluded.content_hash,
              local_oss_key = excluded.local_oss_key,
              local_path = excluded.local_path,
              collection_id = COALESCE(NULLIF(excluded.collection_id, ''), platform_source.collection_id)
            """,
            (source_id, kind_n, fname, text_schema_id, digest, local_oss_key, local_path, coll, now),
        )
    return {
        "source_id": source_id,
        "kind": kind_n,
        "filename": fname,
        "text_schema_id": text_schema_id,
        "content_hash": digest,
        "local_oss_key": local_oss_key,
        "local_path": local_path,
        "collection_id": coll,
        "created_at": now,
    }


def create_sample(source_ids: list[str], sample_id: str | None = None) -> dict[str, Any]:
    ids = [str(s).strip() for s in source_ids if str(s).strip()]
    if not ids:
        raise ValueError("sample requires at least one source_id")
    sid = (sample_id or "").strip() or str(uuid.uuid4())
    now = _utc_now_iso()
    with db_conn() as conn:
        for src in ids:
            row = conn.execute(
                "SELECT 1 FROM platform_source WHERE source_id = ?",
                (src,),
            ).fetchone()
            if row is None:
                raise ValueError(f"unknown source_id={src}")
        conn.execute(
            "INSERT OR IGNORE INTO platform_sample (sample_id, created_at) VALUES (?, ?)",
            (sid, now),
        )
        for src in ids:
            conn.execute(
                """
                INSERT OR IGNORE INTO platform_sample_source (sample_id, source_id)
                VALUES (?, ?)
                """,
                (sid, src),
            )
    return {"sample_id": sid, "source_ids": list_sample_source_ids(sid)}


def list_sources(
    *,
    limit: int = 100,
    eligible_for: str | None = None,
) -> list[dict[str, Any]]:
    """Return recent lake sources (persisted across sessions).

    When ``eligible_for`` is a data_type_id, only sources whose kind can fill
    that recipe's slots / require_any_kinds are returned.
    """
    lim = max(1, min(int(limit or 100), 500))
    kind_filter: set[str] | None = None
    dtype = (eligible_for or "").strip()
    if dtype:
        recipe = get_data_type(dtype)
        if recipe is None:
            raise ValueError(f"unknown data_type_id={dtype}")
        kind_filter = eligible_kinds_for_recipe(recipe)
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT source_id, kind, filename, text_schema_id, content_hash,
                   local_oss_key, local_path, collection_id, created_at
            FROM platform_source
            ORDER BY created_at DESC, source_id
            LIMIT ?
            """,
            (lim if kind_filter is None else 2000,),
        ).fetchall()
    items = [_source_row(r) for r in rows]
    if kind_filter is not None:
        items = [row for row in items if str(row.get("kind") or "") in kind_filter]
        items = items[:lim]
    return items


def _source_kind_by_id(source_ids: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    with db_conn() as conn:
        for src in source_ids:
            row = conn.execute(
                "SELECT kind, filename FROM platform_source WHERE source_id = ?",
                (src,),
            ).fetchone()
            if row is None:
                continue
            out[src] = (
                resolve_source_kind(kind=str(row["kind"]), filename=str(row["filename"] or ""))
                or str(row["kind"])
            )
    return out


def create_run_from_sources(
    source_ids: list[str],
    data_type_id: str,
    *,
    pipeline_run_id: str | None = None,
    assignments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Auto-create Sample from multi-selected sources, then queue a platform run."""
    from hmi.platform.run_bind import resolve_run_source_bindings

    recipe = get_data_type(data_type_id)
    if recipe is None:
        raise ValueError(f"unknown data_type_id={data_type_id}")
    if recipe.get("status") != "published":
        raise ValueError(f"data type {data_type_id} is not published")
    rec = validate_recipe(recipe)

    mentioned: list[str] = []
    if assignments:
        for asg in assignments:
            if isinstance(asg, dict):
                mentioned.extend(str(s).strip() for s in (asg.get("source_ids") or []) if str(s).strip())
    else:
        mentioned = [str(s).strip() for s in source_ids if str(s).strip()]
    kind_map = _source_kind_by_id(mentioned)
    ids = resolve_run_source_bindings(
        rec,
        source_ids=source_ids,
        assignments=assignments,
        source_kind_by_id=kind_map,
    )
    if not ids:
        raise ValueError("source_ids required")
    kinds = [kind_map.get(src) or "" for src in ids]
    pf = preflight(recipe, kinds)
    if not pf["ok"]:
        raise ValueError("preflight failed: missing " + ",".join(pf.get("missing") or []))
    sample_id = None
    if len(ids) == 1 and modality_of(kinds[0]) == "rosbag":
        sample_id = ids[0]
    sample = create_sample(ids, sample_id=sample_id)
    run = create_run(sample["sample_id"], data_type_id, pipeline_run_id=pipeline_run_id)
    run["source_ids"] = list(sample["source_ids"])
    return run


def list_sample_source_ids(sample_id: str) -> list[str]:
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT source_id FROM platform_sample_source WHERE sample_id = ? ORDER BY source_id",
            (sample_id,),
        ).fetchall()
    return [r["source_id"] for r in rows]


def list_sample_sources(sample_id: str) -> list[dict[str, Any]]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.source_id, s.kind, s.filename, s.text_schema_id, s.content_hash, s.local_oss_key, s.local_path
            FROM platform_sample_source ps
            JOIN platform_source s ON s.source_id = ps.source_id
            WHERE ps.sample_id = ?
            ORDER BY s.filename, s.source_id
            """,
            (sample_id,),
        ).fetchall()
    return [_source_row(r) for r in rows]


def sample_source_kinds(sample_id: str) -> list[str]:
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT s.kind, s.filename
            FROM platform_sample_source ps
            JOIN platform_source s ON s.source_id = ps.source_id
            WHERE ps.sample_id = ?
            """,
            (sample_id,),
        ).fetchall()
    return [
        resolve_source_kind(kind=str(r["kind"]), filename=str(r["filename"] or "")) or str(r["kind"])
        for r in rows
    ]


def preflight_sample(sample_id: str, data_type_id: str) -> dict[str, Any]:
    recipe = get_data_type(data_type_id)
    if recipe is None:
        raise ValueError(f"unknown data_type_id={data_type_id}")
    if recipe.get("status") != "published":
        raise ValueError(f"data type {data_type_id} is not published")
    kinds = sample_source_kinds(sample_id)
    result = preflight(recipe, kinds)
    result["sample_id"] = sample_id
    result["source_kinds"] = kinds
    return result


def create_run(
    sample_id: str,
    data_type_id: str,
    *,
    pipeline_run_id: str | None = None,
) -> dict[str, Any]:
    pf = preflight_sample(sample_id, data_type_id)
    if not pf["ok"]:
        raise ValueError("preflight failed: missing " + ",".join(pf.get("missing") or []))
    if pipeline_run_id:
        pf["pipeline_run_id"] = str(pipeline_run_id)
    run_id = str(uuid.uuid4())
    now = _utc_now_iso()
    recipe = get_data_type(data_type_id)
    assert recipe is not None
    tax_id = recipe["taxonomy_id"]
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO platform_run (
              run_id, sample_id, data_type_id, taxonomy_id, taxonomy_version_id,
              status, y_json, preflight_json, created_at
            ) VALUES (?, ?, ?, ?, NULL, 'queued', '{}', ?, ?)
            """,
            (run_id, sample_id, data_type_id, tax_id, json.dumps(pf, ensure_ascii=False), now),
        )
    return {
        "run_id": run_id,
        "sample_id": sample_id,
        "data_type_id": data_type_id,
        "preflight": pf,
        "pipeline_run_id": pipeline_run_id,
    }


def put_run_y(run_id: str, y: dict[str, Any]) -> None:
    with db_conn() as conn:
        conn.execute(
            "UPDATE platform_run SET y_json = ?, status = 'labeled' WHERE run_id = ?",
            (json.dumps(y, ensure_ascii=False), run_id),
        )


def set_run_status(run_id: str, status: str, *, y: dict[str, Any] | None = None) -> None:
    allowed = {"queued", "running", "completed", "failed", "labeled"}
    if status not in allowed:
        raise ValueError(f"invalid platform_run status={status!r}")
    with db_conn() as conn:
        if y is None:
            conn.execute("UPDATE platform_run SET status = ? WHERE run_id = ?", (status, run_id))
        else:
            conn.execute(
                "UPDATE platform_run SET status = ?, y_json = ? WHERE run_id = ?",
                (status, json.dumps(y, ensure_ascii=False), run_id),
            )


def list_runs_by_status(statuses: list[str], *, limit: int = 20) -> list[dict[str, Any]]:
    wanted = [str(s).strip() for s in statuses if str(s).strip()]
    if not wanted:
        return []
    placeholders = ",".join("?" for _ in wanted)
    with db_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT run_id, sample_id, data_type_id, taxonomy_id, status, y_json, preflight_json, created_at
            FROM platform_run
            WHERE status IN ({placeholders})
            ORDER BY created_at ASC
            LIMIT ?
            """,
            (*wanted, max(1, limit)),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "run_id": row["run_id"],
                "sample_id": row["sample_id"],
                "data_type_id": row["data_type_id"],
                "taxonomy_id": row["taxonomy_id"],
                "status": row["status"],
                "y": json.loads(row["y_json"] or "{}"),
                "preflight": json.loads(row["preflight_json"] or "{}"),
                "created_at": row["created_at"],
            }
        )
    return out


def try_claim_run(run_id: str) -> bool:
    with db_conn() as conn:
        cur = conn.execute(
            """
            UPDATE platform_run
            SET status = 'running'
            WHERE run_id = ? AND status = 'queued'
            """,
            (run_id,),
        )
    return int(cur.rowcount) == 1


def get_run(run_id: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute("SELECT * FROM platform_run WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["run_id"],
        "sample_id": row["sample_id"],
        "data_type_id": row["data_type_id"],
        "taxonomy_id": row["taxonomy_id"],
        "status": row["status"],
        "y": json.loads(row["y_json"] or "{}"),
        "preflight": json.loads(row["preflight_json"] or "{}"),
    }


_product_writes_paused = False


def pause_product_writes() -> None:
    """Block lineage inserts while test-data reset is wiping platform_product."""
    global _product_writes_paused
    _product_writes_paused = True


def resume_product_writes() -> None:
    global _product_writes_paused
    _product_writes_paused = False


def product_writes_paused() -> bool:
    return _product_writes_paused


def record_product(
    *,
    input_ids: list[str],
    op_id: str,
    params: dict[str, Any] | None = None,
    skipped: bool = False,
    artifact_path: str | None = None,
    run_id: str | None = None,
) -> str:
    key = product_cache_key(input_ids, op_id, params)
    if _product_writes_paused:
        return key
    now = _utc_now_iso()
    with db_conn() as conn:
        conn.execute(
            """
            INSERT INTO platform_product (
              cache_key, op_id, input_ids_json, params_json, artifact_path, run_id, skipped, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
              skipped = excluded.skipped,
              artifact_path = COALESCE(excluded.artifact_path, platform_product.artifact_path),
              run_id = COALESCE(excluded.run_id, platform_product.run_id)
            """,
            (
                key,
                op_id,
                json.dumps(sorted(input_ids), ensure_ascii=False),
                json.dumps(params or {}, ensure_ascii=False, sort_keys=True),
                artifact_path,
                run_id,
                1 if skipped else 0,
                now,
            ),
        )
    return key


def product_exists(input_ids: list[str], op_id: str, params: dict[str, Any] | None = None) -> bool:
    key = product_cache_key(input_ids, op_id, params)
    with db_conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM platform_product WHERE cache_key = ?",
            (key,),
        ).fetchone()
    return row is not None


def lookup_or_record_product(
    *,
    input_ids: list[str],
    op_id: str,
    params: dict[str, Any] | None = None,
    artifact_path: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Return cache hit (skipped=True) or insert a new product row."""
    hit = product_exists(input_ids, op_id, params)
    if hit:
        key = product_cache_key(input_ids, op_id, params)
        if artifact_path or run_id:
            record_product(
                input_ids=input_ids,
                op_id=op_id,
                params=params,
                skipped=True,
                artifact_path=artifact_path,
                run_id=run_id,
            )
        return {"cache_key": key, "skipped": True}
    key = record_product(
        input_ids=input_ids,
        op_id=op_id,
        params=params,
        skipped=False,
        artifact_path=artifact_path,
        run_id=run_id,
    )
    return {"cache_key": key, "skipped": False}


_FALLBACK_OP_TITLES = {
    "label": "AI打标器",
    "embed": "向量化",
    "source": "数据源",
}


def _op_title(op_id: str) -> str:
    from hmi.platform.operators import display_op_title

    return display_op_title(op_id) or _FALLBACK_OP_TITLES.get(op_id, op_id)


def _walk_source_refs(
    input_ids: list[str],
    *,
    sources_by_id: dict[str, dict[str, Any]],
    products_by_key: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve input ids to leaf lake sources (walk nested products)."""
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    found: set[str] = set()
    queue = [str(i) for i in input_ids if str(i).strip()]
    while queue:
        iid = queue.pop()
        if not iid or iid in seen_ids:
            continue
        seen_ids.add(iid)
        bare = iid[5:] if iid.startswith("prod:") else iid
        src = sources_by_id.get(iid) or sources_by_id.get(bare)
        if src is not None:
            sid = str(src["source_id"])
            if sid not in found:
                found.add(sid)
                out.append(
                    {
                        "source_id": sid,
                        "kind": src.get("kind"),
                        "filename": src.get("filename"),
                        "collection_id": src.get("collection_id"),
                    }
                )
            continue
        prod = products_by_key.get(iid) or products_by_key.get(bare)
        if prod is not None:
            queue.extend(str(x) for x in (prod.get("input_ids") or []) if str(x).strip())
    return out


def _lineage_sentence(item: dict[str, Any]) -> str:
    step = str(item.get("op_title") or item.get("op_id") or "未知步骤")
    op_id = str(item.get("op_id") or "")
    run_id = str(item.get("run_id") or "").strip()
    dtype_id = str(item.get("data_type_id") or "").strip()
    dtype_title = str(item.get("data_type_title") or "").strip()
    if run_id:
        if dtype_title and dtype_id:
            dtype_bit = f"（数据类型「{dtype_title}」/{dtype_id}）"
        elif dtype_id:
            dtype_bit = f"（数据类型 {dtype_id}）"
        else:
            dtype_bit = ""
        origin = f"管线运行 {run_id}{dtype_bit} 的步骤「{step}」（{op_id}）"
    else:
        origin = f"未关联管线运行；步骤「{step}」（{op_id}）"
    sources = item.get("sources") or []
    if sources:
        names = [str(s.get("filename") or s.get("source_id") or "未知") for s in sources]
        src_clause = f"数据源 {'、'.join(names)}"
    else:
        src_clause = "数据源未知"
    extra = "；缓存命中未重算" if item.get("skipped") else ""
    return f"来自{origin}，{src_clause}{extra}"


def list_products(*, limit: int = 200) -> list[dict[str, Any]]:
    """Newest products with run/step/source lineage for the lake browser."""
    ensure_platform_schema()
    lim = max(1, min(int(limit or 200), 500))
    with db_conn() as conn:
        rows = conn.execute(
            """
            SELECT p.cache_key, p.op_id, p.input_ids_json, p.params_json, p.artifact_path,
                   p.run_id, p.skipped, p.created_at,
                   r.data_type_id, r.status AS run_status, r.created_at AS run_created_at,
                   r.sample_id
            FROM platform_product p
            LEFT JOIN platform_run r ON r.run_id = p.run_id
            ORDER BY p.created_at DESC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
        src_rows = conn.execute(
            "SELECT source_id, kind, filename, collection_id FROM platform_source"
        ).fetchall()
        prod_walk_rows = conn.execute(
            "SELECT cache_key, input_ids_json FROM platform_product"
        ).fetchall()
    sources_by_id = {str(r["source_id"]): dict(r) for r in src_rows}
    products_by_key = {
        str(r["cache_key"]): {"input_ids": json.loads(r["input_ids_json"] or "[]")}
        for r in prod_walk_rows
    }
    dtype_title_cache: dict[str, str | None] = {}
    items: list[dict[str, Any]] = []
    for row in rows:
        input_ids = json.loads(row["input_ids_json"] or "[]")
        op_id = str(row["op_id"])
        spec = get_operator(op_id) or {}
        dtype_id = row["data_type_id"]
        dtype_key = str(dtype_id) if dtype_id else ""
        if dtype_key and dtype_key not in dtype_title_cache:
            rec = get_data_type(dtype_key)
            title = (rec or {}).get("title")
            dtype_title_cache[dtype_key] = str(title) if title else None
        item: dict[str, Any] = {
            "cache_key": row["cache_key"],
            "op_id": op_id,
            "op_title": _op_title(op_id),
            "product_type": spec.get("product"),
            "input_ids": input_ids,
            "params": json.loads(row["params_json"] or "{}"),
            "artifact_path": row["artifact_path"],
            "run_id": row["run_id"],
            "run_status": row["run_status"],
            "run_created_at": row["run_created_at"],
            "sample_id": row["sample_id"],
            "data_type_id": dtype_id,
            "data_type_title": dtype_title_cache.get(dtype_key) if dtype_key else None,
            "skipped": bool(row["skipped"]),
            "created_at": row["created_at"],
            "sources": _walk_source_refs(
                input_ids,
                sources_by_id=sources_by_id,
                products_by_key=products_by_key,
            ),
        }
        item["lineage"] = _lineage_sentence(item)
        items.append(item)
    return items


def get_product(cache_key: str) -> dict[str, Any] | None:
    with db_conn() as conn:
        row = conn.execute(
            """
            SELECT cache_key, op_id, input_ids_json, params_json, artifact_path, run_id, skipped, created_at
            FROM platform_product WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()
    if row is None:
        return None
    return {
        "cache_key": row["cache_key"],
        "op_id": row["op_id"],
        "input_ids": json.loads(row["input_ids_json"] or "[]"),
        "params": json.loads(row["params_json"] or "{}"),
        "artifact_path": row["artifact_path"],
        "run_id": row["run_id"],
        "skipped": bool(row["skipped"]),
        "created_at": row["created_at"],
    }


def lineage_for_source(source_id: str) -> dict[str, Any]:
    """Products that consumed this source_id (directly) and downstream runs."""
    sid = str(source_id).strip()
    with db_conn() as conn:
        src = conn.execute(
            "SELECT source_id, kind, filename, collection_id FROM platform_source WHERE source_id = ?",
            (sid,),
        ).fetchone()
        if src is None:
            raise ValueError(f"unknown source_id={sid}")
        rows = conn.execute(
            """
            SELECT cache_key, op_id, input_ids_json, params_json, artifact_path, run_id, skipped, created_at
            FROM platform_product
            ORDER BY created_at ASC
            """
        ).fetchall()
    products: list[dict[str, Any]] = []
    for row in rows:
        inputs = json.loads(row["input_ids_json"] or "[]")
        if sid not in inputs:
            continue
        products.append(
            {
                "cache_key": row["cache_key"],
                "op_id": row["op_id"],
                "input_ids": inputs,
                "params": json.loads(row["params_json"] or "{}"),
                "artifact_path": row["artifact_path"],
                "run_id": row["run_id"],
                "skipped": bool(row["skipped"]),
                "created_at": row["created_at"],
            }
        )
    return {
        "source": dict(src),
        "products": products,
        "product_count": len(products),
    }


def lineage_for_product(cache_key: str) -> dict[str, Any]:
    prod = get_product(cache_key)
    if prod is None:
        raise ValueError(f"unknown product cache_key={cache_key}")
    parents: list[dict[str, Any]] = []
    for iid in prod["input_ids"]:
        if str(iid).startswith("sha256:") or not str(iid).startswith("prod:"):
            # Prefer source lookup; product keys are opaque hashes.
            with db_conn() as conn:
                src = conn.execute(
                    "SELECT source_id, kind, filename, collection_id FROM platform_source WHERE source_id = ?",
                    (iid,),
                ).fetchone()
            if src is not None:
                parents.append({"type": "source", **dict(src)})
            else:
                upstream = get_product(str(iid))
                if upstream is not None:
                    parents.append({"type": "product", **upstream})
                else:
                    parents.append({"type": "ref", "id": iid})
        else:
            upstream = get_product(str(iid))
            parents.append({"type": "product", **upstream} if upstream else {"type": "ref", "id": iid})
    return {"product": prod, "parents": parents}
