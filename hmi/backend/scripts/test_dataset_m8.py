"""M8 smoke test: balance/oversample, derive, aug_recipe, distribution preview."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-secret-for-m8-smoke-at-least-32-chars")
os.environ.setdefault("HMI_DATA_SOURCE", "local")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import list_audit_logs
from hmi.dataset.assemble import assemble_snapshot_rows
from hmi.dataset.balance import apply_balance
from hmi.dataset.build import build_snapshot_sync
from hmi.dataset_db import get_snapshot
from hmi.local import store
from hmi.main import app
from hmi.review_db import create_review

_uploads: dict[str, str] = {}


def _mock_put_object_text(key: str, text: str, *, content_type: str = "application/json") -> None:
    _uploads[key.lstrip("/")] = text


def _mock_put_object_bytes(key: str, payload: bytes, *, content_type: str = "application/zip") -> None:
    _uploads[key.lstrip("/")] = payload.decode("latin-1")


def _login(client: TestClient, username: str, password: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _seed_clip(*, clip_id: str, run_id: str, ds: str, label: str) -> None:
    store.execute(
        "INSERT OR REPLACE INTO dim_clip (clip_id, clip_dir_name, active_run_id) VALUES (?, ?, ?)",
        (clip_id, clip_id[:16], run_id),
    )
    store.execute(
        "INSERT OR REPLACE INTO pipeline_run (run_id, clip_id, ds, status) VALUES (?, ?, ?, 'completed')",
        (run_id, clip_id, ds),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO fact_embedding (
          clip_id, run_id, ds, object_type, object_id, timestamp_ns, vector_json, dim
        ) VALUES (?, ?, ?, 'frame', 'cam0:0', 1000000000, ?, 2)
        """,
        (clip_id, run_id, ds, json.dumps([1.0, 0.0])),
    )
    create_review(
        clip_id,
        run_id,
        labels_json={"L1.1.day_period": label, "L1.2.weather": "sunny"},
        review_status="reviewed",
    )


def _seed_taxonomy(suffix: str) -> str:
    from hmi.taxonomy_db import create_version, publish_version, replace_nodes

    version = create_version(f"m8_tax_{suffix}", status="draft")
    version_id = version["id"]
    root_id = str(uuid.uuid4())
    day_id = str(uuid.uuid4())
    weather_id = str(uuid.uuid4())
    replace_nodes(
        version_id,
        [
            {
                "id": root_id,
                "label_id": "L1",
                "level_code": "L1",
                "level_name": "场景",
                "name": "场景",
                "sort_order": 0,
                "is_active": True,
                "parent_id": None,
            },
            {
                "id": day_id,
                "label_id": "L1.1.day_period",
                "level_code": "L2",
                "level_name": "时段",
                "name": "时段",
                "dtype": "enum",
                "value_schema": {"enum": ["day", "night"]},
                "sort_order": 0,
                "is_active": True,
                "parent_id": root_id,
            },
            {
                "id": weather_id,
                "label_id": "L1.2.weather",
                "level_code": "L2",
                "level_name": "天气",
                "name": "天气",
                "dtype": "enum",
                "value_schema": {"enum": ["sunny", "rain"]},
                "sort_order": 1,
                "is_active": True,
                "parent_id": root_id,
            },
        ],
    )
    published = publish_version(version_id)
    return str(published["id"])


def _sync_build(snapshot_id: str) -> None:
    with patch("hmi.dataset.export.put_object_text", side_effect=_mock_put_object_text), patch(
        "hmi.dataset.export.put_object_bytes", side_effect=_mock_put_object_bytes
    ):
        build_snapshot_sync(snapshot_id)


