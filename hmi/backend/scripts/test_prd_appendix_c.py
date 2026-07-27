"""M5.1 — PRD appendix C full integration (C1–C8, N1–N6).

Single exit script after M1–M4 milestone tests. Local mode; C6 OSS only (cloud MC → H-1).
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

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m5-appendix-c-at-least-32b")
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


def _mock_put(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


def _seed_clip(*, clip_id: str, run_id: str, ds: str) -> None:
    labels_payload = {
        "values": {"L1.1.day_period": {"value": "morning"}, "L1.1.is_holiday": {"value": False}}
    }
    store.execute(
        "INSERT OR REPLACE INTO dim_clip (clip_id, clip_dir_name, active_run_id) VALUES (?, ?, ?)",
        (clip_id, clip_id[:16], run_id),
    )
    store.execute(
        "INSERT OR REPLACE INTO pipeline_run (run_id, clip_id, ds, status) VALUES (?, ?, ?, 'completed')",
        (run_id, clip_id, ds),
    )
    store.execute(
        "INSERT OR REPLACE INTO pipeline_step (run_id, ds, step_id, status) VALUES (?, ?, 'job3_label', 'success')",
        (run_id, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_image_label (
          clip_id, run_id, ds, frame_id, timestamp_ns, labels_json
        ) VALUES (?, ?, ?, 'cam0:0', 1000000000, ?)
        """,
        (clip_id, run_id, ds, json.dumps(labels_payload, ensure_ascii=False)),
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
    try:
        with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put):
            build_snapshot_sync(snapshot_id)
    except Exception:
        pass


