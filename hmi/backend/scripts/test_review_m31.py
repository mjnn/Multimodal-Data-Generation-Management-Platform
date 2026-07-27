"""M3.1 review DB + audit_log smoke test."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.audit import append_audit_log, list_audit_logs
from hmi.review_db import (
    REVIEW_STATUSES,
    create_review,
    get_review,
    list_reviews,
    update_review,
)


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"m31_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        user = create_user(reviewer_name, "reviewpass123", roles=["reviewer"])
        reviewer_id = user["id"]
    else:
        reviewer_id = get_user_by_username(reviewer_name)["id"]

    clip_id = f"sha256:m31_{suffix}"
    run_id = str(uuid.uuid4())
    labels = {"L1.1.day_period": "morning", "L1.1.is_holiday": False}
    summary = {"source": "test", "frame_count": 3}

    review = create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="pending_review",
        ai_source_summary_json=summary,
    )
    assert review["review_status"] == "pending_review"
    assert review["labels_json"] == labels
    print("OK create_review")

    try:
        create_review(clip_id, run_id, labels_json=labels)
        print("FAIL duplicate review should raise")
        raise SystemExit(1)
    except ValueError as exc:
        assert "already exists" in str(exc)
    print("OK duplicate rejected")

    pending = list_reviews(review_status="pending_review", limit=10)
    assert any(r["id"] == review["id"] for r in pending)
    print("OK list_reviews pending")

    updated = update_review(
        clip_id,
        run_id,
        labels_json={"L1.1.day_period": "night"},
        review_status="reviewed",
        reviewer_id=reviewer_id,
        expected_updated_at=review["updated_at"],
    )
    assert updated["review_status"] == "reviewed"
    assert updated["reviewer_id"] == reviewer_id
    assert updated["reviewed_at"]
    print("OK update_review -> reviewed")

    try:
        update_review(
            clip_id,
            run_id,
            labels_json=labels,
            expected_updated_at="1970-01-01T00:00:00+00:00",
        )
        print("FAIL stale updated_at should raise")
        raise SystemExit(1)
    except ValueError as exc:
        assert "conflict" in str(exc)
    print("OK optimistic lock conflict")

    log = append_audit_log(
        actor_id=reviewer_id,
        action="clip.review",
        resource_type="clip_label_review",
        resource_id=review["id"],
        detail={"clip_id": clip_id, "run_id": run_id},
    )
    logs = list_audit_logs(resource_type="clip_label_review", resource_id=review["id"])
    assert any(l["id"] == log["id"] for l in logs)
    print("OK audit_log append + list")

    assert get_review(clip_id, run_id) is not None
    assert REVIEW_STATUSES == frozenset({"pending_review", "reviewed"})
    print("\nAll M3.1 checks passed.")


if __name__ == "__main__":
    main()
