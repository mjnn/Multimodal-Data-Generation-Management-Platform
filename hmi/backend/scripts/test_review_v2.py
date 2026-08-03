"""M6 milestone exit integration test (M6.6).

Runs M6.1–M6.3 smoke modules and v2 API integration checks.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.main import app
from hmi.review_db import create_review


def _run_script(name: str) -> None:
    path = BACKEND_ROOT / "scripts" / name
    result = subprocess.run(
        [sys.executable, str(path)],
        cwd=str(BACKEND_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise AssertionError(f"{name} failed with code {result.returncode}")


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def main() -> None:
    ensure_schema()

    print("== M6.1 field review DB + merge ==")
    _run_script("test_review_m61.py")

    print("== M6.2 v2 task queue API ==")
    _run_script("test_review_m62.py")

    print("== M6.3 submit + audit ==")
    _run_script("test_review_m63.py")

    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"m6_exit_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, "reviewpass123", roles=["reviewer"])

    clip_id = f"sha256:m6_exit_{suffix}"
    run_id = str(uuid.uuid4())
    labels = {"L1.1.day_period": "morning", "L1.1.is_holiday": False}
    create_review(clip_id, run_id, labels_json=labels, review_status="pending_review")

    client = TestClient(app)
    token = _login(client, reviewer_name, "reviewpass123")
    headers = {"Authorization": f"Bearer {token}"}

    views = {
        (clip_id, run_id): {
            "clip_label_ready": True,
            "labels_json": labels,
            "disputed_label_ids": ["L1.1.day_period"],
            "dispute_count": 1,
            "label_preview": "morning",
            "anchor_timestamp_ns": 1_000_000_000,
        }
    }

    def fake_view(cid: str, rid: str, *, ds: str | None = None):
        return views.get((cid, rid), {"clip_label_ready": False, "labels_json": {}})

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=[{"clip_id": clip_id, "run_id": run_id}]):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch("hmi.review.v2_tasks.load_ai_label_hints_local", return_value={}):
                                with patch("hmi.review.v2_tasks._clip_dir_name", side_effect=lambda c: c[-8:]):
                                    res = client.get("/api/review/v2/session?mode=confidence", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "session" in body and "stats" in body
    print("OK GET /api/review/v2/session")

    trainer_name = f"m6_exit_trainer_{suffix}"
    if get_user_by_username(trainer_name) is None:
        create_user(trainer_name, "trainerpass123", roles=["model_trainer"])
    trainer_token = _login(client, trainer_name, "trainerpass123")
    trainer_headers = {"Authorization": f"Bearer {trainer_token}"}

    res = client.post(
        "/api/review/v2/submit",
        headers=trainer_headers,
        json={
            "clip_id": clip_id,
            "run_id": run_id,
            "label_id": "L1.1.day_period",
            "action": "confirm",
        },
    )
    assert res.status_code == 403, res.text
    print("OK trainer submit 403 (N6 regression)")

    print("\nM6 exit integration tests passed.")


if __name__ == "__main__":
    main()
