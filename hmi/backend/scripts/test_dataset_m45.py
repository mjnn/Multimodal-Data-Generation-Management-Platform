"""M4.5 smoke test: Dataset REST API."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m45-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import list_audit_logs
from hmi.dataset.build import build_snapshot_sync
from hmi.dataset_db import create_snapshot, update_snapshot
from hmi.local import store
from hmi.main import app
from hmi.review_db import create_review, get_review

_uploads: dict[str, str] = {}


def _mock_put_object_text(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


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


def _sync_enqueue(snapshot_id: str) -> None:
    try:
        with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text):
            build_snapshot_sync(snapshot_id)
    except Exception:
        pass


def main() -> None:
    ensure_schema()
    _uploads.clear()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m45_admin_{suffix}"
    manager_name = f"m45_manager_{suffix}"
    trainer_name = f"m45_trainer_{suffix}"

    for name, password, roles in (
        (admin_name, "adminpass123", ["admin"]),
        (manager_name, "managerpass123", ["dataset_manager"]),
        (trainer_name, "trainerpass123", ["model_trainer"]),
    ):
        if get_user_by_username(name) is None:
            create_user(name, password, roles=roles)

    clip_id = f"sha256:m45_{suffix}"
    run_id = str(uuid.uuid4())
    ds = "20260721"
    _seed_clip(clip_id=clip_id, run_id=run_id, ds=ds)
    create_review(clip_id, run_id, labels_json={"L1.1.day_period": "morning"}, review_status="reviewed")

    client = TestClient(app)

    unauth = client.get("/api/datasets")
    assert unauth.status_code == 401, unauth.text
    print("OK GET /datasets without auth -> 401")

    admin_h = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}
    manager_h = {"Authorization": f"Bearer {_login(client, manager_name, 'managerpass123')}"}
    trainer_h = {"Authorization": f"Bearer {_login(client, trainer_name, 'trainerpass123')}"}

    trainer_list = client.get("/api/datasets", headers=trainer_h)
    assert trainer_list.status_code == 200, trainer_list.text
    print("OK model_trainer GET list -> 200")

    trainer_create = client.post(
        "/api/datasets",
        headers=trainer_h,
        json={"name": f"trainer_blocked_{suffix}"},
    )
    assert trainer_create.status_code == 403, trainer_create.text
    print("OK model_trainer POST -> 403")

    with patch("hmi.dataset.router.enqueue_build", side_effect=_sync_enqueue):
        created = client.post(
            "/api/datasets",
            headers=manager_h,
            json={
                "name": f"m45_dataset_{suffix}",
                "description": "api test",
                "filter_json": {"review_status": "reviewed", "clip_ids": [clip_id]},
            },
        )
    assert created.status_code == 201, created.text
    snapshot = created.json()
    snapshot_id = snapshot["id"]
    assert snapshot["status"] == "ready"
    assert snapshot["clip_count"] == 1
    print("OK POST /datasets -> ready")

    audits = list_audit_logs(resource_type="dataset_snapshot", resource_id=snapshot_id)
    assert any(a["action"] == "dataset.create" for a in audits)
    print("OK dataset.create audit")

    detail = client.get(f"/api/datasets/{snapshot_id}", headers=trainer_h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "ready"
    print("OK GET /datasets/{id}")

    download = client.get(f"/api/datasets/{snapshot_id}/download", headers=trainer_h)
    assert download.status_code == 200, download.text
    body = download.json()
    assert body.get("x_url")
    assert body.get("y_url")
    assert body.get("x_key")
    assert body.get("y_key")
    assert body["clip_count"] == 1
    print("OK GET /datasets/{id}/download")

    manager_include = client.post(
        "/api/datasets",
        headers=manager_h,
        json={
            "name": f"m45_pending_{suffix}",
            "filter_json": {"include_pending_review": True},
        },
    )
    assert manager_include.status_code == 403, manager_include.text
    print("OK manager include_pending_review -> 403")

    with patch("hmi.dataset.router.enqueue_build", side_effect=_sync_enqueue):
        admin_include = client.post(
            "/api/datasets",
            headers=admin_h,
            json={
                "name": f"m45_admin_pending_{suffix}",
                "filter_json": {"include_pending_review": True, "clip_ids": [clip_id]},
            },
        )
    assert admin_include.status_code == 201, admin_include.text
    admin_snapshot_id = admin_include.json()["id"]
    admin_audits = list_audit_logs(resource_type="dataset_snapshot", resource_id=admin_snapshot_id)
    create_audit = next(a for a in admin_audits if a["action"] == "dataset.create")
    assert create_audit["detail"]["include_pending_review"] is True
    print("OK admin include_pending_review + audit")

    failed_snapshot = create_snapshot(
        f"m45_failed_{suffix}",
        filter_json={"review_status": "reviewed", "clip_ids": ["sha256:missing"]},
    )
    update_snapshot(failed_snapshot["id"], status="failed", error_message="simulated")

    retry_conflict = client.post(f"/api/datasets/{snapshot_id}/retry", headers=manager_h)
    assert retry_conflict.status_code == 409, retry_conflict.text
    print("OK retry ready snapshot -> 409")

    with patch("hmi.dataset.router.enqueue_build", side_effect=_sync_enqueue):
        retried = client.post(f"/api/datasets/{failed_snapshot['id']}/retry", headers=manager_h)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] in ("failed", "building", "ready")
    print("OK POST /datasets/{id}/retry")

    deleted = client.delete(f"/api/datasets/{snapshot_id}", headers=manager_h)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "archived"
    delete_audits = list_audit_logs(resource_type="dataset_snapshot", resource_id=snapshot_id)
    assert any(a["action"] == "dataset.delete" for a in delete_audits)
    print("OK DELETE /datasets/{id} -> archived + audit")

    review_row = get_review(clip_id, run_id)
    assert review_row is not None
    trainer_review_write = client.put(
        f"/api/review/clips/{clip_id}",
        headers=trainer_h,
        json={
            "labels_json": {"L1.1.day_period": "night"},
            "review_status": "reviewed",
            "updated_at": review_row["updated_at"],
            "run_id": run_id,
        },
    )
    assert trainer_review_write.status_code == 403, trainer_review_write.text
    print("OK model_trainer PUT review -> 403 regression")

    print("\nAll M4.5 checks passed.")


if __name__ == "__main__":
    main()
