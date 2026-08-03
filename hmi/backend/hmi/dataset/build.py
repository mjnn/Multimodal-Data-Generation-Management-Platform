"""Build dataset snapshots asynchronously."""

from __future__ import annotations

import threading
from typing import Any

from hmi.dataset.assemble import assemble_snapshot_rows
from hmi.dataset.export import export_xy_to_oss
from hmi.dataset_db import get_snapshot, update_snapshot

_build_lock = threading.Lock()
_running: set[str] = set()


def _mark_running(snapshot_id: str, *, running: bool) -> None:
    with _build_lock:
        if running:
            _running.add(snapshot_id)
        else:
            _running.discard(snapshot_id)


def is_build_running(snapshot_id: str) -> bool:
    with _build_lock:
        return snapshot_id in _running


def _taxonomy_summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    version_ids: set[str] = set()
    version_codes: set[str] = set()
    for row in rows:
        vid = row.get("taxonomy_version_id")
        vcode = row.get("taxonomy_version_code")
        if vid:
            version_ids.add(str(vid))
        if vcode:
            version_codes.add(str(vcode))
    summary: dict[str, Any] = {}
    if len(version_ids) == 1:
        summary["version_id"] = next(iter(version_ids))
    elif version_ids:
        summary["version_ids"] = sorted(version_ids)
    if len(version_codes) == 1:
        summary["version_code"] = next(iter(version_codes))
    elif version_codes:
        summary["version_codes"] = sorted(version_codes)
    return summary


def _resolve_export_preset(snapshot: dict[str, Any]) -> str:
    filt = snapshot.get("filter_json") or {}
    return str(snapshot.get("export_preset") or filt.get("export_preset") or "minimal")


def _resolve_aug_recipe_meta(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    recipe_id = snapshot.get("aug_recipe_id")
    if not recipe_id:
        return None
    from hmi.dataset.aug_recipe_db import get_recipe

    recipe = get_recipe(str(recipe_id))
    if recipe is None:
        return None
    return {
        "recipe_id": recipe["id"],
        "recipe_code": recipe["recipe_code"],
        "version": recipe["version"],
    }


def build_snapshot_sync(snapshot_id: str) -> dict[str, Any]:
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        raise ValueError(f"snapshot not found: {snapshot_id}")
    if snapshot["status"] == "archived":
        raise ValueError("archived snapshot cannot be built")

    if is_build_running(snapshot_id):
        raise ValueError(f"build already running: {snapshot_id}")

    _mark_running(snapshot_id, running=True)
    try:
        update_snapshot(snapshot_id, status="building", clear_error=True)
        assembly = assemble_snapshot_rows(
            snapshot.get("filter_json"),
            snapshot_id=snapshot_id,
        )
        if assembly.clip_count == 0:
            message = "no clip rows assembled"
            if assembly.warnings:
                message = f"{message}: {'; '.join(assembly.warnings[:3])}"
            raise ValueError(message)

        export_preset = _resolve_export_preset(snapshot)
        taxonomy_summary = _taxonomy_summary_from_rows(assembly.rows)
        aug_recipe_meta = _resolve_aug_recipe_meta(snapshot)

        export_info = export_xy_to_oss(
            snapshot_id,
            assembly,
            snapshot_name=snapshot.get("name"),
            export_preset=export_preset,
            filter_snapshot=snapshot.get("filter_json"),
            augmentation_mode=str(snapshot.get("augmentation_mode") or "none"),
            parent_snapshot_id=snapshot.get("parent_snapshot_id"),
            derivation=snapshot.get("derivation_json"),
            aug_recipe=aug_recipe_meta,
            taxonomy_summary=taxonomy_summary,
        )
        build_report = dict(export_info["build_report"] or {})
        if export_info.get("parquet_available"):
            build_report["parquet_available"] = True
        updated = update_snapshot(
            snapshot_id,
            status="ready",
            clip_count=export_info["clip_count"],
            line_count=export_info["line_count"],
            oss_x_uri=export_info["oss_x_uri"],
            oss_y_uri=export_info["oss_y_uri"],
            oss_manifest_uri=export_info["oss_package_uri"],
            mc_table_name="",
            export_preset=export_info["export_preset"],
            build_report=build_report,
            schema_version=export_info["schema_version"],
        )
        return {
            "snapshot": updated,
            "export": export_info,
            "warnings": assembly.warnings,
            "skipped": assembly.skipped,
            "build_report": assembly.build_report,
            "distribution_report": assembly.distribution_report,
        }
    except Exception as exc:
        update_snapshot(snapshot_id, status="failed", error_message=str(exc))
        raise
    finally:
        _mark_running(snapshot_id, running=False)


def _build_thread_target(snapshot_id: str) -> None:
    try:
        build_snapshot_sync(snapshot_id)
    except Exception:
        pass


def enqueue_build(snapshot_id: str) -> None:
    snapshot = get_snapshot(snapshot_id)
    if snapshot is None:
        raise ValueError(f"snapshot not found: {snapshot_id}")
    if snapshot["status"] == "archived":
        raise ValueError("archived snapshot cannot be built")
    if is_build_running(snapshot_id):
        raise ValueError(f"build already running: {snapshot_id}")

    thread = threading.Thread(
        target=_build_thread_target,
        args=(snapshot_id,),
        name=f"dataset-build-{snapshot_id[:8]}",
        daemon=True,
    )
    thread.start()
