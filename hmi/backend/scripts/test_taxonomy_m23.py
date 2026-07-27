"""M2.3 smoke test: taxonomy REST API."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m23-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.main import app
from hmi.taxonomy_db import get_version_by_code

ADMIN_USER = "m23_test_admin"
ADMIN_PASS = "adminpass123"
REVIEWER_USER = "m23_test_reviewer"
REVIEWER_PASS = "reviewpass123"


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _sample_nodes() -> list[dict]:
    return [
        {
            "label_id": "L1.1.day_period",
            "level_code": "L1.1",
            "level_name": "时间维度",
            "name": "日时段",
            "definition": "按小时划分",
            "dtype": "enum",
            "value_schema": {"type": "enum", "values": ["morning", "night"]},
            "sort_order": 0,
        },
        {
            "label_id": "L1.1.is_holiday",
            "level_code": "L1.1",
            "level_name": "时间维度",
            "name": "是否节假日",
            "dtype": "bool",
            "value_schema": {"type": "bool", "values": ["true", "false"]},
            "sort_order": 1,
        },
    ]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"{ADMIN_USER}_{suffix}"
    reviewer_name = f"{REVIEWER_USER}_{suffix}"

    if get_user_by_username(admin_name) is None:
        create_user(admin_name, ADMIN_PASS, display_name="M23 Admin", roles=["admin"])
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, REVIEWER_PASS, display_name="M23 Reviewer", roles=["reviewer"])

    client = TestClient(app)

    unauth = client.get("/api/taxonomy/versions")
    assert unauth.status_code == 401, unauth.text
    print("OK GET /versions without auth -> 401")

    admin_headers = {"Authorization": f"Bearer {_login(client, admin_name, ADMIN_PASS)}"}
    reviewer_headers = {"Authorization": f"Bearer {_login(client, reviewer_name, REVIEWER_PASS)}"}

    draft_code = f"m23_draft_{suffix}"
    created = client.post(
        "/api/taxonomy/versions",
        headers=admin_headers,
        json={"version_code": draft_code},
    )
    assert created.status_code == 201, created.text
    draft = created.json()
    draft_id = draft["id"]
    assert draft["status"] == "draft"
    assert draft["node_count"] == 0
    print("OK admin POST /versions -> 201")

    reviewer_create = client.post(
        "/api/taxonomy/versions",
        headers=reviewer_headers,
        json={"version_code": f"m23_blocked_{suffix}"},
    )
    assert reviewer_create.status_code == 403, reviewer_create.text
    print("OK reviewer POST /versions -> 403")

    listed = client.get("/api/taxonomy/versions", headers=reviewer_headers)
    assert listed.status_code == 200, listed.text
    assert any(v["version_code"] == draft_code for v in listed.json())
    print("OK reviewer GET /versions -> 200")

    put_nodes = client.put(
        f"/api/taxonomy/versions/{draft_id}/nodes",
        headers=admin_headers,
        json={"nodes": _sample_nodes()},
    )
    assert put_nodes.status_code == 200, put_nodes.text
    assert put_nodes.json()["replaced"] == 2
    print("OK admin PUT draft nodes -> 200")

    tree = client.get(f"/api/taxonomy/versions/{draft_id}/tree", headers=reviewer_headers)
    assert tree.status_code == 200, tree.text
    body = tree.json()
    assert len(body["nodes"]) == 2
    assert len(body["tree"]) == 1
    assert body["tree"][0]["id"] == "L1.1"
    print("OK GET /versions/{id}/tree -> grouped tree")

    clone_code = f"{draft_code}-clone"
    cloned = client.post(
        f"/api/taxonomy/versions/{draft_id}/clone",
        headers=admin_headers,
        json={"version_code": clone_code},
    )
    assert cloned.status_code == 201, cloned.text
    clone_id = cloned.json()["id"]
    assert cloned.json()["node_count"] == 2
    print("OK POST /versions/{id}/clone -> 201")

    published = client.post(
        f"/api/taxonomy/versions/{draft_id}/publish",
        headers=admin_headers,
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"
    print("OK POST /versions/{id}/publish -> 200")

    conflict = client.put(
        f"/api/taxonomy/versions/{draft_id}/nodes",
        headers=admin_headers,
        json={"nodes": _sample_nodes()},
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["detail"]["code"] == "409_CONFLICT"
    print("OK PUT nodes on published -> 409")

    archived = client.post(
        f"/api/taxonomy/versions/{clone_id}/archive",
        headers=admin_headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    print("OK POST /versions/{id}/archive -> 200")

    import_code = f"m23_import_{suffix}"
    imported = client.post(
        "/api/taxonomy/versions",
        headers=admin_headers,
        json={"version_code": import_code, "import_yaml": True},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["node_count"] == 68
    assert get_version_by_code(import_code) is not None
    print("OK POST /versions import_yaml -> 201 (68 nodes)")

    print("\nAll M2.3 checks passed.")


if __name__ == "__main__":
    main()