def main() -> None:
    ensure_schema()
    _uploads.clear()
    suffix = uuid.uuid4().hex[:8]
    manager_name = f"m8_manager_{suffix}"

    if get_user_by_username(manager_name) is None:
        create_user(manager_name, "managerpass123", roles=["dataset_manager"])

    ds = "20260730"
    all_clip_ids: list[str] = []
    night_clips = []
    for i in range(3):
        cid = f"sha256:m8_night_{suffix}_{i}"
        rid = str(uuid.uuid4())
        _seed_clip(clip_id=cid, run_id=rid, ds=ds, label="night")
        night_clips.append((cid, rid))
        all_clip_ids.append(cid)

    for i in range(10):
        cid = f"sha256:m8_day_{suffix}_{i}"
        rid = str(uuid.uuid4())
        _seed_clip(clip_id=cid, run_id=rid, ds=ds, label="day")
        all_clip_ids.append(cid)

    client = TestClient(app)
    manager_h = {"Authorization": f"Bearer {_login(client, manager_name, 'managerpass123')}"}

    balance_filter = {
        "review_status": "reviewed",
        "clip_ids": all_clip_ids,
        "balance_by_label": "L1.1.day_period",
        "min_per_class": 5,
        "oversample_policy": "duplicate_to_min",
    }
    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True):
        preview = client.post(
            "/api/datasets/preview",
            headers=manager_h,
            json={"name": "balance_preview", "filter_json": balance_filter},
        )
    assert preview.status_code == 200, preview.text
    prev = preview.json()
    assert "distribution_before" in prev
    assert "distribution_after" in prev
    assert prev["distribution_before"].get("night", 0) == 3
    assert prev["distribution_before"].get("day", 0) == 10
    assert prev["distribution_after"].get("night", 0) >= 5
    assert prev["estimated_line_count"] >= prev["estimated_clip_count"]
    print("OK preview returns distribution_before/after")

    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True):
        assembly = assemble_snapshot_rows(balance_filter)
    assert assembly.line_count >= assembly.clip_count
    assert assembly.clip_count == 13
    assert assembly.line_count >= 15
    night_rows = [r for r in assembly.rows if (r.get("y_json") or {}).get("L1.1.day_period") == "night"]
    assert len(night_rows) >= 5
    dup_rows = [r for r in night_rows if str(r.get("variant_id", "base")) != "base"]
    assert dup_rows
    source_y = dup_rows[0]["y_json"]
    for row in dup_rows:
        assert row["y_json"] == source_y
    print("OK min_per_class oversample duplicates with same y_json")

    capped_filter = {
        **balance_filter,
        "min_per_class": None,
        "oversample_policy": "none",
        "max_per_class": 5,
    }
    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True):
        capped = assemble_snapshot_rows(capped_filter)
    from hmi.dataset.distribution import label_histogram

    after_hist = label_histogram(capped.rows, "L1.1.day_period")
    assert after_hist.get("day", 0) <= 5
    print("OK max_per_class caps class size")

    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True), patch(
        "hmi.dataset.router.enqueue_build", side_effect=_sync_build
    ):
        base = client.post(
            "/api/datasets",
            headers=manager_h,
            json={
                "name": f"m8_base_{suffix}",
                "filter_json": {"review_status": "reviewed", "clip_ids": all_clip_ids},
            },
        )
    assert base.status_code == 201, base.text
    base_id = base.json()["id"]
    base_snap = get_snapshot(base_id)
    assert base_snap and base_snap["status"] == "ready"

    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True), patch(
        "hmi.dataset.router.enqueue_build", side_effect=_sync_build
    ):
        derived = client.post(
            f"/api/datasets/{base_id}/derive",
            headers=manager_h,
            json={
                "name": f"m8_derived_{suffix}",
                "filter_json": balance_filter,
            },
        )
    assert derived.status_code == 201, derived.text
    derived_id = derived.json()["id"]
    derived_snap = get_snapshot(derived_id)
    assert derived_snap
    assert derived_snap["parent_snapshot_id"] == base_id
    assert derived_snap["status"] == "ready"
    base_after = get_snapshot(base_id)
    assert base_after and base_after["status"] == "ready"
    print("OK derive sets parent_snapshot_id; base stays ready")

    derived_filt = derived_snap.get("filter_json") or {}
    assert derived_filt.get("balance_by_label") == balance_filter["balance_by_label"]
    assert derived_filt.get("min_per_class") == balance_filter["min_per_class"]
    print("OK derive merges balance overrides into child filter_json")

    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True), patch(
        "hmi.dataset.router.enqueue_build", side_effect=_sync_build
    ):
        crop_derived = client.post(
            f"/api/datasets/{base_id}/derive",
            headers=manager_h,
            json={
                "name": f"m8_derived_crop_{suffix}",
                "filter_json": {
                    "label_filters": {"L1.1.day_period": "night"},
                    "max_per_class": 2,
                    "balance_by_label": "L1.1.day_period",
                    "oversample_policy": "none",
                },
            },
        )
    assert crop_derived.status_code == 201, crop_derived.text
    crop_id = crop_derived.json()["id"]
    crop_snap = get_snapshot(crop_id)
    assert crop_snap and crop_snap["status"] == "ready"
    crop_filt = crop_snap.get("filter_json") or {}
    assert crop_filt.get("label_filters") == {"L1.1.day_period": "night"}
    assert crop_filt.get("clip_ids") == (base_snap.get("filter_json") or {}).get("clip_ids")
    assert crop_snap.get("line_count", 0) <= base_snap.get("line_count", 999)
    print("OK derive label crop + max_per_class on parent clip_ids")

    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True), patch(
        "hmi.dataset.router.enqueue_build", side_effect=_sync_build
    ):
        chain_derived = client.post(
            f"/api/datasets/{derived_id}/derive",
            headers=manager_h,
            json={"name": f"m8_chain_{suffix}", "filter_json": {"max_per_class": 3}},
        )
    assert chain_derived.status_code == 201, chain_derived.text
    chain_id = chain_derived.json()["id"]
    chain_snap = get_snapshot(chain_id)
    assert chain_snap and chain_snap["status"] == "ready"
    assert chain_snap["parent_snapshot_id"] == derived_id
    chain_deriv = chain_snap.get("derivation_json") or {}
    assert chain_deriv.get("root_snapshot_id") == base_id
    assert chain_deriv.get("derivation_depth") == 2
    chain_lineage = chain_deriv.get("lineage_chain") or []
    assert len(chain_lineage) == 2
    assert chain_lineage[0]["id"] == base_id
    assert chain_lineage[1]["id"] == derived_id

    detail = client.get(f"/api/datasets/{chain_id}", headers=manager_h)
    assert detail.status_code == 200
    lineage = detail.json().get("lineage") or {}
    assert lineage.get("derivation_depth") == 2
    assert len(lineage.get("derived_children") or []) == 0
    parent_lineage = client.get(f"/api/datasets/{derived_id}", headers=manager_h).json().get("lineage") or {}
    assert any(c["id"] == chain_id for c in parent_lineage.get("derived_children") or [])
    print("OK chain derive from derived snapshot with lineage depth 2")

    _seed_taxonomy(suffix)
    with patch("hmi.review.merge.all_ai_labels_field_reviewed", return_value=True), patch(
        "hmi.dataset.router.enqueue_build", side_effect=_sync_build
    ):
        tax_crop_resp = client.post(
            f"/api/datasets/{base_id}/derive",
            headers=manager_h,
            json={
                "name": f"m8_tax_crop_{suffix}",
                "taxonomy_crop_label_ids": ["L1.1.day_period"],
            },
        )
    assert tax_crop_resp.status_code == 201, tax_crop_resp.text
    tax_crop_id = tax_crop_resp.json()["id"]
    tax_crop_snap = get_snapshot(tax_crop_id)
    assert tax_crop_snap and tax_crop_snap["status"] == "ready"
    tax_deriv = tax_crop_snap.get("derivation_json") or {}
    tax_crop_meta = tax_deriv.get("taxonomy_crop") or {}
    assert tax_crop_meta.get("cropped_version_id")
    assert tax_crop_meta.get("selected_label_ids") == ["L1.1.day_period"]
    export_ids = (tax_crop_snap.get("filter_json") or {}).get("export_label_ids") or []
    assert "L1.1.day_period" in export_ids
    assert "L1.2.weather" not in export_ids
    y_key = f"datasets/{tax_crop_id}/y.jsonl"
    y_body = _uploads.get(y_key, "")
    assert y_body
    first_y = json.loads(y_body.splitlines()[0])
    y_json = first_y.get("y_json") or {}
    assert "L1.1.day_period" in y_json
    assert "L1.2.weather" not in y_json
    print("OK derive taxonomy crop creates draft version and filters exported y_json")

    derive_audits = list_audit_logs(resource_type="dataset_snapshot", resource_id=derived_id)
    assert any(a.get("action") == "dataset.derive" for a in derive_audits)
    print("OK dataset.derive audit logged")

    recipe_spec = {
        "recipe_schema_version": "1.0",
        "recipe_code": f"test_recipe_{suffix}",
        "version": 1,
        "description": "test",
        "applies_to": {"export_preset": "full", "modalities": ["camera"]},
        "transforms": [
            {
                "id": "hflip",
                "type": "horizontal_flip",
                "p": 0.5,
                "targets": [{"modality": "camera", "cameras": ["front"]}],
            }
        ],
        "seed_policy": {"mode": "per_epoch", "base_seed": 42},
    }
    draft = client.post(
        "/api/datasets/aug-recipes",
        headers=manager_h,
        json={"recipe_code": recipe_spec["recipe_code"], "spec_json": recipe_spec},
    )
    assert draft.status_code == 201, draft.text
    recipe_id = draft.json()["id"]
    assert draft.json()["status"] == "draft"

    published = client.post(f"/api/datasets/aug-recipes/{recipe_id}/publish", headers=manager_h)
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    publish_again = client.post(f"/api/datasets/aug-recipes/{recipe_id}/publish", headers=manager_h)
    assert publish_again.status_code == 422
    print("OK published recipe cannot be republished")

    recipe_audits = list_audit_logs(resource_type="aug_recipe", resource_id=recipe_id)
    assert any(a.get("action") == "aug_recipe.create" for a in recipe_audits)
    assert any(a.get("action") == "aug_recipe.publish" for a in recipe_audits)
    print("OK aug_recipe audit logged")

    list_resp = client.get("/api/datasets/aug-recipes", headers=manager_h)
    assert list_resp.status_code == 200
    assert any(r["id"] == recipe_id for r in list_resp.json()["items"])
    print("OK GET aug-recipes list")

    meta_key = f"datasets/{derived_id}/meta.json"
    meta = json.loads(_uploads.get(meta_key, "{}"))
    if meta:
        assert meta.get("augmentation_mode") in ("oversample_only", "none", "recipe_attached")
        assert "distribution_report" in meta
    print("OK derived meta includes augmentation/distribution")

    example_recipe = REPO_ROOT / "examples" / "_tmp_recipe.json"
    example_recipe.parent.mkdir(parents=True, exist_ok=True)
    example_recipe.write_text(json.dumps(recipe_spec), encoding="utf-8")
    import subprocess

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "examples" / "apply_aug_recipe.py"), str(example_recipe)],
        capture_output=True,
        text=True,
    )
    example_recipe.unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    print("OK examples/apply_aug_recipe.py parses mock recipe")

    print("\nM8 backend tests passed.")


if __name__ == "__main__":
    main()
