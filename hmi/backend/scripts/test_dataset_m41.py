"""M4.1 dataset_snapshot DB smoke test."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.dataset_db import (
    DATASET_STATUSES,
    DEFAULT_FEATURE_SPEC,
    DEFAULT_FILTER,
    DEFAULT_TARGET_SPEC,
    count_snapshots,
    create_snapshot,
    get_snapshot,
    list_snapshots,
    update_snapshot,
)


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    manager_name = f"m41_manager_{suffix}"
    if get_user_by_username(manager_name) is None:
        user = create_user(manager_name, "managerpass123", roles=["dataset_manager"])
        manager_id = user["id"]
    else:
        manager_id = get_user_by_username(manager_name)["id"]

    snapshot = create_snapshot(
        f"m41_dataset_{suffix}",
        description="test snapshot",
        created_by=manager_id,
    )
    assert snapshot["status"] == "building"
    assert snapshot["filter_json"] == DEFAULT_FILTER
    assert snapshot["feature_spec_json"] == DEFAULT_FEATURE_SPEC
    assert snapshot["target_spec_json"] == DEFAULT_TARGET_SPEC
    assert snapshot["clip_count"] == 0
    print("OK create_snapshot defaults")

    listed = list_snapshots(limit=20)
    assert any(s["id"] == snapshot["id"] for s in listed)
    assert count_snapshots() >= 1
    print("OK list_snapshots + count")

    ready = update_snapshot(
        snapshot["id"],
        status="ready",
        clip_count=42,
        oss_manifest_uri=f"datasets/{snapshot['id']}/manifest.jsonl",
        mc_table_name="aig_rosbag__dataset_snapshot_row",
    )
    assert ready["status"] == "ready"
    assert ready["clip_count"] == 42
    assert ready["ready_at"]
    assert ready["oss_manifest_uri"]
    print("OK update_snapshot -> ready")

    failed = update_snapshot(
        snapshot["id"],
        status="failed",
        error_message="simulated build error",
    )
    assert failed["status"] == "failed"
    assert failed["error_message"] == "simulated build error"
    print("OK update_snapshot -> failed")

    retried = update_snapshot(
        snapshot["id"],
        status="building",
        clear_error=True,
    )
    assert retried["status"] == "building"
    assert retried["error_message"] is None
    print("OK retry building clears error")

    archived = update_snapshot(snapshot["id"], status="archived")
    assert archived["status"] == "archived"
    assert not any(s["id"] == snapshot["id"] for s in list_snapshots())
    assert get_snapshot(snapshot["id"]) is not None
    print("OK archived hidden from default list")

    try:
        update_snapshot(str(uuid.uuid4()), status="ready")
        print("FAIL missing snapshot should raise")
        raise SystemExit(1)
    except ValueError as exc:
        assert "not found" in str(exc)
    print("OK update missing snapshot rejected")

    assert DATASET_STATUSES == frozenset({"building", "ready", "failed", "archived"})
    print("\nAll M4.1 checks passed.")


if __name__ == "__main__":
    main()
