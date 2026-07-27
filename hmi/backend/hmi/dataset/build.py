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

        export_info = export_xy_to_oss(
            snapshot_id,
            assembly,
            snapshot_name=snapshot.get("name"),
        )
        updated = update_snapshot(
            snapshot_id,
            status="ready",
            clip_count=export_info["clip_count"],
            oss_x_uri=export_info["oss_x_uri"],
            oss_y_uri=export_info["oss_y_uri"],
            oss_manifest_uri=export_info["oss_package_uri"],
            mc_table_name="",
        )
        return {
            "snapshot": updated,
            "export": export_info,
            "warnings": assembly.warnings,
            "skipped": assembly.skipped,
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
