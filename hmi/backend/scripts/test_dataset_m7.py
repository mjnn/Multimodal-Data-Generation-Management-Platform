"""M7 smoke test: export preset, build_report, meta.json schema, dataset_ready preview."""

from __future__ import annotations

import io
import json
import os
import sys
import uuid
import zipfile
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m7-smoke-at-least-32-chars")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.dataset.assemble import assemble_snapshot_rows, build_report_from_skipped
from hmi.dataset.build import build_snapshot_sync
from hmi.dataset.export import SCHEMA_VERSION, build_dataset_package_bytes, export_xy_to_oss
from hmi.local import store
from hmi.main import app
from hmi.review_db import create_review

_uploads: dict[str, str] = {}


def _mock_put_object_text(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


def _mock_put_object_bytes(key: str, payload: bytes, *, content_type: str = "application/zip") -> None:
    _uploads[key.lstrip("/")] = payload.decode("latin-1")


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


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


def _sync_build(snapshot_id: str) -> None:
    with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text), patch(
        "hmi.dataset.export.put_object_bytes", side_effect=_mock_put_object_bytes
    ):
        build_snapshot_sync(snapshot_id)


def main() -> None:
    ensure_schema()
    _uploads.clear()
    suffix = uuid.uuid4().hex[:8]
    manager_name = f"m7_manager_{suffix}"

    if get_user_by_username(manager_name) is None:
        create_user(manager_name, "managerpass123", roles=["dataset_manager"])

    clip_id = f"sha256:m7_{suffix}"
    run_id = str(uuid.uuid4())
    ds = "20260730"
    _seed_clip(clip_id=clip_id, run_id=run_id, ds=ds)
    create_review(clip_id, run_id, labels_json={"L1.1.day_period": "morning"}, review_status="reviewed")

    client = TestClient(app)
    manager_h = {"Authorization": f"Bearer {_login(client, manager_name, 'managerpass123')}"}

    preview = client.post(
        "/api/datasets/preview",
        headers=manager_h,
        json={"name": "preview", "export_preset": "minimal"},
    )
    assert preview.status_code == 200, preview.text
    prev = preview.json()
    assert "dataset_ready_count" in prev, prev
    assert prev["export_preset"] == "minimal"
    print("OK preview returns dataset_ready_count and export_preset")

    with patch("hmi.dataset.router.enqueue_build", side_effect=_sync_build):
        created = client.post(
            "/api/datasets",
            headers=manager_h,
            json={"name": f"m7_minimal_{suffix}", "export_preset": "minimal"},
        )
    assert created.status_code == 201, created.text
    snapshot_id = created.json()["id"]

    detail = client.get(f"/api/datasets/{snapshot_id}", headers=manager_h)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "ready", body
    assert body.get("build_report") is not None
    assert body.get("export_preset") == "minimal"
    print("OK GET detail includes build_report and export_preset")

    meta_key = f"datasets/{snapshot_id}/meta.json"
    assert meta_key in _uploads, list(_uploads.keys())
    meta = json.loads(_uploads[meta_key])
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["export_preset"] == "minimal"
    assert "build_report" in meta
    assert "filter_snapshot" in meta
    assert "embedding_summary" in meta
    assert meta["line_count"] >= meta["clip_count"]
    print("OK meta.json has schema_version, build_report, filter_snapshot, embedding_summary")

    package_key = f"datasets/{snapshot_id}/dataset.zip"
    assert package_key in _uploads
    zip_bytes = _uploads[package_key].encode("latin-1")
    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        assert "特征.jsonl" in names
        assert "目标.jsonl" in names
        assert "meta.json" in names
        parsed_binaries = [n for n in names if n.startswith("clips/") and "/parsed/" in n]
        assert len(parsed_binaries) == 0, f"minimal should skip parsed binaries: {parsed_binaries}"
    print("OK minimal preset zip excludes parsed binaries")

    assembly = assemble_snapshot_rows({"review_status": "reviewed"})
    report = build_report_from_skipped(assembly.skipped, warnings=assembly.warnings)
    assert report["skipped_by_reason"] == assembly.build_report.get("skipped_by_reason", {})
    print("OK build_report.skipped_by_reason consistent")

    full_zip = build_dataset_package_bytes(
        snapshot_id="test",
        x_body='{"clip_id":"a","run_id":"b","x_json":{}}\n',
        y_body='{"clip_id":"a","run_id":"b","y_json":{}}\n',
        meta_body='{"schema_version":"1.0"}',
        export_preset="full",
        parsed_body='{"clip_id":"a"}\n',
        parsed_files=[("clips/x/runs/y/parsed/manifest.json", b"{}")],
    )
    with zipfile.ZipFile(io.BytesIO(full_zip), "r") as zf:
        assert "解析数据.jsonl" in zf.namelist()
        assert any(n.startswith("clips/") for n in zf.namelist())
    print("OK full preset zip includes parsed index and clip files")

    print("\nM7 backend tests passed.")


if __name__ == "__main__":
    main()
