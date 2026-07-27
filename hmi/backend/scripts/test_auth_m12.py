"""M1.2 smoke test: bootstrap + admin CRUD + reviewer 403."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m12-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.main import app

ADMIN_USER = "m12_test_admin"
ADMIN_PASS = "adminpass123"
REVIEWER_USER = "m12_test_reviewer"
REVIEWER_PASS = "reviewpass123"


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"{ADMIN_USER}_{suffix}"
    reviewer_name = f"{REVIEWER_USER}_{suffix}"

    if get_user_by_username(admin_name) is None:
        create_user(admin_name, ADMIN_PASS, display_name="M12 Admin", roles=["admin"])
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, REVIEWER_PASS, display_name="M12 Reviewer", roles=["reviewer"])

    client = TestClient(app)
    admin_token = _login(client, admin_name, ADMIN_PASS)
    reviewer_token = _login(client, reviewer_name, REVIEWER_PASS)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    reviewer_headers = {"Authorization": f"Bearer {reviewer_token}"}

    forbidden = client.post(
        "/api/admin/users",
        headers=reviewer_headers,
        json={
            "username": f"blocked_{suffix}",
            "password": "password123",
            "roles": ["reviewer"],
        },
    )
    assert forbidden.status_code == 403, forbidden.text
    assert forbidden.json()["detail"]["code"] == "403_FORBIDDEN"
    print("OK reviewer POST /api/admin/users -> 403")

    new_user = f"reviewer_new_{suffix}"
    created = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={
            "username": new_user,
            "password": "password123",
            "display_name": "New Reviewer",
            "roles": ["reviewer"],
        },
    )
    assert created.status_code == 201, created.text
    created_body = created.json()
    assert created_body["username"] == new_user
    assert created_body["roles"] == ["reviewer"]
    print("OK admin POST /api/admin/users -> 201")

    listed = client.get("/api/admin/users", headers=admin_headers)
    assert listed.status_code == 200, listed.text
    usernames = {u["username"] for u in listed.json()}
    assert new_user in usernames
    print("OK admin GET /api/admin/users -> 200")

    patched = client.patch(
        f"/api/admin/users/{created_body['id']}",
        headers=admin_headers,
        json={"display_name": "Renamed Reviewer", "is_active": True},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["display_name"] == "Renamed Reviewer"
    print("OK admin PATCH /api/admin/users/{id} -> 200")

    short_pw = client.post(
        "/api/admin/users",
        headers=admin_headers,
        json={"username": f"bad_{suffix}", "password": "short", "roles": []},
    )
    assert short_pw.status_code == 422, short_pw.text
    print("OK admin POST short password -> 422")

    print("\nAll M1.2 checks passed.")


if __name__ == "__main__":
    main()
