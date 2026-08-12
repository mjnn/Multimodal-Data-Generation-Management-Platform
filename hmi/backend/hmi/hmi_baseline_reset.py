"""Reset HMI operational artifacts to a clean baseline (admin-only, test mode)."""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Any

from hmi.app_db import APP_DB_PATH, ensure_schema, get_user_by_username
from hmi.app_meta import write_app_meta
from hmi.config import TAXONOMY_PATH, get_settings
from hmi.data_source import (
    LOCAL_ARTIFACTS_ROOT,
    LOCAL_DB_PATH,
    LOCAL_OSS_ROOT,
    LOCAL_ROOT,
    is_cloud_mode,
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
from hmi.test_mode import is_test_mode

logger = logging.getLogger(__name__)

_RESET_LOCK = threading.Lock()
_PROGRESS_LOCK = threading.Lock()
_PROGRESS: dict[str, Any] = {
    "running": False,
    "percent": 0,
    "stage": "idle",
    "message": "",
    "error": None,
    "ok": None,
}

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

# Cloud OSS prefixes wiped on 「重置测试数据」(taxonomy re-exported after wipe).
_CLOUD_OSS_PREFIXES = (
    "rosbags/",
    "clips/",
    "pipeline/",
    "datasets/",
    "reviews/",
    "config/",
)

_SDK_MC_SUFFIXES = (
    "dim_clip",
    "dispatch_staging",
    "pipeline_run",
    "pipeline_step",
    "clip_parse_summary",
    "fact_clip_label",
    "fact_clip_embedding",
    "fact_audio_segment",
)

_LEGACY_MC_SUFFIXES = (
    "dim_clip",
    "pipeline_run",
    "pipeline_step",
    "fact_message_timeline",
    "fact_frame",
    "fact_audio_chunk",
    "fact_event",
    "clip_parse_summary",
    "fact_sample_policy",
    "fact_sample_sync_group",
    "fact_audio_segment",
    "fact_image_label",
    "fact_embedding",
    "dispatch_staging",
)


def get_reset_progress() -> dict[str, Any]:
    with _PROGRESS_LOCK:
        return dict(_PROGRESS)


def _set_progress(
    *,
    percent: int | None = None,
    stage: str | None = None,
    message: str | None = None,
    running: bool | None = None,
    error: str | None = None,
    ok: bool | None = None,
) -> None:
    with _PROGRESS_LOCK:
        if running is not None:
            _PROGRESS["running"] = running
        if percent is not None:
            _PROGRESS["percent"] = max(0, min(100, int(percent)))
        if stage is not None:
            _PROGRESS["stage"] = stage
        if message is not None:
            _PROGRESS["message"] = message
        if error is not None:
            _PROGRESS["error"] = error
        if ok is not None:
            _PROGRESS["ok"] = ok


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


def _partition_spec_for_drop(part_name: str) -> str:
    part_name = part_name.strip()
    if part_name.count("=") != 1:
        return part_name
    key, value = part_name.split("=", 1)
    value = value.strip().strip("'").strip('"')
    safe_value = value.replace("'", "''")
    return f"{key}='{safe_value}'"


def _cloud_mc_table_names() -> list[str]:
    """Prefer configured SDK/table prefixes; always include both sdk + legacy for full wipe."""
    settings = get_settings()
    prefixes: list[str] = []
    for key in ("sdk_table_prefix", "table_prefix"):
        raw = str(settings.get(key) or "").strip()
        if raw and raw not in prefixes:
            prefixes.append(raw)
    for fallback in ("aig_sdk__", "aig_rosbag__"):
        if fallback not in prefixes:
            prefixes.append(fallback)
    names: list[str] = []
    seen: set[str] = set()
    for prefix in prefixes:
        if "sdk" in prefix:
            suffixes = list(dict.fromkeys([*_SDK_MC_SUFFIXES, *_LEGACY_MC_SUFFIXES]))
        else:
            suffixes = list(_LEGACY_MC_SUFFIXES)
        for suffix in suffixes:
            name = f"{prefix}{suffix}"
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def _purge_cloud_mc() -> dict[str, Any]:
    from hmi.db import odps_client

    odps = odps_client()
    cleared: list[str] = []
    missing: list[str] = []
    batch_size = 40
    tables = _cloud_mc_table_names()
    total = max(len(tables), 1)
    for idx, table_name in enumerate(tables):
        # OSS 已占约 5–45%；MC 占 45–80%
        pct = 45 + int(35 * idx / total)
        _set_progress(
            percent=pct,
            stage="mc",
            message=f"清理 MaxCompute 表 ({idx + 1}/{total})：{table_name}",
        )
        if not odps.exist_table(table_name):
            missing.append(table_name)
            continue
        table = odps.get_table(table_name)
        schema = table.table_schema
        if schema.partitions:
            parts = list(table.partitions)
            logger.info("reset MC %s: drop %s partition(s)", table_name, len(parts))
            for start in range(0, len(parts), batch_size):
                batch = parts[start : start + batch_size]
                specs = ", ".join(
                    f"PARTITION ({_partition_spec_for_drop(part.name)})" for part in batch
                )
                drop_sql = f"ALTER TABLE {table_name} DROP IF EXISTS {specs}"
                instance = odps.execute_sql(drop_sql)
                instance.wait_for_success()
        else:
            logger.info("reset MC %s: truncate", table_name)
            instance = odps.execute_sql(f"TRUNCATE TABLE {table_name}")
            instance.wait_for_success()
        cleared.append(table_name)
    _set_progress(percent=80, stage="mc", message="MaxCompute 表清理完成")
    return {"cleared_tables": cleared, "missing_tables": missing}


def _purge_cloud_oss() -> dict[str, int]:
    from hmi.services import oss_manage

    counts: dict[str, int] = {}
    total = max(len(_CLOUD_OSS_PREFIXES), 1)
    for idx, prefix in enumerate(_CLOUD_OSS_PREFIXES):
        pct = 5 + int(40 * idx / total)
        _set_progress(
            percent=pct,
            stage="oss",
            message=f"清理 OSS 前缀 ({idx + 1}/{total})：{prefix}",
        )
        logger.info("reset OSS prefix %s …", prefix)
        result = oss_manage.delete_prefix(prefix)
        n = int(result.get("count") or len(result.get("deleted") or []))
        counts[prefix.rstrip("/")] = n
        logger.info("reset OSS prefix %s deleted=%s", prefix, n)
    _set_progress(percent=45, stage="oss", message="OSS 前缀清理完成")
    return counts


def _purge_cloud_pipeline_runtime() -> dict[str, Any]:
    """Wipe cloud OSS pipeline prefixes + MaxCompute fact/dim tables (test mode)."""
    if not is_cloud_mode():
        return {"skipped": True, "reason": "not cloud mode"}
    logger.info("cloud test-data reset: OSS then MC")
    oss = _purge_cloud_oss()
    mc = _purge_cloud_mc()
    return {
        "skipped": False,
        "oss_entries_removed": oss,
        "mc": mc,
    }


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
        "clip_bbox_qa",
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


def _purge_hmi_pipeline_queue_state() -> dict[str, Any]:
    """Clear HMI-side execution queue stores (local SQLite batch + cloud JSON queue).

    Cloud 「管线执行队列」读的是 ``LOCAL_ROOT/cloud_pipeline_jobs.json``，与是否本地模式无关；
    重置测试数据时必须一并清空，否则 UI 仍会显示待执行批次。
    """
    from hmi.services import upload
    from hmi.services.cloud_pipeline_execution import clear_all_executions

    _set_progress(percent=82, stage="queue", message="清空管线执行队列…")

    cloud_cleared = clear_all_executions()
    upload_tasks_cleared = upload.clear_upload_tasks()

    # 即使当前是云端模式，也清掉本地 hmi.db 里的执行批次，避免切回本地时残留
    local_exec_rows = 0
    if LOCAL_DB_PATH.is_file():
        try:
            with sqlite3.connect(LOCAL_DB_PATH) as conn:
                row = conn.execute("SELECT COUNT(*) AS c FROM pipeline_execution").fetchone()
                local_exec_rows = int(row[0]) if row else 0
                if local_exec_rows:
                    conn.execute("DELETE FROM pipeline_execution")
                conn.commit()
        except sqlite3.OperationalError:
            local_exec_rows = 0

    return {
        "cloud_jobs_removed": cloud_cleared,
        "upload_tasks_cleared": upload_tasks_cleared,
        "local_pipeline_execution_rows": local_exec_rows,
    }


def _purge_local_pipeline_runtime() -> dict[str, Any]:
    """Clear local SDK pipeline SQLite rows, disk artifacts, and upload task memory."""
    if not is_local_mode():
        return {"skipped": True, "reason": "not local mode"}

    from hmi.db import cache_clear
    from hmi.local.store import ensure_db
    from hmi.services import upload

    _set_progress(percent=10, stage="local", message="清理本地 SQLite 管线表…")
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

    _set_progress(percent=35, stage="local", message="清理本地 OSS 镜像目录…")
    oss_cleared = {
        "rosbags": _clear_oss_subtree("rosbags"),
        "clips": _clear_oss_subtree("clips"),
        "pipeline": _clear_oss_subtree("pipeline"),
        "config": _clear_oss_subtree("config"),
    }
    _set_progress(percent=55, stage="local", message="清理 artifacts / SDK work…")
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
    Baseline state (requires HMI_TEST_MODE=1):
    - Only user ``admin``
    - No datasets, reviews, assignments, or audit log
    - Single published taxonomy ``label_tree_baseline`` from repo YAML
    - Local mode: clears oss/datasets, oss/reviews, re-exports taxonomy under oss/config/
    - Local mode: clears SDK pipeline (hmi.db clip/run/facts, execution batches, rosbags/clips/pipeline, artifacts, sdk work)
    - Cloud mode: clears cloud OSS (rosbags/clips/pipeline/datasets/reviews/config) + MC aig_sdk__/aig_rosbag__ tables, then re-exports taxonomy
    """
    if not is_test_mode():
        raise PermissionError("重置测试数据仅在测试模式（HMI_TEST_MODE=1）下可用")

    if not _RESET_LOCK.acquire(blocking=False):
        raise RuntimeError("已有重置任务在执行，请稍候再试（云端清理可能需数分钟）")

    _set_progress(
        running=True,
        percent=1,
        stage="start",
        message="开始重置测试数据…",
        error=None,
        ok=None,
    )
    try:
        ensure_schema()
        admin = get_user_by_username("admin")
        if admin is None:
            raise RuntimeError("admin user missing; run hmi/scripts/bootstrap_admin.py first")

        logger.info("test-data reset start (mode=%s)", "local" if is_local_mode() else "cloud")
        local_pipeline = _purge_local_pipeline_runtime()
        cloud_pipeline = _purge_cloud_pipeline_runtime()
        queue_purged = _purge_hmi_pipeline_queue_state()

        _set_progress(percent=85, stage="app_db", message="清理应用库（用户/校核/数据集/标签树）…")
        with sqlite3.connect(APP_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            db_counts = _purge_app_db_artifacts(conn)
            conn.commit()

        oss_cleared = {
            "datasets": _clear_oss_subtree("datasets"),
            "reviews": _clear_oss_subtree("reviews"),
        }

        _set_progress(percent=92, stage="taxonomy", message="写入 baseline 标签树…")
        taxonomy = _seed_baseline_taxonomy(created_by=str(admin["id"]))

        if is_local_mode() and not local_pipeline.get("skipped"):
            from hmi.local.pipeline_settings import save_pipeline_settings

            save_pipeline_settings({"taxonomy_version_id": taxonomy["version_id"]})

        result = {
            "ok": True,
            "message": "测试数据已重置为 baseline",
            "baseline_taxonomy": taxonomy,
            "db_purged": db_counts,
            "oss_entries_removed": oss_cleared,
            "local_pipeline_purged": local_pipeline,
            "cloud_pipeline_purged": cloud_pipeline,
            "pipeline_queue_purged": queue_purged,
        }
        _set_progress(
            running=False,
            percent=100,
            stage="done",
            message=result["message"],
            ok=True,
            error=None,
        )
        logger.info("test-data reset done")
        return result
    except Exception as exc:
        _set_progress(
            running=False,
            stage="error",
            message=str(exc),
            error=str(exc),
            ok=False,
        )
        raise
    finally:
        _RESET_LOCK.release()
