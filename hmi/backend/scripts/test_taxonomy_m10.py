"""M10 taxonomy hub API smoke test."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m10-at-least-32-chars-xx")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.main import app
from hmi.taxonomy.diff import diff_versions
from hmi.taxonomy.insights import build_coverage
from hmi.taxonomy_db import create_version, publish_version, replace_nodes


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m10_admin_{suffix}"
    if get_user_by_username(admin_name) is None:
        create_user(admin_name, "adminpass123", display_name="M10 Admin", roles=["admin"])

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {_login(client, admin_name, 'adminpass123')}"}

    ctx = client.get("/api/taxonomy/context", headers=headers)
    assert ctx.status_code == 200, ctx.text
    body = ctx.json()
    assert "published_taxonomy_version_id" in body
    print("OK GET /api/taxonomy/context")

    versions = client.get("/api/taxonomy/versions", headers=headers)
    assert versions.status_code == 200
    items = versions.json()
    assert items, "need at least one taxonomy version"
    vid = items[0]["id"]

    cov = client.get(f"/api/taxonomy/versions/{vid}/coverage", headers=headers)
    assert cov.status_code == 200, cov.text
    assert "items" in cov.json()
    print("OK GET coverage")

    cov_version = create_version(f"m10_cov_{suffix}", status="draft")
    replace_nodes(
        cov_version["id"],
        [
            {
                "label_id": "L1.1.weather",
                "level_code": "L1",
                "name": "Weather",
                "dtype": "enum",
                "value_schema": {"values": ["sunny", "rainy"]},
                "sort_order": 0,
                "is_active": True,
            },
        ],
    )
    publish_version(cov_version["id"])
    empty_pool_cov = build_coverage(cov_version["id"])
    assert empty_pool_cov["review_pool_count"] == 0
    assert empty_pool_cov["gap_node_count"] == 0
    assert all(not item["has_gap"] for item in empty_pool_cov["items"])
    print("OK coverage: empty review pool has no gap nodes")

    lineage = client.get(f"/api/taxonomy/versions/{vid}/lineage", headers=headers)
    assert lineage.status_code == 200, lineage.text
    assert "lineage_chain" in lineage.json()
    print("OK GET lineage")

    impact = client.get(f"/api/taxonomy/versions/{vid}/impact", headers=headers)
    assert impact.status_code == 200, impact.text
    print("OK GET impact")

    ref = create_version(f"m10_ref_{suffix}", status="draft")
    cur = create_version(f"m10_cur_{suffix}", status="draft")
    replace_nodes(
        ref["id"],
        [
            {"label_id": "L1.1.a", "level_code": "L1", "name": "A", "sort_order": 0, "is_active": True},
            {"label_id": "L1.2.b", "level_code": "L1", "name": "B", "sort_order": 1, "is_active": True},
        ],
    )
    replace_nodes(
        cur["id"],
        [
            {"label_id": "L1.2.b", "level_code": "L1", "name": "B", "sort_order": 0, "is_active": True},
        ],
    )
    diff = diff_versions(cur["id"], ref["id"])
    assert diff["removed_label_ids"] == ["L1.1.a"]
    assert diff["added_label_ids"] == []
    print("OK diff semantics: removed nodes relative to reference")

    if len(items) >= 2:
        other = items[1]["id"]
        diff = client.get(
            f"/api/taxonomy/versions/{vid}/diff",
            headers=headers,
            params={"against": other},
        )
        assert diff.status_code == 200, diff.text
        assert "summary" in diff.json()
        print("OK GET diff")

    proposal = client.post(
        "/api/taxonomy/proposals",
        headers=headers,
        json={
            "title": "M10 test proposal",
            "proposal_type": "scene_cluster",
            "evidence": {"clip_ids": [], "source": "test"},
        },
    )
    assert proposal.status_code == 201, proposal.text
    pid = proposal.json()["id"]
    print("OK POST proposal")

    listed = client.get("/api/taxonomy/proposals", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    print("OK GET proposals")

    patched = client.patch(
        f"/api/taxonomy/proposals/{pid}",
        headers=headers,
        json={"status": "rejected"},
    )
    assert patched.status_code == 200, patched.text
    print("OK PATCH proposal")

    preview = client.post(
        "/api/datasets/preview",
        headers=headers,
        json={"name": "m10-preview", "filter_json": {"review_status": "reviewed"}},
    )
    assert preview.status_code == 200, preview.text
    assert "taxonomy_version_distribution" in preview.json()
    print("OK dataset preview taxonomy_version_distribution")

    print("ALL M10 TESTS PASSED")


if __name__ == "__main__":
    main()
