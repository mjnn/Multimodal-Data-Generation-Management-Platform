"""M1.1 auth smoke test: schema, login, me, 401 on protected routes."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m11-smoke")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import APP_DB_PATH, create_user, ensure_schema, get_user_by_username
from hmi.main import app

TEST_USER = "m11_test_admin"
TEST_PASS = "testpass123"


def main() -> None:
    ensure_schema()
    if get_user_by_username(TEST_USER) is None:
        create_user(TEST_USER, TEST_PASS, display_name="M11 Test", roles=["admin"])

    client = TestClient(app)

    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    print("OK GET /api/health -> 200")

    unauth = client.get("/api/clips")
    assert unauth.status_code == 401, unauth.text
    print("OK GET /api/clips (no token) -> 401")

    bad_login = client.post("/api/auth/login", json={"username": TEST_USER, "password": "wrong"})
    assert bad_login.status_code == 401, bad_login.text
    print("OK POST /api/auth/login (bad password) -> 401")

    login = client.post("/api/auth/login", json={"username": TEST_USER, "password": TEST_PASS})
    assert login.status_code == 200, login.text
    body = login.json()
    assert "access_token" in body
    assert body["user"]["username"] == TEST_USER
    print("OK POST /api/auth/login -> 200 + access_token")

    token = body["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    assert me.json()["user"]["roles"] == ["admin"]
    print("OK GET /api/auth/me -> 200")

    clips = client.get("/api/clips", headers={"Authorization": f"Bearer {token}"})
    assert clips.status_code == 200, clips.text
    print("OK GET /api/clips (with token) -> 200")

    logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout.status_code == 200, logout.text
    print("OK POST /api/auth/logout -> 200")

    print(f"\nAll M1.1 checks passed. app.db: {APP_DB_PATH}")


if __name__ == "__main__":
    main()
