"""M3.4 smoke test: audit_log on review save/reopen + 409 no audit."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m34-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import list_audit_logs
from hmi.main import app
from hmi.review_db import create_review


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"m34_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, "reviewpass123", roles=["reviewer"])

    clip_id = f"sha256:m34_{suffix}"
    run_id = str(uuid.uuid4())
    labels = {"L1.1.day_period": "morning"}
    review = create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="pending_review",
    )

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}

    logs_before = list_audit_logs(resource_type="clip_label_review", resource_id=review["id"])
    assert not any(l["action"] == "clip.review" for l in logs_before)

    draft = client.put(
        f"/api/review/clips/{clip_id}",
        headers=headers,
        json={
            "labels_json": {"L1.1.day_period": "afternoon"},
            "review_status": "pending_review",
            "updated_at": review["updated_at"],
            "run_id": run_id,
        },
    )
    assert draft.status_code == 200, draft.text
    draft_body = draft.json()
    print("OK PUT draft save")

    after_draft = list_audit_logs(resource_type="clip_label_review", resource_id=review["id"])
    draft_logs = [l for l in after_draft if l["action"] == "clip.review"]
    assert len(draft_logs) == 1
    assert draft_logs[0]["detail"]["review_status"] == "pending_review"
    print("OK clip.review audit on draft save")

    reviewed = client.put(
        f"/api/review/clips/{clip_id}",
        headers=headers,
        json={
            "labels_json": {"L1.1.day_period": "night"},
            "review_status": "reviewed",
            "updated_at": draft_body["updated_at"],
            "run_id": run_id,
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    reviewed_body = reviewed.json()
    print("OK PUT mark reviewed")

    after_review = list_audit_logs(resource_type="clip_label_review", resource_id=review["id"])
    review_logs = [l for l in after_review if l["action"] == "clip.review"]
    assert len(review_logs) == 2
    review_statuses = {l["detail"]["review_status"] for l in review_logs}
    assert review_statuses == {"pending_review", "reviewed"}
    print("OK clip.review audit on reviewed save")

    count_before_conflict = len(list_audit_logs(resource_type="clip_label_review", resource_id=review["id"]))
    conflict = client.put(
        f"/api/review/clips/{clip_id}",
        headers=headers,
        json={
            "labels_json": labels,
            "review_status": "reviewed",
            "updated_at": review["updated_at"],
            "run_id": run_id,
        },
    )
    assert conflict.status_code == 409, conflict.text
    count_after_conflict = len(list_audit_logs(resource_type="clip_label_review", resource_id=review["id"]))
    assert count_after_conflict == count_before_conflict
    print("OK 409 conflict writes no audit")

    reopen = client.post(
        f"/api/review/clips/{clip_id}/reopen",
        headers=headers,
        json={"run_id": run_id},
    )
    assert reopen.status_code == 200, reopen.text
    assert reopen.json()["review_status"] == "pending_review"
    print("OK POST reopen")

    after_reopen = list_audit_logs(resource_type="clip_label_review", resource_id=review["id"])
    reopen_logs = [l for l in after_reopen if l["action"] == "clip.reopen"]
    assert len(reopen_logs) == 1
    assert reopen_logs[0]["detail"]["previous_status"] == "reviewed"
    print("OK clip.reopen audit")

    print("\nAll M3.4 checks passed.")


if __name__ == "__main__":
    main()
