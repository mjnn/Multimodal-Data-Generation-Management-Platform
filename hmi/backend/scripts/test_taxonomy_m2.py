"""M2 milestone exit integration test (M2.7).

Flow: import YAML → clone draft → edit nodes → publish → label-taxonomy + dispatch manifest.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m2-exit-at-least-32-chars")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.app_meta import read_app_meta
from hmi.main import app
from hmi.taxonomy.compat import count_taxonomy_leaves
from hmi.taxonomy.export import TAXONOMY_LATEST_KEY, taxonomy_oss_key


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _find_leaf_name(tree: list[dict], label_id: str) -> str | None:
    for level in tree:
        for child in level.get("children") or []:
            if child.get("id") == label_id:
                return str(child.get("name"))
    return None


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m2_admin_{suffix}"
    reviewer_name = f"m2_reviewer_{suffix}"

    if get_user_by_username(admin_name) is None:
        create_user(admin_name, "adminpass123", display_name="M2 Admin", roles=["admin"])
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, "reviewpass123", display_name="M2 Reviewer", roles=["reviewer"])

    client = TestClient(app)
    admin_headers = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}
    reviewer_headers = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}

    base_code = f"m2_base_{suffix}"
    imported = client.post(
        "/api/taxonomy/versions",
        headers=admin_headers,
        json={"version_code": base_code, "import_yaml": True},
    )
    assert imported.status_code == 201, imported.text
    assert imported.json()["node_count"] == 68
    base_id = imported.json()["id"]
    print("OK import_yaml -> 68 nodes")

    draft_code = f"m2_v2_{suffix}"
    cloned = client.post(
        f"/api/taxonomy/versions/{base_id}/clone",
        headers=admin_headers,
        json={"version_code": draft_code},
    )
    assert cloned.status_code == 201, cloned.text
    draft_id = cloned.json()["id"]
    assert cloned.json()["node_count"] == 68
    print("OK clone -> draft v2")

    tree = client.get(f"/api/taxonomy/versions/{draft_id}/tree", headers=admin_headers)
    assert tree.status_code == 200, tree.text
    nodes = tree.json()["nodes"]
    assert len(nodes) == 68

    edited_name = f"日时段-M2-{suffix}"
    payload_nodes = []
    for n in nodes:
        item = {
            "label_id": n["label_id"],
            "level_code": n["level_code"],
            "level_name": n.get("level_name"),
            "name": edited_name if n["label_id"] == "L1.1.day_period" else n["name"],
            "definition": n.get("definition"),
            "dtype": n.get("dtype"),
            "value_schema": n.get("value_schema"),
            "sort_order": n.get("sort_order", 0),
            "is_active": n.get("is_active", True),
        }
        payload_nodes.append(item)

    updated = client.put(
        f"/api/taxonomy/versions/{draft_id}/nodes",
        headers=admin_headers,
        json={"nodes": payload_nodes},
    )
    assert updated.status_code == 200, updated.text
    print("OK PUT draft nodes (edited day_period name)")

    stored: dict[str, str] = {}

    def fake_put(key: str, text: str, *, content_type: str = "application/json") -> None:
        stored[key.lstrip("/")] = text

    with (
        patch("hmi.taxonomy.export.put_object_text", side_effect=fake_put),
        patch("hmi.taxonomy.export.get_object_json") as get_json,
        patch("hmi.taxonomy.export.get_settings") as settings_mock,
    ):
        settings_mock.return_value = {"oss_bucket": "test-bucket"}
        get_json.return_value = {"action": "idle", "reason": "m2_test"}
        published = client.post(
            f"/api/taxonomy/versions/{draft_id}/publish",
            headers=admin_headers,
        )
        assert published.status_code == 200, published.text
        pub_body = published.json()
        assert pub_body["status"] == "published"
        assert pub_body["export"]["taxonomy_version_code"] == draft_code

    oss_key = taxonomy_oss_key(draft_code)
    assert oss_key in stored
    assert edited_name in stored[oss_key]
    dispatch = json.loads(stored["pipeline/dispatch/latest.json"])
    assert dispatch["taxonomy_version_id"] == draft_id
    assert dispatch["taxonomy_oss_key"] == oss_key
    latest = json.loads(stored[TAXONOMY_LATEST_KEY])
    assert latest["taxonomy_version_code"] == draft_code
    print("OK publish -> OSS yaml + dispatch manifest + latest.json")

    meta = read_app_meta()
    assert meta.get("latest_published_taxonomy_version_id") == draft_id
    print("OK app_meta latest published")

    label_tax = client.get("/api/label-taxonomy", headers=admin_headers)
    assert label_tax.status_code == 200, label_tax.text
    leaves = count_taxonomy_leaves(label_tax.json())
    assert leaves == 68
    assert _find_leaf_name(label_tax.json(), "L1.1.day_period") == edited_name
    print("OK GET /label-taxonomy -> published v2 with edit")

    conflict = client.put(
        f"/api/taxonomy/versions/{draft_id}/nodes",
        headers=admin_headers,
        json={"nodes": payload_nodes[:2]},
    )
    assert conflict.status_code == 409, conflict.text
    print("OK published PUT nodes -> 409")

    forbidden = client.post(
        "/api/taxonomy/versions",
        headers=reviewer_headers,
        json={"version_code": f"m2_blocked_{suffix}"},
    )
    assert forbidden.status_code == 403, forbidden.text
    print("OK reviewer POST /taxonomy/versions -> 403")

    reviewer_read = client.get("/api/taxonomy/versions", headers=reviewer_headers)
    assert reviewer_read.status_code == 200, reviewer_read.text
    codes = {v["version_code"] for v in reviewer_read.json()}
    assert draft_code in codes
    print("OK reviewer GET /taxonomy/versions -> 200")

    versions = client.get("/api/taxonomy/versions", headers=admin_headers)
    published_rows = [v for v in versions.json() if v["version_code"] == draft_code]
    assert len(published_rows) == 1
    assert published_rows[0]["status"] == "published"
    print("OK /taxonomy API lists published v2")

    print("\nAll M2 exit checks passed.")


if __name__ == "__main__":
    main()
