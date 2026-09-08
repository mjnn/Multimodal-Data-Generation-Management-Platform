"""Idempotent NVH clip for UI-NVH-REVIEW-SAVE Playwright (live hmi_runtime)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))

CLIP_ID = "sha256:nvh_review_e2e"
RUN_ID = "run-nvh-review-e2e"
DS_DAY = "20260904"


def _labels() -> dict:
    return {
        "nvh.clip.spl.leq_db_mean": 94.5,
        "nvh.clip.spl.level_class": "high",
        "nvh.sem.noise_category": "tonal",
        "nvh.sem.quality_grade": "C",
        "_meta": {
            "taxonomy_version_code": "audio_nvh-v2",
            "deriver_version": "nvh_deriver-v1",
            "label_source": "derive_nvh_labels+nvh_ai_label",
        },
    }


def main() -> None:
    from hmi.app_db import ensure_schema
    from hmi.data_source import artifacts_dir
    from hmi.local import pipeline_execution as pe
    from hmi.local import pipeline_run as pr
    from hmi.local import store as local_store
    from hmi.local.nvh_deriver import apply_nvh_labels_to_facts, persist_nvh_labels_artifact
    from hmi.platform.store import ensure_platform_schema

    ensure_schema()
    ensure_platform_schema()
    local_store.ensure_db()

    pr.upsert_clip_row(
        clip_id=CLIP_ID,
        clip_dir_name="nvh_review_e2e",
        content_hash="nvh-review-e2e",
        bag_oss_key="local://sources/nvh_review_e2e/source_manifest.json",
        active_run_id=RUN_ID,
    )
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    pe.create_execution_record(
        run_id=RUN_ID,
        label="nvh-review-e2e",
        started_at=now,
        data_type_id="audio_array_spec",
    )
    pr.upsert_run(run_id=RUN_ID, clip_id=CLIP_ID, ds=DS_DAY, status="completed")

    root = artifacts_dir(CLIP_ID, RUN_ID)
    spec = root / "audio_spec"
    spec.mkdir(parents=True, exist_ok=True)
    (spec / "summary.json").write_text(
        json.dumps(
            {
                "fs_hz": 48000,
                "duration_s": 1.0,
                "unit": "Pa",
                "channels": [{"name": "VL", "leq_db": 94.5}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    persist_nvh_labels_artifact(root, _labels())
    apply_nvh_labels_to_facts(
        clip_id=CLIP_ID,
        run_id=RUN_ID,
        ds=DS_DAY,
        labels=_labels(),
        update_platform_run=False,
    )
    print(f"{CLIP_ID} {RUN_ID}")


if __name__ == "__main__":
    main()
