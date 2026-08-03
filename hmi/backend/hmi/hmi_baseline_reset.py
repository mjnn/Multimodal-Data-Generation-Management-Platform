"""Reset HMI operational artifacts to a clean baseline (admin-only)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from hmi.app_db import APP_DB_PATH, ensure_schema, get_user_by_username
from hmi.app_meta import write_app_meta
from hmi.config import TAXONOMY_PATH
from hmi.data_source import (
    LOCAL_ARTIFACTS_ROOT,
    LOCAL_DB_PATH,
    LOCAL_OSS_ROOT,
    LOCAL_ROOT,
    is_local_mode,
    oss_key_path,
)
from hmi.taxonomy.export import (
    TAXONOMY_LATEST_KEY,
    nodes_to_yaml_document,
    serialize_taxonomy_yaml,
    taxonomy_oss_key,
    taxonomy_pointer,
)
from hmi.taxonomy_db import create_version, get_version, list_nodes, publish_version, replace_nodes
from hmi.taxonomy_import import parse_taxonomy_yaml, yaml_labels_to_nodes

BASELINE_TAXONOMY_CODE = "label_tree_baseline"

_LOCAL_PIPELINE_TABLES = (
    "fact_frame",
    "fact_event",
    "fact_audio_segment",
    "fact_image_label",
    "fact_sample_sync_group",
    "fact_embedding",
    "fact_clip_label",
    "fact_clip_embedding",
    "clip_parse_summary",
    "pipeline_step",
    "pipeline_run",
    "pipeline_execution",
    "dim_clip",
    "sync_meta",
)


def _clear_dir_children(root: Path) -> int:
    if not root.is_dir():
        return 0
    removed = 0
    for child in list(root.iterdir()):
        if child.name == ".keep":
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink(missing_ok=True)
        removed += 1
    return removed


def _clear_oss_subtree(prefix: str) -> int:
    """Remove files/dirs under LOCAL_OSS_ROOT/prefix (keep .keep). Returns removed count."""
    if not is_local_mode():
        return 0
    root = LOCAL_OSS_ROOT / prefix.strip("/")
    return _clear_dir_children(root)


def _write_local_taxonomy_export(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise ValueError(f"taxonomy version not found: {version_id}")
    nodes = list_nodes(version_id)
    if not nodes:
        raise ValueError("cannot export taxonomy with zero nodes")

    document = nodes_to_yaml_document(version, nodes)
    yaml_text = serialize_taxonomy_yaml(document)
    oss_key = taxonomy_oss_key(version["version_code"])
    pointer = taxonomy_pointer(version)

    yaml_path = oss_key_path(oss_key)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(yaml_text, encoding="utf-8")

    latest_path = oss_key_path(TAXONOMY_LATEST_KEY)
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text(
        json.dumps({**pointer, "label_count": len(nodes)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    dispatch_path = oss_key_path("pipeline/dispatch/latest.json")
    dispatch: dict[str, Any] = {}
    if dispatch_path.is_file():
        try:
            loaded = json.loads(dispatch_path.read_text(encoding="utf-8"))
            dispatch = loaded if isinstance(loaded, dict) else {}
        except (json.JSONDecodeError, OSError):
            dispatch = {}
    for key in ("taxonomy_version_id", "taxonomy_version_code", "taxonomy_oss_key"):
        val = pointer.get(key)
        if val:
            dispatch[key] = str(val)
    dispatch_path.parent.mkdir(parents=True, exist_ok=True)
    dispatch_path.write_text(json.dumps(dispatch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    write_app_meta(
        {
            "latest_published_taxonomy_version_id": pointer["taxonomy_version_id"],
            "latest_published_taxonomy_version_code": pointer["taxonomy_version_code"],
            "latest_published_taxonomy_oss_key": pointer["taxonomy_oss_key"],
        }
    )
    return {**pointer, "label_count": len(nodes)}


def _seed_baseline_taxonomy(*, created_by: str | None) -> dict[str, Any]:
    parsed = parse_taxonomy_yaml(TAXONOMY_PATH)
    nodes = yaml_labels_to_nodes(parsed.labels)
    version = create_version(
        BASELINE_TAXONOMY_CODE,
        source_import=str(parsed.yaml_path),
        created_by=created_by,
    )
    replace_nodes(version["id"], nodes)
    publish_version(version["id"])

    if is_local_mode():
        export_info = _write_local_taxonomy_export(version["id"])
    else:
        from hmi.taxonomy.export import export_published_taxonomy

        export_info = export_published_taxonomy(version["id"])

    return {
        "version_id": version["id"],
        "version_code": BASELINE_TAXONOMY_CODE,
        "node_count": export_info.get("label_count", len(nodes)),
    }


def _purge_app_db_artifacts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}

    def _count(table: str) -> int:
        row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
        return int(row["c"]) if row else 0

    for table in (
        "review_workbench_session",
        "review_assignment_item",
        "review_assignment_batch",
        "clip_label_field_review",
        "clip_label_review",
        "audit_log",
        "dataset_snapshot",
        "taxonomy_proposal",
    ):
        n = _count(table)
        conn.execute(f"DELETE FROM {table}")
        counts[table] = n

    tax_versions = _count("label_taxonomy_version")
    conn.execute("DELETE FROM label_taxonomy_node")
    conn.execute("DELETE FROM label_taxonomy_version")
    counts["label_taxonomy_version"] = tax_versions

    admin = conn.execute(
        "SELECT id FROM app_user WHERE username = ? LIMIT 1",
        ("admin",),
    ).fetchone()
    if admin is None:
        raise RuntimeError("admin user missing; run scripts/bootstrap_admin.py first")

    admin_id = str(admin["id"])
    non_admin = conn.execute(
        "SELECT id FROM app_user WHERE username != ?",
        ("admin",),
    ).fetchall()
    removed_users = len(non_admin)
    for row in non_admin:
        uid = str(row["id"])
        conn.execute("DELETE FROM app_user_role WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM app_user WHERE id = ?", (uid,))

    counts["app_user_removed"] = removed_users
    return counts


def _purge_local_pipeline_runtime() -> dict[str, Any]:
    """Clear local SDK pipeline SQLite rows, disk artifacts, and upload task memory."""
    if not is_local_mode():
        return {"skipped": True, "reason": "not local mode"}

    from hmi.db import cache_clear
    from hmi.local.store import ensure_db
    from hmi.services import upload

    ensure_db()
    db_counts: dict[str, int] = {}
    if LOCAL_DB_PATH.is_file():
        with sqlite3.connect(LOCAL_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            for table in _LOCAL_PIPELINE_TABLES:
                try:
                    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                    n = int(row["c"]) if row else 0
                except sqlite3.OperationalError:
                    n = 0
                if n:
                    conn.execute(f"DELETE FROM {table}")
                db_counts[table] = n
            conn.commit()

    settings_path = LOCAL_ROOT / "config" / "pipeline_settings.json"
    if settings_path.is_file():
        settings_path.unlink(missing_ok=True)

    oss_cleared = {
        "rosbags": _clear_oss_subtree("rosbags"),
        "clips": _clear_oss_subtree("clips"),
        "pipeline": _clear_oss_subtree("pipeline"),
        "config": _clear_oss_subtree("config"),
    }
    artifacts_removed = _clear_dir_children(LOCAL_ARTIFACTS_ROOT)
    sdk_work_removed = _clear_dir_children(LOCAL_ROOT / "work" / "sdk_runs")
    upload_tasks_cleared = upload.clear_upload_tasks()
    cache_clear()

    return {
        "skipped": False,
        "sqlite_rows_removed": db_counts,
        "artifacts_entries_removed": artifacts_removed,
        "sdk_work_entries_removed": sdk_work_removed,
        "oss_entries_removed": oss_cleared,
        "upload_tasks_cleared": upload_tasks_cleared,
    }


def reset_hmi_artifacts_to_baseline() -> dict[str, Any]:
    """
    Baseline state:
    - Only user ``admin``
    - No datasets, reviews, assignments, or audit log
    - Single published taxonomy ``label_tree_baseline`` from repo YAML
    - Local mode: clears oss/datasets, oss/reviews, re-exports taxonomy under oss/config/
    - Local mode: clears SDK pipeline (hmi.db clip/run/facts, execution batches, rosbags/clips/pipeline, artifacts, sdk work)
    """
    ensure_schema()
    admin = get_user_by_username("admin")
    if admin is None:
        raise RuntimeError("admin user missing; run hmi/scripts/bootstrap_admin.py first")

    local_pipeline = _purge_local_pipeline_runtime()

    with sqlite3.connect(APP_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        db_counts = _purge_app_db_artifacts(conn)
        conn.commit()

    oss_cleared = {
        "datasets": _clear_oss_subtree("datasets"),
        "reviews": _clear_oss_subtree("reviews"),
    }

    taxonomy = _seed_baseline_taxonomy(created_by=str(admin["id"]))

    if is_local_mode() and not local_pipeline.get("skipped"):
        from hmi.local.pipeline_settings import save_pipeline_settings

        save_pipeline_settings({"taxonomy_version_id": taxonomy["version_id"]})

    return {
        "ok": True,
        "message": "HMI 产物已重置为 baseline",
        "baseline_taxonomy": taxonomy,
        "db_purged": db_counts,
        "oss_entries_removed": oss_cleared,
        "local_pipeline_purged": local_pipeline,
    }
