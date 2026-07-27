"""M1.4 smoke test: role-based OSS and admin ACL."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m14-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.main import app

ADMIN = "m12_test_admin_7e5a2c1a"
ADMIN_PASS = "adminpass123"
REVIEWER = "m12_test_reviewer_7e5a2c1a"
REVIEWER_PASS = "reviewpass123"


def _token(client: TestClient, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def main() -> None:
    client = TestClient(app)
    admin_h = {"Authorization": f"Bearer {_token(client, ADMIN, ADMIN_PASS)}"}
    reviewer_h = {"Authorization": f"Bearer {_token(client, REVIEWER, REVIEWER_PASS)}"}

    r = client.get("/api/oss/info", headers=admin_h)
    assert r.status_code == 200, r.text
    print("OK admin GET /api/oss/info -> 200")

    r = client.get("/api/oss/info", headers=reviewer_h)
    assert r.status_code == 403, r.text
    print("OK reviewer GET /api/oss/info -> 403")

    r = client.get("/api/admin/users", headers=admin_h)
    assert r.status_code == 200, r.text
    print("OK admin GET /api/admin/users -> 200")

    r = client.get("/api/admin/users", headers=reviewer_h)
    assert r.status_code == 403, r.text
    print("OK reviewer GET /api/admin/users -> 403")

    r = client.get("/api/clips", headers=reviewer_h)
    assert r.status_code == 200, r.text
    print("OK reviewer GET /api/clips -> 200")

    print("\nAll M1.4 checks passed.")


if __name__ == "__main__":
    main()
