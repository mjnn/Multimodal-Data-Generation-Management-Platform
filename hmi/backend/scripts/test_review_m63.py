"""M6.3 review v2 submit API + audit smoke test."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import list_audit_logs
from hmi.main import app
from hmi.review.field_review_db import get_field_review, list_field_review_label_ids
from hmi.review_db import create_review, get_review


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"m63_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        user = create_user(reviewer_name, "reviewpass123", roles=["reviewer"])
        reviewer_id = user["id"]
    else:
        reviewer_id = get_user_by_username(reviewer_name)["id"]

    clip_id = f"sha256:m63_{suffix}"
    run_id = str(uuid.uuid4())
    labels = {"L1.1.day_period": "morning", "L1.1.is_holiday": False}
    review = create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="pending_review",
    )

    client = TestClient(app)
    token = _login(client, reviewer_name, "reviewpass123")
    headers = {"Authorization": f"Bearer {token}"}

    ai_ids = ["L1.1.day_period", "L1.1.is_holiday"]

    with patch("hmi.review.merge.get_ai_label_ids", return_value=ai_ids):
        with patch("hmi.review.merge.get_ai_label_value", side_effect=lambda _c, _r, lid: labels.get(lid)):
            res = client.post(
                "/api/review/v2/submit",
                headers=headers,
                json={
                    "clip_id": clip_id,
                    "run_id": run_id,
                    "label_id": "L1.1.day_period",
                    "action": "confirm",
                    "clip_updated_at": review["updated_at"],
                },
            )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["field_review"]["action"] == "confirm"
    assert body["field_review"]["value_json"] == "morning"
    assert body["clip_review"]["labels_json"]["L1.1.day_period"] == "morning"
    assert body["rolled_up_to_reviewed"] is False
    print("OK submit confirm")

    review = get_review(clip_id, run_id)
    assert review is not None

    with patch("hmi.review.merge.get_ai_label_ids", return_value=ai_ids):
        with patch("hmi.review.merge.get_ai_label_value", side_effect=lambda _c, _r, lid: labels.get(lid)):
            res = client.post(
                "/api/review/v2/submit",
                headers=headers,
                json={
                    "clip_id": clip_id,
                    "run_id": run_id,
                    "label_id": "L1.1.is_holiday",
                    "action": "uncertain",
                    "clip_updated_at": review["updated_at"],
                },
            )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["field_review"]["human_doubtful"] is True
    assert body["field_review"]["value_json"] is None
    assert body["clip_review"]["labels_json"]["L1.1.is_holiday"] is None
    assert body["rolled_up_to_reviewed"] is True
    assert body["clip_review"]["review_status"] == "reviewed"
    print("OK submit uncertain + rollup reviewed")

    field = get_field_review(clip_id, run_id, "L1.1.is_holiday")
    assert field is not None
    assert field["human_doubtful"] is True
    assert set(list_field_review_label_ids(clip_id, run_id)) == set(ai_ids)
    print("OK field reviews persisted")

    logs = list_audit_logs(resource_type="clip_label_field_review", resource_id=field["id"], limit=5)
    assert logs and logs[0]["action"] == "clip.label_field_review"
    assert logs[0]["detail"]["action"] == "uncertain"
    print("OK audit_log clip.label_field_review")

    res = client.post(
        "/api/review/v2/submit",
        headers=headers,
        json={
            "clip_id": clip_id,
            "run_id": run_id,
            "label_id": "L1.1.day_period",
            "action": "correct",
        },
    )
    assert res.status_code == 422
    print("OK correct without value -> 422")

    trainer = f"m63_trainer_{suffix}"
    create_user(trainer, "trainerpass123", roles=["model_trainer"])
    trainer_token = _login(client, trainer, "trainerpass123")
    res = client.post(
        "/api/review/v2/submit",
        headers={"Authorization": f"Bearer {trainer_token}"},
        json={
            "clip_id": clip_id,
            "run_id": run_id,
            "label_id": "L1.1.day_period",
            "action": "confirm",
        },
    )
    assert res.status_code == 403
    print("OK trainer forbidden")

    clip2 = f"sha256:m63b_{suffix}"
    run2 = str(uuid.uuid4())
    rev2 = create_review(clip2, run2, labels_json=labels, review_status="pending_review")
    with patch("hmi.review.merge.get_ai_label_ids", return_value=ai_ids):
        with patch("hmi.review.merge.get_ai_label_value", side_effect=lambda _c, _r, lid: labels.get(lid)):
            res = client.post(
                "/api/review/v2/submit",
                headers=headers,
                json={
                    "clip_id": clip2,
                    "run_id": run2,
                    "label_id": "L1.1.day_period",
                    "action": "confirm",
                    "clip_updated_at": "stale-ts",
                },
            )
    assert res.status_code == 409
    assert rev2["updated_at"] != "stale-ts"
    print("OK optimistic lock 409")

    print("\nAll M6.3 checks passed.")


if __name__ == "__main__":
    main()
