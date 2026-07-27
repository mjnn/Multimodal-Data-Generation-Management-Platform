"""M3 milestone exit integration test (M3.6).

Flow: enqueue → queue pending → edit → reviewed → audit → 409 → reopen → trainer 403.
Covers PRD slices S3, C3, C4, N5, N6.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m3-exit-at-least-32-chars")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import list_audit_logs
from hmi.local import store
from hmi.main import app


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _seed_local_clip(*, clip_id: str, run_id: str, ds: str) -> None:
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


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m3_admin_{suffix}"
    reviewer_name = f"m3_reviewer_{suffix}"
    trainer_name = f"m3_trainer_{suffix}"

    for name, password, roles in (
        (admin_name, "adminpass123", ["admin"]),
        (reviewer_name, "reviewpass123", ["reviewer"]),
        (trainer_name, "trainerpass123", ["model_trainer"]),
    ):
        if get_user_by_username(name) is None:
            create_user(name, password, roles=roles)

    clip_id = f"sha256:m3_{suffix}"
    run_id = str(uuid.uuid4())
    ds = "20260721"
    _seed_local_clip(clip_id=clip_id, run_id=run_id, ds=ds)

    client = TestClient(app)
    admin_h = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}
    reviewer_h = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}
    trainer_h = {"Authorization": f"Bearer {_login(client, trainer_name, 'trainerpass123')}"}

    # C3: admin enqueue (simulates Job3-complete clip entering queue)
    enq = client.post(
        "/api/review/enqueue",
        headers=admin_h,
        json={"clip_ids": [clip_id]},
    )
    assert enq.status_code == 200, enq.text
    assert enq.json()["summary"]["created"] == 1
    print("OK C3 admin enqueue -> created")

    # S3: pending visible in queue
    queue = client.get("/api/review/queue?status=pending_review", headers=reviewer_h)
    assert queue.status_code == 200, queue.text
    pending_items = queue.json()["items"]
    match = next((i for i in pending_items if i["clip_id"] == clip_id and i["run_id"] == run_id), None)
    assert match is not None
    assert match["review_status"] == "pending_review"
    review_id = match["id"]
    print("OK S3 queue pending visible")

    detail = client.get(f"/api/review/clips/{clip_id}?run_id={run_id}", headers=reviewer_h)
    assert detail.status_code == 200, detail.text
    review = detail.json()
    assert review["labels_json"].get("L1.1.day_period") == "morning"
    print("OK GET review detail")

    # C4 + S3: reviewer edit and mark reviewed
    save = client.put(
        f"/api/review/clips/{clip_id}",
        headers=reviewer_h,
        json={
            "labels_json": {"L1.1.day_period": "night", "L1.1.is_holiday": True},
            "review_status": "reviewed",
            "updated_at": review["updated_at"],
            "run_id": run_id,
        },
    )
    assert save.status_code == 200, save.text
    saved = save.json()
    assert saved["review_status"] == "reviewed"
    assert saved["reviewer_id"]
    assert saved["reviewed_at"]
    assert saved["labels_json"]["L1.1.day_period"] == "night"
    print("OK C4/S3 reviewer save reviewed")

    audit_logs = list_audit_logs(resource_type="clip_label_review", resource_id=review_id)
    assert any(l["action"] == "clip.review" for l in audit_logs)
    print("OK C4 audit_log clip.review")

    # N5: stale updated_at -> 409, no extra audit
    count_before = len(audit_logs)
    conflict = client.put(
        f"/api/review/clips/{clip_id}",
        headers=reviewer_h,
        json={
            "labels_json": saved["labels_json"],
            "review_status": "reviewed",
            "updated_at": "1970-01-01T00:00:00+00:00",
            "run_id": run_id,
        },
    )
    assert conflict.status_code == 409, conflict.text
    assert len(list_audit_logs(resource_type="clip_label_review", resource_id=review_id)) == count_before
    print("OK N5 concurrent stale PUT -> 409")

    # N6: model_trainer write forbidden
    trainer_put = client.put(
        f"/api/review/clips/{clip_id}",
        headers=trainer_h,
        json={
            "labels_json": {"L1.1.day_period": "morning"},
            "review_status": "pending_review",
            "updated_at": saved["updated_at"],
            "run_id": run_id,
        },
    )
    assert trainer_put.status_code == 403, trainer_put.text
    print("OK N6 model_trainer PUT -> 403")

    # S3: reopen back to pending
    reopen = client.post(
        f"/api/review/clips/{clip_id}/reopen",
        headers=reviewer_h,
        json={"run_id": run_id},
    )
    assert reopen.status_code == 200, reopen.text
    assert reopen.json()["review_status"] == "pending_review"
    assert any(
        l["action"] == "clip.reopen"
        for l in list_audit_logs(resource_type="clip_label_review", resource_id=review_id)
    )
    print("OK S3 reopen -> pending_review + clip.reopen audit")

    # reviewer cannot write taxonomy (cross-check from M3 test matrix)
    blocked = client.post(
        "/api/taxonomy/versions",
        headers=reviewer_h,
        json={"version_code": f"m3_blocked_{suffix}"},
    )
    assert blocked.status_code == 403, blocked.text
    print("OK reviewer POST taxonomy -> 403")

    reviewed_queue = client.get("/api/review/queue?status=reviewed", headers=reviewer_h)
    assert reviewed_queue.status_code == 200
    assert not any(
        i["clip_id"] == clip_id and i["run_id"] == run_id for i in reviewed_queue.json()["items"]
    )
    print("OK queue status after reopen")

    print("\nAll M3 exit checks passed.")


if __name__ == "__main__":
    main()
