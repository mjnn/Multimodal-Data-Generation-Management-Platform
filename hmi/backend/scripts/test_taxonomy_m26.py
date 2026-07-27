"""M2.6 taxonomy OSS export + dispatch manifest smoke test."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "dataworks"))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m26-smoke-at-least-32b")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.app_meta import APP_META_PATH, read_app_meta
from hmi.main import app
from hmi.taxonomy.export import (
    TAXONOMY_LATEST_KEY,
    export_published_taxonomy,
    merge_taxonomy_into_dispatch,
    nodes_to_yaml_document,
    taxonomy_oss_key,
)
from pipeline_dispatch import attach_taxonomy_to_dispatch_payload


def _sample_nodes() -> list[dict]:
    return [
        {
            "level_code": "L1.1",
            "level_name": "时间维度",
            "label_id": "L1.1.day_period",
            "name": "日时段",
            "definition": "按小时划分",
            "dtype": "enum",
            "value_schema": {"type": "enum", "values": ["morning", "night"]},
            "sort_order": 0,
            "is_active": True,
        }
    ]


def main() -> None:
    ensure_schema()

    version = {"id": "ver-1", "version_code": "m26_v1", "source_import": "test"}
    doc = nodes_to_yaml_document(version, _sample_nodes())
    assert doc["label_count"] == 1
    assert doc["labels"][0]["id"] == "L1.1.day_period"
    print("OK nodes_to_yaml_document")

    merged = merge_taxonomy_into_dispatch(
        {"action": "run", "clip_id": "c1"},
        {
            "taxonomy_version_id": "ver-1",
            "taxonomy_version_code": "m26_v1",
            "taxonomy_oss_key": taxonomy_oss_key("m26_v1"),
        },
    )
    assert merged["taxonomy_oss_key"] == "config/taxonomy/m26_v1.yaml"
    print("OK merge_taxonomy_into_dispatch")

    with patch("pipeline_dispatch.load_taxonomy_latest_from_oss") as load_mock:
        load_mock.return_value = {
            "taxonomy_version_id": "ver-1",
            "taxonomy_version_code": "m26_v1",
            "taxonomy_oss_key": "config/taxonomy/m26_v1.yaml",
        }
        payload = attach_taxonomy_to_dispatch_payload(
            {"action": "run", "clip_id": "c1", "run_id": "r1"},
            bucket_name="bucket",
            endpoint="https://oss-cn-shanghai.aliyuncs.com",
            account=object(),
        )
    assert payload["taxonomy_version_id"] == "ver-1"
    print("OK attach_taxonomy_to_dispatch_payload")

    stored: dict[str, str] = {}

    def fake_put(key: str, text: str, *, content_type: str = "application/json") -> None:
        stored[key.lstrip("/")] = text

    def fake_get(key: str):
        return stored.get(key.lstrip("/"))

    import uuid

    suffix = uuid.uuid4().hex[:8]
    admin_name = f"m26_admin_{suffix}"
    if get_user_by_username(admin_name) is None:
        create_user(admin_name, "adminpass123", display_name="M26 Admin", roles=["admin"])

    client = TestClient(app)
    login = client.post(
        "/api/auth/login",
        json={"username": admin_name, "password": "adminpass123"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    draft_code = f"m26_draft_{suffix}"
    created = client.post(
        "/api/taxonomy/versions",
        headers=headers,
        json={"version_code": draft_code, "import_yaml": True},
    )
    assert created.status_code == 201, created.text
    version_id = created.json()["id"]

    with (
        patch("hmi.taxonomy.export.put_object_text", side_effect=fake_put),
        patch("hmi.taxonomy.export.get_object_json") as get_json,
        patch("hmi.taxonomy.export.get_settings") as settings_mock,
    ):
        settings_mock.return_value = {"oss_bucket": "test-bucket"}
        get_json.return_value = {"action": "idle", "reason": "test"}
        published = client.post(
            f"/api/taxonomy/versions/{version_id}/publish",
            headers=headers,
        )
        assert published.status_code == 200, published.text
        body = published.json()
        assert body["status"] == "published"
        assert body["export"]["taxonomy_oss_key"] == taxonomy_oss_key(draft_code)

    yaml_key = taxonomy_oss_key(draft_code)
    assert yaml_key in stored
    assert "L1.1.timestamp" in stored[yaml_key]
    assert TAXONOMY_LATEST_KEY in stored
    latest = json.loads(stored[TAXONOMY_LATEST_KEY])
    assert latest["taxonomy_version_id"] == version_id

    dispatch = json.loads(stored["pipeline/dispatch/latest.json"])
    assert dispatch["taxonomy_version_id"] == version_id
    assert dispatch["taxonomy_oss_key"] == yaml_key
    print("OK publish exports yaml + latest + dispatch manifest")

    meta = read_app_meta()
    assert meta.get("latest_published_taxonomy_version_id") == version_id
    assert APP_META_PATH.is_file()
    print("OK app_meta.json updated")

    print("\nAll M2.6 checks passed.")


if __name__ == "__main__":
    main()
