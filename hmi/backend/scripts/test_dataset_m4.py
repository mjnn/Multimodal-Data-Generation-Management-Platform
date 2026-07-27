"""M4 milestone exit integration test (M4.7).

Flow: reviewed-only snapshot → OSS manifest → trainer read/download →
pending excluded (N4) → audit → trainer/reviewer write 403 → archive.
Covers PRD slices S4, S5, C5, C6 (local), C7, N4.
"""

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

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m4-exit-at-least-32-chars")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import list_audit_logs
from hmi.dataset.build import build_snapshot_sync
from hmi.dataset.export import manifest_oss_key
from hmi.local import store
from hmi.main import app
from hmi.review_db import create_review

_uploads: dict[str, str] = {}


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _mock_put_object_text(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


def _seed_clip(*, clip_id: str, run_id: str, ds: str, vector: list[float]) -> None:
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
        ) VALUES (?, ?, ?, 'frame', 'cam0:0', 1000000000, ?, ?)
        """,
        (clip_id, run_id, ds, json.dumps(vector), len(vector)),
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
    admin_name = f"m4_admin_{suffix}"
    manager_name = f"m4_manager_{suffix}"
    trainer_name = f"m4_trainer_{suffix}"
    reviewer_name = f"m4_reviewer_{suffix}"

    for name, password, roles in (
        (admin_name, "adminpass123", ["admin"]),
        (manager_name, "managerpass123", ["dataset_manager"]),
        (trainer_name, "trainerpass123", ["model_trainer"]),
        (reviewer_name, "reviewpass123", ["reviewer"]),
    ):
        if get_user_by_username(name) is None:
            create_user(name, password, roles=roles)

    ds = "20260721"
    reviewed_clip = f"sha256:m4_reviewed_{suffix}"
    pending_clip = f"sha256:m4_pending_{suffix}"
    reviewed_run = str(uuid.uuid4())
    pending_run = str(uuid.uuid4())

    _seed_clip(clip_id=reviewed_clip, run_id=reviewed_run, ds=ds, vector=[1.0, 0.0])
    _seed_clip(clip_id=pending_clip, run_id=pending_run, ds=ds, vector=[0.0, 1.0])
    create_review(
        reviewed_clip,
        reviewed_run,
        labels_json={"L1.1.day_period": "morning"},
        review_status="reviewed",
    )
    create_review(
        pending_clip,
        pending_run,
        labels_json={"L1.1.day_period": "night"},
        review_status="pending_review",
    )

    client = TestClient(app)
    admin_h = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}
    manager_h = {"Authorization": f"Bearer {_login(client, manager_name, 'managerpass123')}"}
    trainer_h = {"Authorization": f"Bearer {_login(client, trainer_name, 'trainerpass123')}"}
    reviewer_h = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}

    reviewer_list = client.get("/api/datasets", headers=reviewer_h)
    assert reviewer_list.status_code == 403, reviewer_list.text
    print("OK reviewer GET /datasets -> 403")

    with patch("hmi.dataset.router.enqueue_build", side_effect=_sync_enqueue):
        created = client.post(
            "/api/datasets",
            headers=manager_h,
            json={
                "name": f"m4_exit_{suffix}",
                "description": "milestone exit",
                "filter_json": {
                    "review_status": "reviewed",
                    "clip_ids": [reviewed_clip, pending_clip],
                },
            },
        )
    assert created.status_code == 201, created.text
    snapshot = created.json()
    snapshot_id = snapshot["id"]
    assert snapshot["status"] == "ready"
    assert snapshot["clip_count"] == 1
    assert snapshot["mc_table_name"] is None
    print("OK S4/C5 manager create -> ready (reviewed only)")

    audits = list_audit_logs(resource_type="dataset_snapshot", resource_id=snapshot_id)
    assert any(a["action"] == "dataset.create" for a in audits)
    print("OK dataset.create audit")

    manifest_key = manifest_oss_key(snapshot_id)
    assert manifest_key in _uploads
    lines = [ln for ln in _uploads[manifest_key].splitlines() if ln.strip()]
    assert len(lines) == snapshot["clip_count"] == 1
    row = json.loads(lines[0])
    assert row["clip_id"] == reviewed_clip
    assert row["run_id"] == reviewed_run
    assert row["y_json"]["L1.1.day_period"] == "morning"
    x = row["x_json"]
    assert x["schema"] == "frame_embeddings_v1"
    assert x["items"][0]["vector"] == [1.0, 0.0]
    print("OK C6 OSS manifest rows == clip_count with x_json/y_json")

    clip_ids_in_manifest = {json.loads(ln)["clip_id"] for ln in lines}
    assert pending_clip not in clip_ids_in_manifest
    print("OK N4 pending clip excluded by default")

    trainer_list = client.get("/api/datasets", headers=trainer_h)
    assert trainer_list.status_code == 200, trainer_list.text
    assert any(item["id"] == snapshot_id for item in trainer_list.json()["items"])
    print("OK S5 trainer list -> 200")

    trainer_detail = client.get(f"/api/datasets/{snapshot_id}", headers=trainer_h)
    assert trainer_detail.status_code == 200, trainer_detail.text
    assert trainer_detail.json()["status"] == "ready"
    print("OK S5 trainer detail -> 200")

    trainer_download = client.get(f"/api/datasets/{snapshot_id}/download", headers=trainer_h)
    assert trainer_download.status_code == 200, trainer_download.text
    assert trainer_download.json().get("url")
    assert trainer_download.json()["clip_count"] == 1
    print("OK C7 trainer download manifest URL")

    trainer_create = client.post(
        "/api/datasets",
        headers=trainer_h,
        json={"name": f"m4_trainer_blocked_{suffix}"},
    )
    assert trainer_create.status_code == 403, trainer_create.text
    print("OK C7 trainer POST /datasets -> 403")

    trainer_review = client.put(
        f"/api/review/clips/{reviewed_clip}",
        headers=trainer_h,
        json={
            "labels_json": {"L1.1.day_period": "noon"},
            "review_status": "reviewed",
            "updated_at": "1970-01-01T00:00:00+00:00",
            "run_id": reviewed_run,
        },
    )
    assert trainer_review.status_code == 403, trainer_review.text
    print("OK C7 trainer PUT review -> 403")

    trainer_taxonomy = client.post(
        "/api/taxonomy/versions",
        headers=trainer_h,
        json={"version_code": f"m4_blocked_{suffix}"},
    )
    assert trainer_taxonomy.status_code == 403, trainer_taxonomy.text
    print("OK C7 trainer POST taxonomy -> 403")

    with patch("hmi.dataset.router.enqueue_build", side_effect=_sync_enqueue):
        admin_include = client.post(
            "/api/datasets",
            headers=admin_h,
            json={
                "name": f"m4_admin_include_{suffix}",
                "filter_json": {
                    "include_pending_review": True,
                    "clip_ids": [reviewed_clip, pending_clip],
                },
            },
        )
    assert admin_include.status_code == 201, admin_include.text
    admin_snapshot_id = admin_include.json()["id"]
    assert admin_include.json()["clip_count"] == 2
    admin_audits = list_audit_logs(resource_type="dataset_snapshot", resource_id=admin_snapshot_id)
    create_audit = next(a for a in admin_audits if a["action"] == "dataset.create")
    assert create_audit["detail"]["include_pending_review"] is True
    admin_manifest = _uploads.get(manifest_oss_key(admin_snapshot_id), "")
    admin_clip_ids = {json.loads(ln)["clip_id"] for ln in admin_manifest.splitlines() if ln.strip()}
    assert reviewed_clip in admin_clip_ids and pending_clip in admin_clip_ids
    print("OK N4 admin include_pending -> 2 clips + audit flag")

    deleted = client.delete(f"/api/datasets/{snapshot_id}", headers=manager_h)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "archived"
    assert any(
        a["action"] == "dataset.delete"
        for a in list_audit_logs(resource_type="dataset_snapshot", resource_id=snapshot_id)
    )
    archived_list = client.get("/api/datasets", headers=manager_h)
    assert not any(item["id"] == snapshot_id for item in archived_list.json()["items"])
    print("OK archive + dataset.delete audit + hidden from list")

    print("\nAll M4 exit checks passed.")


if __name__ == "__main__":
    main()
