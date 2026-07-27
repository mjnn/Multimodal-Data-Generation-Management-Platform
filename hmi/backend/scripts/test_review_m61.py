"""M6.1 field review DB + merge into clip_label_review smoke test."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.app_db import create_user, ensure_schema, get_user_by_username
from hmi.review.field_review_db import (
    FIELD_REVIEW_ACTIONS,
    count_field_reviews,
    delete_field_reviews,
    get_field_review,
    list_field_review_label_ids,
    upsert_field_review,
)
from hmi.review.merge import (
    all_ai_labels_field_reviewed,
    apply_field_review,
    merge_label_into_clip_dict,
    resolve_field_review_value,
)
from hmi.review_db import create_review, get_review, update_review


def main() -> None:
    ensure_schema()
    suffix = uuid.uuid4().hex[:8]
    reviewer_name = f"m61_reviewer_{suffix}"
    if get_user_by_username(reviewer_name) is None:
        user = create_user(reviewer_name, "reviewpass123", roles=["reviewer"])
        reviewer_id = user["id"]
    else:
        reviewer_id = get_user_by_username(reviewer_name)["id"]

    clip_id = f"sha256:m61_{suffix}"
    run_id = str(uuid.uuid4())
    labels = {"L1.1.day_period": "morning", "L1.1.is_holiday": False}

    create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="pending_review",
    )
    print("OK create_review baseline")

    assert FIELD_REVIEW_ACTIONS == frozenset({"confirm", "correct", "uncertain"})

    field = upsert_field_review(
        clip_id,
        run_id,
        "L1.1.day_period",
        action="correct",
        value="afternoon",
        human_doubtful=False,
        ai_value="morning",
        taxonomy_version_id=None,
        reviewer_id=reviewer_id,
    )
    assert field["action"] == "correct"
    assert field["value_json"] == "afternoon"
    assert field["human_doubtful"] is False
    print("OK upsert_field_review")

    field2 = upsert_field_review(
        clip_id,
        run_id,
        "L1.1.day_period",
        action="uncertain",
        value=None,
        human_doubtful=True,
        ai_value="morning",
        taxonomy_version_id=None,
        reviewer_id=reviewer_id,
    )
    assert field2["id"] == field["id"]
    assert field2["action"] == "uncertain"
    assert field2["value_json"] is None
    assert field2["human_doubtful"] is True
    print("OK upsert_field_review overwrite")

    assert count_field_reviews(clip_id, run_id) == 1
    assert list_field_review_label_ids(clip_id, run_id) == ["L1.1.day_period"]
    assert get_field_review(clip_id, run_id, "L1.1.day_period") is not None
    print("OK field review queries")

    val, doubtful = resolve_field_review_value(action="confirm", ai_value="morning")
    assert val == "morning" and doubtful is False
    val, doubtful = resolve_field_review_value(action="uncertain", ai_value="morning")
    assert val is None and doubtful is True
    val, doubtful = resolve_field_review_value(action="correct", ai_value="morning", value="night")
    assert val == "night" and doubtful is False
    print("OK resolve_field_review_value")

    merged = merge_label_into_clip_dict(labels, "L1.1.day_period", None)
    assert merged["L1.1.day_period"] is None
    assert merged["L1.1.is_holiday"] is False
    print("OK merge_label_into_clip_dict")

    ai_ids = ["L1.1.day_period", "L1.1.is_holiday"]
    with patch("hmi.review.merge.get_ai_label_ids", return_value=ai_ids):
        assert all_ai_labels_field_reviewed(clip_id, run_id) is False
        upsert_field_review(
            clip_id,
            run_id,
            "L1.1.is_holiday",
            action="confirm",
            value=False,
            human_doubtful=False,
            ai_value=False,
            taxonomy_version_id=None,
            reviewer_id=reviewer_id,
        )
        assert all_ai_labels_field_reviewed(clip_id, run_id) is True
    print("OK all_ai_labels_field_reviewed")

    # apply_field_review merge + rollup
    clip_b = f"sha256:m61b_{suffix}"
    run_b = str(uuid.uuid4())
    create_review(
        clip_b,
        run_b,
        labels_json={"L1.1.day_period": "morning", "L1.1.is_holiday": True},
        review_status="pending_review",
    )
    delete_field_reviews(clip_b, run_b)

    with patch("hmi.review.merge.get_ai_label_ids", return_value=ai_ids):
        with patch(
            "hmi.review.merge.get_ai_label_value",
            side_effect=lambda _c, _r, lid: {"L1.1.day_period": "morning", "L1.1.is_holiday": True}[lid],
        ):
            r1 = apply_field_review(
                clip_id=clip_b,
                run_id=run_b,
                label_id="L1.1.day_period",
                action="confirm",
                reviewer_id=reviewer_id,
            )
            assert r1["clip_review"]["labels_json"]["L1.1.day_period"] == "morning"
            assert r1["clip_review"]["review_status"] == "pending_review"
            assert r1["rolled_up_to_reviewed"] is False

            r2 = apply_field_review(
                clip_id=clip_b,
                run_id=run_b,
                label_id="L1.1.is_holiday",
                action="uncertain",
                reviewer_id=reviewer_id,
            )
            assert r2["clip_review"]["labels_json"]["L1.1.is_holiday"] is None
            assert r2["field_review"]["human_doubtful"] is True
            assert r2["clip_review"]["review_status"] == "reviewed"
            assert r2["rolled_up_to_reviewed"] is True
    print("OK apply_field_review merge + rollup")

    review_b = get_review(clip_b, run_b)
    assert review_b is not None
    assert review_b["review_status"] == "reviewed"
    assert review_b["labels_json"]["L1.1.is_holiday"] is None

    deleted = delete_field_reviews(clip_b, run_b)
    assert deleted == 2
    assert count_field_reviews(clip_b, run_b) == 0
    print("OK delete_field_reviews")

    # optimistic lock on clip review
    review = get_review(clip_id, run_id)
    assert review is not None
    stale = review["updated_at"]
    update_review(clip_id, run_id, labels_json=labels, expected_updated_at=stale)
    review = get_review(clip_id, run_id)
    assert review is not None
    try:
        with patch("hmi.review.merge.get_ai_label_ids", return_value=["L1.1.day_period"]):
            with patch("hmi.review.merge.get_ai_label_value", return_value="morning"):
                apply_field_review(
                    clip_id=clip_id,
                    run_id=run_id,
                    label_id="L1.1.day_period",
                    action="confirm",
                    reviewer_id=reviewer_id,
                    expected_clip_updated_at=stale,
                )
        print("FAIL stale updated_at should raise")
        raise SystemExit(1)
    except ValueError as exc:
        assert "conflict" in str(exc)
    print("OK clip-level optimistic lock")

    print("\nAll M6.1 checks passed.")


if __name__ == "__main__":
    main()
