"""M9 audit API + taxonomy hint smoke test."""

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
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import append_audit_log
from hmi.dataset.taxonomy_hint import taxonomy_context_for_filter
from hmi.main import app


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m9_admin_{suffix}"
    reviewer_name = f"m9_reviewer_{suffix}"
    for name, password, roles in (
        (admin_name, "adminpass123", ["admin"]),
        (reviewer_name, "reviewpass123", ["reviewer"]),
    ):
        if get_user_by_username(name) is None:
            create_user(name, password, roles=roles)

    admin_user = get_user_by_username(admin_name)
    assert admin_user
    append_audit_log(
        actor_id=admin_user["id"],
        action="dataset.create",
        resource_type="dataset_snapshot",
        resource_id=str(uuid.uuid4()),
        detail={"name": "m9_test"},
    )

    client = TestClient(app)
    admin_h = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}
    reviewer_h = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}

    res = client.get("/api/admin/audit?action=dataset.create&limit=10", headers=admin_h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["total"] >= 1
    assert any(i["action"] == "dataset.create" for i in body["items"])
    assert body["items"][0].get("actor_username") == admin_name
    print("OK admin GET /api/admin/audit")

    assert client.get("/api/admin/audit", headers=reviewer_h).status_code == 403
    print("OK reviewer audit 403")

    ctx = taxonomy_context_for_filter({"taxonomy_version_id": "nonexistent-version"})
    assert "published_taxonomy_version_id" in ctx
    print("OK taxonomy_context_for_filter")

    print("\nM9 backend tests passed.")


if __name__ == "__main__":
    main()
