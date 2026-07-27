"""M1 milestone exit: PRD appendix C slices C1, C8, N1, N2 (API-level)."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m1-exit-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.main import app

ADMIN = "m12_test_admin_7e5a2c1a"
ADMIN_PASS = "adminpass123"


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    new_reviewer = f"m1_exit_reviewer_{suffix}"
    new_pass = "reviewpass123"

    client = TestClient(app)

    # N1
    r = client.get("/api/clips")
    assert r.status_code == 401, r.text
    print("OK N1 GET /api/clips without token -> 401")

    admin_token = _login(client, ADMIN, ADMIN_PASS)
    admin_h = {"Authorization": f"Bearer {admin_token}"}

    # C8 — browse + search APIs
    r = client.get("/api/clips", headers=admin_h)
    assert r.status_code == 200, r.text
    print("OK C8 GET /api/clips (authenticated) -> 200")

    r = client.get("/api/search/clusters", headers=admin_h, params={"keyword": ""})
    assert r.status_code == 200, r.text
    print("OK C8 GET /api/search/clusters (authenticated) -> 200")

    # C1 — admin creates reviewer
    if get_user_by_username(new_reviewer) is None:
        r = client.post(
            "/api/admin/users",
            headers=admin_h,
            json={
                "username": new_reviewer,
                "password": new_pass,
                "display_name": "M1 Exit Reviewer",
                "roles": ["reviewer"],
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["roles"] == ["reviewer"]
    print(f"OK C1 admin created reviewer {new_reviewer}")

    reviewer_token = _login(client, new_reviewer, new_pass)
    reviewer_h = {"Authorization": f"Bearer {reviewer_token}"}

    r = client.get("/api/auth/me", headers=reviewer_h)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["roles"] == ["reviewer"]
    print("OK C1 reviewer login + roles")

    # N2
    r = client.post(
        "/api/admin/users",
        headers=reviewer_h,
        json={"username": f"blocked_{suffix}", "password": "password123", "roles": ["reviewer"]},
    )
    assert r.status_code == 403, r.text
    print("OK N2 reviewer POST /api/admin/users -> 403")

    # role menu proxy: reviewer blocked from OSS
    r = client.get("/api/oss/info", headers=reviewer_h)
    assert r.status_code == 403, r.text
    print("OK C1 reviewer OSS denied -> 403")

    r = client.get("/api/clips", headers=reviewer_h)
    assert r.status_code == 200, r.text
    print("OK C1 reviewer can browse clips")

    print("\nAll M1 exit checks passed (C1, C8, N1, N2).")


if __name__ == "__main__":
    main()
