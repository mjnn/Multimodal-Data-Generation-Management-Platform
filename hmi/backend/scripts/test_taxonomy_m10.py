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
            "base_version_id": cov_version["id"],
            "evidence": {"source": "test", "note": "admin tree revision evidence"},
            "nodes": [
                {
                    "label_id": "L1.1.weather",
                    "level_code": "L1",
                    "name": "Weather",
                    "dtype": "enum",
                    "value_schema": {"values": ["sunny", "rainy", "fog"]},
                    "sort_order": 0,
                    "is_active": True,
                },
            ],
        },
    )
    assert proposal.status_code == 201, proposal.text
    pid = proposal.json()["id"]
    assert proposal.json().get("taxonomy_version_id")
    print("OK POST proposal")

    listed = client.get("/api/taxonomy/proposals", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["total"] >= 1
    print("OK GET proposals")

    reviewer_name = f"m10_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, "reviewpass123", roles=["reviewer"])
    reviewer_h = {"Authorization": f"Bearer {_login(client, reviewer_name, 'reviewpass123')}"}
    reviewer_list = client.get("/api/taxonomy/proposals", headers=reviewer_h)
    assert reviewer_list.status_code == 200, reviewer_list.text
    print("OK reviewer GET proposals read-only")

    user_proposal = client.post(
        "/api/taxonomy/proposals",
        headers=reviewer_h,
        json={
            "title": "M10 tree revision proposal",
            "base_version_id": cov_version["id"],
            "evidence": {"source": "test", "note": "rename weather display name based on review notes"},
            "nodes": [
                {
                    "label_id": "L1.1.weather",
                    "level_code": "L1",
                    "name": "Weather Renamed",
                    "dtype": "enum",
                    "value_schema": {"values": ["sunny", "rainy"]},
                    "sort_order": 0,
                    "is_active": True,
                },
            ],
        },
    )
    assert user_proposal.status_code == 201, user_proposal.text
    proposal_body = user_proposal.json()
    assert proposal_body.get("taxonomy_version_id"), proposal_body
    assert proposal_body.get("proposal_type") == "tree_revision"
    prop_vid = proposal_body["taxonomy_version_id"]
    prop_tree = client.get(f"/api/taxonomy/versions/{prop_vid}/tree", headers=reviewer_h)
    assert prop_tree.status_code == 200, prop_tree.text
    assert prop_tree.json()["version"]["status"] == "proposal"
    auto_code = prop_tree.json()["version"]["version_code"]
    assert str(auto_code).startswith("proposal-"), auto_code
    assert prop_tree.json().get("linked_proposal") is not None
    print("OK reviewer POST proposal materializes proposal version")

    custom_code = f"m10-custom-proposal-{suffix}"
    custom_proposal = client.post(
        "/api/taxonomy/proposals",
        headers=reviewer_h,
        json={
            "title": "M10 custom version_code",
            "base_version_id": cov_version["id"],
            "version_code": custom_code,
            "evidence": {"source": "test", "note": "user-supplied version code"},
            "nodes": [
                {
                    "label_id": "L1.1.weather",
                    "level_code": "L1",
                    "name": "Weather Custom",
                    "dtype": "enum",
                    "value_schema": {"values": ["sunny"]},
                    "sort_order": 0,
                    "is_active": True,
                },
            ],
        },
    )
    assert custom_proposal.status_code == 201, custom_proposal.text
    custom_vid = custom_proposal.json()["taxonomy_version_id"]
    custom_tree = client.get(f"/api/taxonomy/versions/{custom_vid}/tree", headers=reviewer_h)
    assert custom_tree.status_code == 200, custom_tree.text
    assert custom_tree.json()["version"]["version_code"] == custom_code
    print("OK proposal uses caller-supplied version_code")

    dup_code = client.post(
        "/api/taxonomy/proposals",
        headers=reviewer_h,
        json={
            "title": "duplicate version_code",
            "base_version_id": cov_version["id"],
            "version_code": custom_code,
            "evidence": {"source": "test", "note": "should conflict"},
            "nodes": [
                {
                    "label_id": "L1.1.weather",
                    "level_code": "L1",
                    "name": "Weather",
                    "sort_order": 0,
                    "is_active": True,
                },
            ],
        },
    )
    assert dup_code.status_code == 409, dup_code.text
    print("OK duplicate proposal version_code → 409")

    prop_lineage = client.get(f"/api/taxonomy/versions/{prop_vid}/lineage", headers=reviewer_h)
    assert prop_lineage.status_code == 200, prop_lineage.text
    lineage_body = prop_lineage.json()
    assert lineage_body.get("parent_version_id") == cov_version["id"], lineage_body
    assert any(n.get("id") == cov_version["id"] for n in lineage_body.get("lineage_chain") or [])
    print("OK proposal lineage parent is base published version")

    missing_evidence = client.post(
        "/api/taxonomy/proposals",
        headers=reviewer_h,
        json={
            "title": "missing evidence",
            "base_version_id": cov_version["id"],
            "evidence": {"source": "test"},
            "nodes": [
                {
                    "label_id": "L1.1.weather",
                    "level_code": "L1",
                    "name": "Weather",
                    "sort_order": 0,
                    "is_active": True,
                },
            ],
        },
    )
    assert missing_evidence.status_code == 422, missing_evidence.text
    print("OK evidence note required")

    tax_mgr_name = f"m10_taxonomy_mgr_{suffix}"
    if get_user_by_username(tax_mgr_name) is None:
        create_user(tax_mgr_name, "taxmgrpass123", roles=["taxonomy_manager"])
    tax_mgr_h = {"Authorization": f"Bearer {_login(client, tax_mgr_name, 'taxmgrpass123')}"}
    tax_draft = client.post(
        "/api/taxonomy/versions",
        headers=tax_mgr_h,
        json={"version_code": f"m10_taxmgr_{suffix}"},
    )
    assert tax_draft.status_code == 201, tax_draft.text
    print("OK taxonomy_manager POST version")

    approve = client.post(
        f"/api/taxonomy/proposals/{proposal_body['id']}/approve-draft",
        headers=tax_mgr_h,
    )
    assert approve.status_code == 200, approve.text
    approved = approve.json()
    assert approved["proposal"]["status"] == "merged"
    assert approved["version"]["status"] == "draft"
    print("OK approve proposal to draft")

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
