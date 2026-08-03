"""M6.2 review v2 task queue API smoke test."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HMI_JWT_SECRET", "test-jwt-secret-at-least-32-characters-long")

from fastapi.testclient import TestClient

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.main import app
from hmi.review.field_review_db import upsert_field_review
from hmi.review.v2_tasks import (
    build_low_confidence_claim_tasks,
    build_pending_tasks,
    clear_sessions,
    encode_cursor,
    filter_low_confidence_claim_tasks,
    get_or_reset_session,
    pick_next_task,
    prev_session_task,
    advance_session,
)


def _login(client: TestClient, username: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _mock_views() -> dict[tuple[str, str], dict]:
    return {
        ("sha256:demo_morning_city", "run-a"): {
            "clip_label_ready": True,
            "labels_json": {"L1.1.day_period": None, "L1.1.is_holiday": False},
            "disputed_label_ids": ["L1.1.day_period"],
            "dispute_count": 1,
            "label_preview": "is_holiday=False",
            "anchor_timestamp_ns": 8_000_000_000,
        },
        ("sha256:demo_holiday_mall", "run-b"): {
            "clip_label_ready": True,
            "labels_json": {"L1.1.day_period": "morning", "L1.1.is_holiday": True},
            "disputed_label_ids": ["L1.1.is_holiday"],
            "dispute_count": 1,
            "label_preview": "morning",
            "anchor_timestamp_ns": 20_000_000_000,
        },
        ("sha256:demo_afternoon_park", "run-c"): {
            "clip_label_ready": True,
            "labels_json": {"L1.1.day_period": "afternoon", "L1.1.is_holiday": False},
            "disputed_label_ids": [],
            "dispute_count": 0,
            "label_preview": "afternoon",
            "anchor_timestamp_ns": 15_000_000_000,
        },
    }


def main() -> None:
    ensure_schema()
    clear_sessions()
    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"m62_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        create_user(reviewer_name, "reviewpass123", roles=["reviewer"])
    password = "reviewpass123"

    candidates = [
        {"clip_id": "sha256:demo_morning_city", "run_id": "run-a"},
        {"clip_id": "sha256:demo_holiday_mall", "run_id": "run-b"},
        {"clip_id": "sha256:demo_afternoon_park", "run_id": "run-c"},
    ]
    views = _mock_views()

    def fake_view(clip_id: str, run_id: str, *, ds: str | None = None):
        return views.get((clip_id, run_id), {"clip_label_ready": False, "labels_json": {}})

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch("hmi.review.v2_tasks.load_ai_label_hints_local", return_value={}):
                                with patch(
                                    "hmi.review.v2_tasks._clip_dir_name",
                                    side_effect=lambda cid: cid.split(":")[-1],
                                ):
                                    tasks = build_pending_tasks("confidence")
    assert len(tasks) == 6
    assert tasks[0]["label_id"] == "L1.1.day_period"
    assert tasks[0]["clip_id"] == "sha256:demo_morning_city"
    assert tasks[0]["priority_bucket"] == 0
    assert tasks[1]["clip_id"] == "sha256:demo_afternoon_park"
    assert tasks[1]["label_id"] == "L1.1.day_period"
    print("OK confidence ordering empty first then low-confidence sort")

    hints_by_clip = {
        ("sha256:demo_holiday_mall", "run-b"): {
            "L1.1.is_holiday": {"confidence": 0.3, "evidence": "e"},
        },
    }

    def fake_hints(clip_id: str, run_id: str):
        return hints_by_clip.get((clip_id, run_id), {})

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch(
                                "hmi.review.v2_tasks.load_ai_label_hints_local",
                                side_effect=fake_hints,
                            ):
                                with patch(
                                    "hmi.review.v2_tasks._clip_dir_name",
                                    side_effect=lambda cid: cid.split(":")[-1],
                                ):
                                    ordered = build_pending_tasks("confidence")
    idx_holiday_dispute = next(
        i
        for i, t in enumerate(ordered)
        if t["clip_id"] == "sha256:demo_holiday_mall" and t["label_id"] == "L1.1.is_holiday"
    )
    idx_afternoon_holiday = next(
        i
        for i, t in enumerate(ordered)
        if t["clip_id"] == "sha256:demo_afternoon_park" and t["label_id"] == "L1.1.is_holiday"
    )
    assert idx_holiday_dispute > idx_afternoon_holiday
    print("OK confidence ascending among non-empty")

    high_conf_hints = {
        ("sha256:demo_afternoon_park", "run-c"): {
            "L1.1.day_period": {"confidence": 0.8, "evidence": "high"},
        },
    }

    def fake_high_conf_hints(clip_id: str, run_id: str):
        return high_conf_hints.get((clip_id, run_id), {})

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch(
                                "hmi.review.v2_tasks.load_ai_label_hints_local",
                                side_effect=fake_high_conf_hints,
                            ):
                                with patch(
                                    "hmi.review.v2_tasks._clip_dir_name",
                                    side_effect=lambda cid: cid.split(":")[-1],
                                ):
                                    all_tasks = build_pending_tasks("confidence")
                                    claimable = filter_low_confidence_claim_tasks(all_tasks)
                                    high_conf_task = next(
                                        t
                                        for t in all_tasks
                                        if t["clip_id"] == "sha256:demo_afternoon_park"
                                        and t["label_id"] == "L1.1.day_period"
                                    )
    assert high_conf_task["priority_bucket"] == 3
    assert high_conf_task not in claimable
    assert len(build_low_confidence_claim_tasks(100)) == len(claimable)
    print("OK low-confidence claim excludes confidence >= 75%")

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch("hmi.review.v2_tasks._clip_dir_name", side_effect=lambda cid: cid.split(":")[-1]):
                                comp = build_pending_tasks(
                                    "comprehensive",
                                    label_id="L1.1.day_period",
                                    filter_value="morning",
                                )
    assert len(comp) == 1
    assert comp[0]["clip_id"] == "sha256:demo_holiday_mall"
    print("OK comprehensive filter ai_value=morning")

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch("hmi.review.v2_tasks._clip_dir_name", side_effect=lambda cid: cid.split(":")[-1]):
                                first = pick_next_task("confidence")
                                assert first is not None
                                cur = encode_cursor(first["clip_id"], first["run_id"], first["label_id"])
                                second = pick_next_task("confidence", cursor=cur)
                                assert second is not None
                                assert second["clip_id"] == "sha256:demo_afternoon_park"
                                assert second["label_id"] == "L1.1.day_period"
    print("OK pick_next_task cursor")

    session = get_or_reset_session("user-1", "confidence")
    assert session.index == -1
    advance_session(session, {"clip_id": "a", "run_id": "r", "label_id": "L1"})
    advance_session(session, {"clip_id": "b", "run_id": "r", "label_id": "L2"})
    assert session.index == 1
    prev = prev_session_task(session)
    assert prev["clip_id"] == "a"
    print("OK session prev")

    client = TestClient(app)
    token = _login(client, reviewer_name, password)
    headers = {"Authorization": f"Bearer {token}"}

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=set()):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch("hmi.review.v2_tasks._clip_dir_name", side_effect=lambda cid: cid.split(":")[-1]):
                                res = client.get(
                                    "/api/review/v2/next?mode=confidence",
                                    headers=headers,
                                )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["task"]["label_id"] == "L1.1.day_period"
    assert body["session"]["history_index"] == 0
    print("OK GET /api/review/v2/next")

    res = client.get("/api/review/v2/tasks/stats?mode=ai_dispute", headers=headers)
    assert res.status_code == 200
    assert res.json()["mode"] == "confidence"
    print("OK legacy ai_dispute stats alias")

    res = client.get(
        "/api/review/v2/next?mode=comprehensive&label_id=L1.1.day_period",
        headers=headers,
    )
    assert res.status_code == 422
    print("OK comprehensive without value -> 422")

    with patch("hmi.review.v2_tasks._active_label_candidate_pairs", return_value=candidates):
        with patch("hmi.review.v2_tasks.get_clip_label_view_for_queue", side_effect=fake_view):
            reviewed = {("sha256:demo_morning_city", "run-a", "L1.1.day_period")}
            with patch("hmi.review.v2_tasks.field_review_key_set", return_value=reviewed):
                with patch("hmi.review.v2_tasks.resolve_ds_for_run", return_value="20260721"):
                    with patch("hmi.review.v2_tasks.resolve_clip_thumbnail", return_value=None):
                        with patch("hmi.review.v2_tasks.get_review", return_value=None):
                            with patch("hmi.review.v2_tasks._clip_dir_name", side_effect=lambda cid: cid.split(":")[-1]):
                                res = client.get("/api/review/v2/tasks/stats?mode=confidence", headers=headers)
    assert res.status_code == 200
    assert res.json()["pending"] == 5
    print("OK field-reviewed tasks excluded")

    res = client.get("/api/review/v2/label-options?keyword=day", headers=headers)
    assert res.status_code == 200
    assert res.json()["total"] >= 0
    print("OK GET /api/review/v2/label-options")

    trainer = f"m62_trainer_{suffix}"
    create_user(trainer, "trainerpass123", roles=["model_trainer"])
    trainer_token = _login(client, trainer, "trainerpass123")
    res = client.get(
        "/api/review/v2/next?mode=ai_dispute",
        headers={"Authorization": f"Bearer {trainer_token}"},
    )
    assert res.status_code == 403
    print("OK model_trainer forbidden on next")

    clear_sessions()
    print("\nAll M6.2 checks passed.")


if __name__ == "__main__":
    main()