def main() -> None:
    ensure_schema()
    _uploads.clear()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m5_admin_{suffix}"
    reviewer_name = f"m5_reviewer_{suffix}"
    manager_name = f"m5_manager_{suffix}"
    trainer_name = f"m5_trainer_{suffix}"

    for name, password, roles in (
        (admin_name, "adminpass123", ["admin"]),
        (reviewer_name, "reviewpass123", ["reviewer"]),
        (manager_name, "managerpass123", ["dataset_manager"]),
        (trainer_name, "trainerpass123", ["model_trainer"]),
    ):
        if get_user_by_username(name) is None:
            create_user(name, password, roles=roles)

    client = TestClient(app)

    assert client.get("/api/clips").status_code == 401
    print("OK N1 unauthenticated /api/clips -> 401")

    admin_h = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}
    reviewer_h = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}
    manager_h = {"Authorization": f"Bearer {_login(client, manager_name, 'managerpass123')}"}
    trainer_h = {"Authorization": f"Bearer {_login(client, trainer_name, 'trainerpass123')}"}

    assert client.get("/api/clips", headers=admin_h).status_code == 200
    assert client.get("/api/search/clusters", headers=admin_h, params={"keyword": ""}).status_code == 200
    print("OK C8 authenticated clip browse + search")

    new_rev = f"m5_new_reviewer_{suffix}"
    created_user = client.post(
        "/api/admin/users",
        headers=admin_h,
        json={"username": new_rev, "password": "reviewpass123", "roles": ["reviewer"]},
    )
    assert created_user.status_code == 201, created_user.text
    new_rev_h = {"Authorization": f"Bearer {_login(client, new_rev, 'reviewpass123')}"}
    assert client.get("/api/auth/me", headers=new_rev_h).json()["user"]["roles"] == ["reviewer"]
    assert client.get("/api/oss/info", headers=new_rev_h).status_code == 403
    assert client.get("/api/clips", headers=new_rev_h).status_code == 200
    print("OK C1 admin create reviewer + role-scoped access")

    assert client.post(
        "/api/admin/users",
        headers=reviewer_h,
        json={"username": f"blocked_{suffix}", "password": "x", "roles": ["reviewer"]},
    ).status_code == 403
    print("OK N2 reviewer POST /admin/users -> 403")

    base = client.post(
        "/api/taxonomy/versions",
        headers=admin_h,
        json={"version_code": f"m5_v1_{suffix}", "import_yaml": True},
    )
    assert base.status_code == 201, base.text
    base_id = base.json()["id"]
    draft = client.post(
        f"/api/taxonomy/versions/{base_id}/clone",
        headers=admin_h,
        json={"version_code": f"m5_v2_{suffix}"},
    )
    assert draft.status_code == 201, draft.text
    draft_id = draft.json()["id"]
    tree = client.get(f"/api/taxonomy/versions/{draft_id}/tree", headers=admin_h).json()
    nodes = tree["nodes"]
    edited_name = f"日时段-M5-{suffix}"
    payload_nodes = [
        {
            "label_id": n["label_id"],
            "level_code": n["level_code"],
            "level_name": n.get("level_name"),
            "name": edited_name if n["label_id"] == "L1.1.day_period" else n["name"],
            "definition": n.get("definition"),
            "dtype": n.get("dtype"),
            "value_schema": n.get("value_schema"),
            "sort_order": n.get("sort_order", 0),
            "is_active": n.get("is_active", True),
        }
        for n in nodes
    ]
    assert client.put(
        f"/api/taxonomy/versions/{draft_id}/nodes",
        headers=admin_h,
        json={"nodes": payload_nodes},
    ).status_code == 200

    with (
        patch("hmi.taxonomy.export.put_object_text", side_effect=_mock_put),
        patch("hmi.taxonomy.export.get_object_json", return_value={"action": "idle"}),
        patch("hmi.taxonomy.export.get_settings", return_value={"oss_bucket": "test-bucket"}),
    ):
        published = client.post(
            f"/api/taxonomy/versions/{draft_id}/publish",
            headers=admin_h,
        )
    assert published.status_code == 200, published.text
    pub_id = published.json()["id"]

    tax_v2 = client.get("/api/label-taxonomy", headers=reviewer_h, params={"version_id": pub_id})
    assert tax_v2.status_code == 200, tax_v2.text
    found = False
    for level in tax_v2.json():
        for child in level.get("children") or []:
            if child.get("id") == "L1.1.day_period" and child.get("name") == edited_name:
                found = True
    assert found, "published v2 label name not visible via label-taxonomy"
    print("OK C2 taxonomy v1->v2 publish + label-taxonomy version_id")

    pub_tree = client.get(f"/api/taxonomy/versions/{pub_id}/tree", headers=admin_h).json()["nodes"]
    n3_nodes = [
        {
            "label_id": n["label_id"],
            "level_code": n["level_code"],
            "level_name": n.get("level_name"),
            "name": n["name"],
            "definition": n.get("definition"),
            "dtype": n.get("dtype"),
            "value_schema": n.get("value_schema"),
            "sort_order": n.get("sort_order", 0),
            "is_active": n.get("is_active", True),
        }
        for n in pub_tree
    ]
    assert client.put(
        f"/api/taxonomy/versions/{pub_id}/nodes",
        headers=admin_h,
        json={"nodes": n3_nodes},
    ).status_code == 409
    print("OK N3 PUT published taxonomy nodes -> 409")

    ds = "20260721"
    reviewed_clip = f"sha256:m5_r_{suffix}"
    pending_clip = f"sha256:m5_p_{suffix}"
    reviewed_run = str(uuid.uuid4())
    pending_run = str(uuid.uuid4())
    _seed_clip(clip_id=reviewed_clip, run_id=reviewed_run, ds=ds)
    _seed_clip(clip_id=pending_clip, run_id=pending_run, ds=ds)

    enq = client.post(
        "/api/review/enqueue",
        headers=admin_h,
        json={"clip_ids": [reviewed_clip]},
    )
    assert enq.status_code == 200, enq.text
    assert enq.json()["summary"]["created"] == 1
    queue = client.get("/api/review/queue?status=pending_review", headers=reviewer_h)
    match = next(
        i for i in queue.json()["items"] if i["clip_id"] == reviewed_clip and i["run_id"] == reviewed_run
    )
    assert match["review_status"] == "pending_review"
    assert match["labels_json"].get("L1.1.day_period") == "morning"
    review_id = match["id"]
    print("OK C3 enqueue -> pending_review with AI labels")

    review = client.get(
        f"/api/review/clips/{reviewed_clip}?run_id={reviewed_run}",
        headers=reviewer_h,
    ).json()

    saved = client.put(
        f"/api/review/clips/{reviewed_clip}",
        headers=reviewer_h,
        json={
            "labels_json": {"L1.1.day_period": "night"},
            "review_status": "reviewed",
            "updated_at": review["updated_at"],
            "run_id": reviewed_run,
        },
    ).json()
    assert saved["review_status"] == "reviewed"
    assert any(
        l["action"] == "clip.review"
        for l in list_audit_logs(resource_type="clip_label_review", resource_id=review_id)
    )
    print("OK C4 reviewer save reviewed + audit")

    audit_before = len(list_audit_logs(resource_type="clip_label_review", resource_id=review_id))
    assert client.put(
        f"/api/review/clips/{reviewed_clip}",
        headers=reviewer_h,
        json={
            "labels_json": saved["labels_json"],
            "review_status": "reviewed",
            "updated_at": "1970-01-01T00:00:00+00:00",
            "run_id": reviewed_run,
        },
    ).status_code == 409
    assert len(list_audit_logs(resource_type="clip_label_review", resource_id=review_id)) == audit_before
    print("OK N5 stale review PUT -> 409")

    assert client.put(
        f"/api/review/clips/{reviewed_clip}",
        headers=trainer_h,
        json={
            "labels_json": {"L1.1.day_period": "noon"},
            "review_status": "reviewed",
            "updated_at": saved["updated_at"],
            "run_id": reviewed_run,
        },
    ).status_code == 403
    print("OK N6 trainer PUT review -> 403")

    create_review(
        pending_clip,
        pending_run,
        labels_json={"L1.1.day_period": "pending"},
        review_status="pending_review",
    )

    with patch("hmi.dataset.router.enqueue_build", side_effect=_sync_build):
        snap_resp = client.post(
            "/api/datasets",
            headers=manager_h,
            json={
                "name": f"m5_snap_{suffix}",
                "filter_json": {
                    "review_status": "reviewed",
                    "clip_ids": [reviewed_clip, pending_clip],
                },
            },
        )
    assert snap_resp.status_code == 201, snap_resp.text
    snapshot = snap_resp.json()
    snapshot_id = snapshot["id"]
    assert snapshot["status"] == "ready"
    assert snapshot["clip_count"] == 1
    print("OK C5/N4 dataset reviewed-only (pending excluded)")

    manifest = _uploads.get(manifest_oss_key(snapshot_id), "")
    lines = [ln for ln in manifest.splitlines() if ln.strip()]
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["clip_id"] == reviewed_clip and row["x_json"] and row["y_json"]
    print("OK C6 OSS manifest rows == clip_count with x_json/y_json (local)")

    assert client.get("/api/datasets", headers=trainer_h).status_code == 200
    assert client.get(f"/api/datasets/{snapshot_id}", headers=trainer_h).status_code == 200
    assert client.get(f"/api/datasets/{snapshot_id}/download", headers=trainer_h).status_code == 200
    assert client.post("/api/datasets", headers=trainer_h, json={"name": "x"}).status_code == 403
    assert client.post(
        "/api/taxonomy/versions",
        headers=trainer_h,
        json={"version_code": f"m5_trainer_{suffix}"},
    ).status_code == 403
    print("OK C7 trainer read/download; write dataset/taxonomy forbidden")

    print("\nAll PRD appendix C checks passed (C1–C8, N1–N6; C6 cloud MC deferred H-1).")


if __name__ == "__main__":
    main()
