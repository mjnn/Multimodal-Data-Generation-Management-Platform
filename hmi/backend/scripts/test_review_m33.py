"""M3.3 smoke test: Review REST API."""

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

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m33-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.local import store
from hmi.main import app
from hmi.review_db import create_review


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
        "INSERT OR REPLACE INTO pipeline_step (run_id, ds, step_id, status) VALUES (?, ?, 'job3_label', 'success')",
        (run_id, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_image_label (
          clip_id, run_id, ds, frame_id, timestamp_ns, labels_json
        ) VALUES (?, ?, ?, 'cam0:0', 1000000000, ?)
        """,
        (
            clip_id,
            run_id,
            ds,
            json.dumps({"values": {"L1.1.day_period": {"value": "morning"}}}, ensure_ascii=False),
        ),
    )


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m33_admin_{suffix}"
    reviewer_name = f"m33_reviewer_{suffix}"
    trainer_name = f"m33_trainer_{suffix}"

    for name, password, roles in (
        (admin_name, "adminpass123", ["admin"]),
        (reviewer_name, "reviewpass123", ["reviewer"]),
        (trainer_name, "trainerpass123", ["model_trainer"]),
    ):
        if get_user_by_username(name) is None:
            create_user(name, password, roles=roles)

    clip_id = f"sha256:m33_{suffix}"
    run_id = str(uuid.uuid4())
    ds = "20260721"
    _seed_clip(clip_id=clip_id, run_id=run_id, ds=ds)

    labels = {"L1.1.day_period": "morning"}
    review = create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="pending_review",
        ai_source_summary_json={"source": "test"},
    )

    client = TestClient(app)

    unauth = client.get("/api/review/queue")
    assert unauth.status_code == 401, unauth.text
    print("OK GET /queue without auth -> 401")

    reviewer_h = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}
    admin_h = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}
    trainer_h = {"Authorization": f"Bearer {_login(client, trainer_name, 'trainerpass123')}"}

    queue = client.get("/api/review/queue?status=pending_review", headers=reviewer_h)
    assert queue.status_code == 200, queue.text
    body = queue.json()
    assert any(item["id"] == review["id"] for item in body["items"])
    assert body["total"] >= 1
    print("OK GET /queue pending")

    detail = client.get(f"/api/review/clips/{clip_id}?run_id={run_id}", headers=reviewer_h)
    assert detail.status_code == 200, detail.text
    assert detail.json()["labels_json"] == labels
    print("OK GET /clips/{id}")

    trainer_read = client.get(f"/api/review/clips/{clip_id}?run_id={run_id}", headers=trainer_h)
    assert trainer_read.status_code == 200, trainer_read.text
    print("OK model_trainer GET detail -> 200")

    save = client.put(
        f"/api/review/clips/{clip_id}",
        headers=reviewer_h,
        json={
            "labels_json": {"L1.1.day_period": "night"},
            "review_status": "reviewed",
            "updated_at": review["updated_at"],
            "run_id": run_id,
        },
    )
    assert save.status_code == 200, save.text
    saved = save.json()
    assert saved["review_status"] == "reviewed"
    assert saved["labels_json"]["L1.1.day_period"] == "night"
    print("OK PUT save reviewed")

    trainer_put = client.put(
        f"/api/review/clips/{clip_id}",
        headers=trainer_h,
        json={
            "labels_json": labels,
            "review_status": "pending_review",
            "updated_at": saved["updated_at"],
            "run_id": run_id,
        },
    )
    assert trainer_put.status_code == 403, trainer_put.text
    print("OK model_trainer PUT -> 403")

    conflict = client.put(
        f"/api/review/clips/{clip_id}",
        headers=reviewer_h,
        json={
            "labels_json": labels,
            "review_status": "reviewed",
            "updated_at": review["updated_at"],
            "run_id": run_id,
        },
    )
    assert conflict.status_code == 409, conflict.text
    print("OK PUT stale updated_at -> 409")

    reopen = client.post(
        f"/api/review/clips/{clip_id}/reopen",
        headers=reviewer_h,
        json={"run_id": run_id},
    )
    assert reopen.status_code == 200, reopen.text
    assert reopen.json()["review_status"] == "pending_review"
    print("OK POST reopen")

    reviewer_enqueue = client.post(
        "/api/review/enqueue",
        headers=reviewer_h,
        json={"clip_ids": [clip_id]},
    )
    assert reviewer_enqueue.status_code == 403, reviewer_enqueue.text
    print("OK reviewer POST /enqueue -> 403")

    clip_new = f"sha256:m33_new_{suffix}"
    run_new = str(uuid.uuid4())
    _seed_clip(clip_id=clip_new, run_id=run_new, ds=ds)
    enqueue = client.post(
        "/api/review/enqueue",
        headers=admin_h,
        json={"clip_ids": [clip_new]},
    )
    assert enqueue.status_code == 200, enqueue.text
    enq_body = enqueue.json()
    assert enq_body["summary"]["created"] == 1
    print("OK admin POST /enqueue")

    print("\nAll M3.3 checks passed.")


if __name__ == "__main__":
    main()
