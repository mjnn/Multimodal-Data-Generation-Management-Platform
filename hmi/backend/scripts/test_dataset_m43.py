"""M4.3 dataset build + OSS export smoke test."""

from __future__ import annotations

import json
import sys
import uuid
import zipfile
import io
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import ensure_schema
from hmi.dataset.build import build_snapshot_sync
from hmi.dataset.export import meta_oss_key, package_oss_key, parsed_oss_key, x_oss_key, y_oss_key
from hmi.dataset_db import create_snapshot, get_snapshot
from hmi.local import store
from hmi.review_db import create_review

_uploads: dict[str, str] = {}
_upload_bytes: dict[str, bytes] = {}


def _mock_put_object_text(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


def _mock_put_object_bytes(key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
    _upload_bytes[key.lstrip("/")] = data


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
        (clip_id, run_id, ds, json.dumps([1.0, 0.0])),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO clip_parse_summary (
          clip_id, run_id, ds, start_time_ns, end_time_ns, duration_sec
        ) VALUES (?, ?, ?, 1000000000, 2000000000, 1.0)
        """,
        (clip_id, run_id, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_frame (
          clip_id, run_id, ds, camera, frame_idx, timestamp_ns, image_path
        ) VALUES (?, ?, ?, 'camera0', 0, 1000000000, 'parsed/output/images/camera0/000000.jpg')
        """,
        (clip_id, run_id, ds),
    )


def main() -> None:
    ensure_schema()
    _uploads.clear()
    _upload_bytes.clear()
    suffix = uuid.uuid4().hex[:8]
    ds = "20260721"
    clip_id = f"sha256:m43_{suffix}"
    run_id = str(uuid.uuid4())

    _seed_clip(clip_id=clip_id, run_id=run_id, ds=ds)
    create_review(clip_id, run_id, labels_json={"L1.1.day_period": "morning"}, review_status="reviewed")
    snapshot = create_snapshot(
        f"m43_dataset_{suffix}",
        filter_json={"review_status": "reviewed", "clip_ids": [clip_id]},
    )

    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True), patch(
        "hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text
    ), patch("hmi.dataset.export.put_object_bytes", side_effect=_mock_put_object_bytes), patch(
        "hmi.dataset.export.object_exists", return_value=False
    ):
        result = build_snapshot_sync(snapshot["id"])

    updated = result["snapshot"]
    assert updated["status"] == "ready"
    assert updated["clip_count"] == 1
    assert updated["oss_x_uri"] == x_oss_key(snapshot["id"])
    assert updated["oss_y_uri"] == y_oss_key(snapshot["id"])
    assert updated["oss_manifest_uri"] == package_oss_key(snapshot["id"])
    assert updated["ready_at"]
    print("OK build_snapshot_sync -> ready")

    x_key = x_oss_key(snapshot["id"])
    y_key = y_oss_key(snapshot["id"])
    meta_key = meta_oss_key(snapshot["id"])
    pkg_key = package_oss_key(snapshot["id"])
    assert x_key in _uploads
    assert y_key in _uploads
    assert parsed_oss_key(snapshot["id"]) in _uploads
    assert meta_key in _uploads
    assert pkg_key in _upload_bytes
    with zipfile.ZipFile(io.BytesIO(_upload_bytes[pkg_key])) as zf:
        names = set(zf.namelist())
        assert "特征.jsonl" in names
        assert "目标.jsonl" in names
        assert "解析数据.jsonl" in names
        assert "meta.json" in names
        assert "README.txt" in names
    print("OK dataset.zip contains features + targets + parsed + meta")
    x_lines = [ln for ln in _uploads[x_key].splitlines() if ln.strip()]
    y_lines = [ln for ln in _uploads[y_key].splitlines() if ln.strip()]
    parsed_lines = [ln for ln in _uploads[parsed_oss_key(snapshot["id"])].splitlines() if ln.strip()]
    assert len(x_lines) == 1
    assert len(y_lines) == 1
    assert len(parsed_lines) == 1
    x_row = json.loads(x_lines[0])
    y_row = json.loads(y_lines[0])
    parsed_row = json.loads(parsed_lines[0])
    assert x_row["clip_id"] == clip_id
    assert y_row["clip_id"] == clip_id
    assert parsed_row["clip_id"] == clip_id
    assert len(parsed_row.get("frames") or []) == 1
    assert y_row["y_json"]["L1.1.day_period"] == "morning"
    print("OK OSS 特征/目标 + meta uploaded")

    failed_snapshot = create_snapshot(
        f"m43_empty_{suffix}",
        filter_json={"review_status": "reviewed", "clip_ids": ["sha256:missing"]},
    )
    with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text), patch(
        "hmi.dataset.export.put_object_bytes", side_effect=_mock_put_object_bytes
    ), patch("hmi.dataset.export.object_exists", return_value=False):
        try:
            build_snapshot_sync(failed_snapshot["id"])
            print("FAIL empty build should raise")
            raise SystemExit(1)
        except ValueError:
            pass
    failed = get_snapshot(failed_snapshot["id"])
    assert failed is not None
    assert failed["status"] == "failed"
    assert failed["error_message"]
    print("OK empty assemble -> failed")

    retry_snapshot = create_snapshot(
        f"m43_retry_{suffix}",
        filter_json={"review_status": "reviewed", "clip_ids": [clip_id]},
    )
    update_to_failed = get_snapshot(retry_snapshot["id"])
    assert update_to_failed is not None

    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True), patch(
        "hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text
    ), patch("hmi.dataset.export.put_object_bytes", side_effect=_mock_put_object_bytes), patch(
        "hmi.dataset.export.object_exists", return_value=False
    ):
        build_snapshot_sync(retry_snapshot["id"])
    ready = get_snapshot(retry_snapshot["id"])
    assert ready is not None
    assert ready["status"] == "ready", ready
    print("OK retry build -> ready")

    print("\nAll M4.3 checks passed.")


if __name__ == "__main__":
    main()
