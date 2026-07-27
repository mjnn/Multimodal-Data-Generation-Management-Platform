"""M4.4 dataset MC export smoke test."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import ensure_schema
from hmi.dataset.build import build_snapshot_sync
from hmi.dataset.mc_export import (
    MC_TABLE_SUFFIX,
    export_snapshot_rows_to_mc,
    resolve_mc_table_name,
    should_export_to_mc,
)
from hmi.dataset.assemble import AssemblyResult
from hmi.dataset_db import create_snapshot, get_snapshot
from hmi.local import store
from hmi.review_db import create_review

_uploads: dict[str, str] = {}
_mc_writes: list[dict] = []


def _mock_put_object_text(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


class _FakeWriter:
    def __init__(self) -> None:
        self.rows: list[list] = []

    def write(self, rows: list[list]) -> None:
        self.rows.extend(rows)

    def __enter__(self) -> _FakeWriter:
        return self

    def __exit__(self, *args) -> None:
        return None


class _FakeTable:
    def __init__(self) -> None:
        self.writer = _FakeWriter()
        self.partition: str | None = None

    def open_writer(self, *, partition: str, create_partition: bool) -> _FakeWriter:
        self.partition = partition
        return self.writer


class _FakeOdps:
    def __init__(self) -> None:
        self.table = _FakeTable()
        self.deletes: list[str] = []

    def execute_sql(self, sql: str) -> None:
        self.deletes.append(sql)

    def get_table(self, name: str) -> _FakeTable:
        return self.table


def _seed_clip(*, clip_id: str, run_id: str, ds: str) -> None:
    store.execute(
        "INSERT OR REPLACE INTO dim_clip (clip_id, clip_dir_name, active_run_id) VALUES (?, ?, ?)",
        (clip_id, clip_id[:16], run_id),
    )
    store.execute(
        "INSERT OR REPLACE INTO pipeline_run (run_id, clip_id, ds, status) VALUES (?, ?, ?, 'completed')",
        (run_id, clip_id, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_embedding (
          clip_id, run_id, ds, object_type, object_id, timestamp_ns, vector_json, dim
        ) VALUES (?, ?, ?, 'frame', 'cam0:0', 1000000000, ?, 2)
        """,
        (clip_id, run_id, ds, json.dumps([0.5, 0.5])),
    )


def main() -> None:
    ensure_schema()
    _uploads.clear()
    _mc_writes.clear()
    suffix = uuid.uuid4().hex[:8]
    ds = "20260721"
    clip_id = f"sha256:m44_{suffix}"
    run_id = str(uuid.uuid4())

    _seed_clip(clip_id=clip_id, run_id=run_id, ds=ds)
    create_review(clip_id, run_id, labels_json={"L1.1.day_period": "night"}, review_status="reviewed")

    assert should_export_to_mc() is False
    print("OK local mode skips MC export gate")

    snapshot = create_snapshot(
        f"m44_local_{suffix}",
        filter_json={"review_status": "reviewed", "clip_ids": [clip_id]},
    )
    with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text):
        result = build_snapshot_sync(snapshot["id"])
    local_ready = result["snapshot"]
    assert local_ready["status"] == "ready"
    assert local_ready["mc_table_name"] is None
    assert result["mc_export"]["skipped"] is True
    print("OK build local -> mc_table_name null")

    assembly = AssemblyResult(
        rows=[
            {
                "snapshot_id": "snap-test",
                "clip_id": clip_id,
                "run_id": run_id,
                "x_json": [{"object_type": "frame", "vector": [0.5, 0.5]}],
                "y_json": {"L1.1.day_period": "night"},
                "taxonomy_version_id": None,
                "taxonomy_version_code": None,
            }
        ],
        clip_count=1,
    )
    fake_odps = _FakeOdps()
    with (
        patch("hmi.dataset.mc_export.should_export_to_mc", return_value=True),
        patch("hmi.dataset.mc_export.resolve_mc_table_name", return_value="aig_rosbag__dataset_snapshot_row"),
        patch("hmi.dataset.mc_export.odps_client", return_value=fake_odps),
    ):
        mc_result = export_snapshot_rows_to_mc("snap-test", assembly, client=fake_odps)

    assert mc_result["skipped"] is False
    assert mc_result["row_count"] == 1
    assert mc_result["mc_table_name"] == "aig_rosbag__dataset_snapshot_row"
    assert fake_odps.table.partition == "snapshot_id=snap-test"
    assert len(fake_odps.table.writer.rows) == 1
    written = fake_odps.table.writer.rows[0]
    assert written[0] == "snap-test"
    assert written[1] == clip_id
    assert written[2] == run_id
    assert json.loads(written[4])["L1.1.day_period"] == "night"
    assert written[7] == ds
    assert any("DELETE FROM" in sql for sql in fake_odps.deletes)
    print("OK export_snapshot_rows_to_mc cloud mock")

    cloud_snapshot = create_snapshot(
        f"m44_cloud_{suffix}",
        filter_json={"review_status": "reviewed", "clip_ids": [clip_id]},
    )
    with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text):
        with patch("hmi.dataset.build.should_export_to_mc", return_value=True):
            with patch("hmi.dataset.build.export_snapshot_rows_to_mc") as mc_mock:
                mc_mock.return_value = {
                    "mc_table_name": "aig_rosbag__dataset_snapshot_row",
                    "row_count": 1,
                    "skipped": False,
                }
                cloud_result = build_snapshot_sync(cloud_snapshot["id"])

    cloud_ready = get_snapshot(cloud_snapshot["id"])
    assert cloud_ready is not None
    assert cloud_ready["status"] == "ready"
    assert cloud_ready["mc_table_name"] == "aig_rosbag__dataset_snapshot_row"
    mc_mock.assert_called_once()
    assert cloud_result["mc_export"]["row_count"] == 1
    print("OK build cloud hooks mc_export + mc_table_name")

    with patch("hmi.config.get_settings", return_value={"table_prefix": "aig_rosbag__"}):
        assert resolve_mc_table_name().endswith(MC_TABLE_SUFFIX)
    print("OK resolve_mc_table_name")

    print("\nAll M4.4 checks passed.")


if __name__ == "__main__":
    main()
