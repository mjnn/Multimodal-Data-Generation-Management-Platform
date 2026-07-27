"""M2.4 smoke test: GET /api/label-taxonomy reads DB published version."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m24-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.main import app
from hmi.taxonomy.compat import (
    count_taxonomy_leaves,
    get_label_taxonomy_from_yaml,
)
from hmi.taxonomy_db import get_version_by_code

ADMIN_USER = "m24_test_admin"
ADMIN_PASS = "adminpass123"


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"{ADMIN_USER}_{suffix}"

    if get_user_by_username(admin_name) is None:
        create_user(admin_name, ADMIN_PASS, display_name="M24 Admin", roles=["admin"])

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_login(client, admin_name, ADMIN_PASS)}"}

    yaml_tree = get_label_taxonomy_from_yaml()
    yaml_leaves = count_taxonomy_leaves(yaml_tree)
    assert yaml_leaves == 68, f"expected 68 yaml leaves, got {yaml_leaves}"
    print(f"OK yaml fallback baseline -> {yaml_leaves} leaves")

    v2 = get_version_by_code("v2")
    assert v2 is not None, "v2 draft missing; run import_taxonomy_yaml.py first"
    assert v2["status"] == "draft", f"v2 status={v2['status']}"

    preview = client.get(
        f"/api/label-taxonomy?version_id={v2['id']}",
        headers=headers,
    )
    assert preview.status_code == 200, preview.text
    preview_leaves = count_taxonomy_leaves(preview.json())
    assert preview_leaves == 68
    assert preview.json()[0]["children"][0]["id"] == "L1.1.timestamp"
    assert "definition" not in preview.json()[0]["children"][0]
    print("OK GET /label-taxonomy?version_id=draft -> 68 leaves, compat shape")

    missing = client.get(
        "/api/label-taxonomy?version_id=00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    assert missing.status_code == 404, missing.text
    print("OK unknown version_id -> 404")

    pub_code = f"m24_pub_{suffix}"
    created = client.post(
        "/api/taxonomy/versions",
        headers=headers,
        json={"version_code": pub_code, "import_yaml": True},
    )
    assert created.status_code == 201, created.text
    pub_id = created.json()["id"]

    published = client.post(
        f"/api/taxonomy/versions/{pub_id}/publish",
        headers=headers,
    )
    assert published.status_code == 200, published.text
    print("OK publish imported version for default read")

    default = client.get("/api/label-taxonomy", headers=headers)
    assert default.status_code == 200, default.text
    db_leaves = count_taxonomy_leaves(default.json())
    assert db_leaves == 68
    assert db_leaves == yaml_leaves
    print("OK GET /label-taxonomy default -> published DB 68 leaves == yaml")

    print("\nAll M2.4 checks passed.")


if __name__ == "__main__":
    main()
