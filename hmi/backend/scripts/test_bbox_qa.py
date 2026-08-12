"""BBox QA sidecar API smoke test (isolated from taxonomy labels_json)."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import list_audit_logs
from hmi.main import app
from hmi.review.bbox_qa_db import get_bbox_qa
from hmi.review_db import create_review, get_review


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"bbox_qa_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, "reviewpass123", roles=["reviewer"])

    clip_id = f"sha256:bbox_qa_{suffix}"
    run_id = str(uuid.uuid4())
    labels = {"L1.1.day_period": "morning"}
    review = create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="pending_review",
    )
    labels_before = dict(review["labels_json"])

    client = TestClient(app)
    token = _login(client, reviewer_name, "reviewpass123")
    headers = {"Authorization": f"Bearer {token}"}

    empty = client.get(
        "/api/review/v2/bbox-qa",
        headers=headers,
        params={"clip_id": clip_id, "run_id": run_id},
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["bbox_qa"] is None
    print("OK get empty bbox_qa")

    bad = client.put(
        "/api/review/v2/bbox-qa",
        headers=headers,
        json={"clip_id": clip_id, "run_id": run_id, "status": "not_a_status"},
    )
    assert bad.status_code == 422, bad.text
    print("OK reject invalid status")

    put = client.put(
        "/api/review/v2/bbox-qa",
        headers=headers,
        json={
            "clip_id": clip_id,
            "run_id": run_id,
            "status": "bbox_bad",
            "note": "框明显偏了",
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()["bbox_qa"]
    assert body["status"] == "bbox_bad"
    assert body["note"] == "框明显偏了"
    assert body["clip_id"] == clip_id
    assert body["run_id"] == run_id
    print("OK put bbox_bad")

    got = client.get(
        "/api/review/v2/bbox-qa",
        headers=headers,
        params={"clip_id": clip_id, "run_id": run_id},
    )
    assert got.status_code == 200, got.text
    assert got.json()["bbox_qa"]["status"] == "bbox_bad"

    put2 = client.put(
        "/api/review/v2/bbox-qa",
        headers=headers,
        json={"clip_id": clip_id, "run_id": run_id, "status": "bbox_ok", "note": ""},
    )
    assert put2.status_code == 200, put2.text
    assert put2.json()["bbox_qa"]["status"] == "bbox_ok"
    assert put2.json()["bbox_qa"]["note"] is None
    print("OK upsert bbox_ok clears empty note")

    stored = get_bbox_qa(clip_id, run_id)
    assert stored is not None and stored["status"] == "bbox_ok"

    review_after = get_review(clip_id, run_id)
    assert review_after is not None
    assert review_after["labels_json"] == labels_before
    print("OK labels_json untouched")

    logs = list_audit_logs(resource_type="clip_bbox_qa", resource_id=stored["id"], limit=5)
    assert logs and logs[0]["action"] == "clip.bbox_qa"
    print("OK audit_log clip.bbox_qa")
    print("ALL PASS")


if __name__ == "__main__":
    main()
