#!/usr/bin/env python3
"""Generate clip-omni v2 pipeline mock artifacts for demo / verification.

Usage (repo root):
  py -3 scripts/mock_pipeline_artifacts.py --list
  py -3 scripts/mock_pipeline_artifacts.py --clip demo_morning_city
  py -3 scripts/mock_pipeline_artifacts.py --all --reset
  py -3 scripts/mock_pipeline_artifacts.py --export-fixtures
"""

from __future__ import annotations

import argparse
import base64
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND = PROJECT_ROOT / "backend"
SCRIPTS = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(SCRIPTS))

from hmi.ai_artifacts import ingest_v2_ai_from_local_artifacts
from hmi.app_db import ensure_schema
from hmi.clip_consensus import attach_consensus_fields
from hmi.clip_facts import upsert_clip_embedding, upsert_clip_label
from hmi.config import PIPELINE_STEP_ORDER
from hmi.data_source import artifacts_dir
from hmi.local import store
from hmi.review.enqueue import enqueue_clip
from hmi.review_db import create_review, get_review
from mock_pipeline_run import (
    AGREEMENT_THRESHOLD,
    MockRunSpec,
    artifact_checklist,
    write_full_mock_run,
)

DS = "20260721"
START_NS = int(datetime(2026, 7, 21, 8, 30, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp() * 1_000_000_000)
DURATION_SEC = 32.0
END_NS = START_NS + int(DURATION_SEC * 1_000_000_000)

_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

# Demo scenarios — cover full AI dual-model labeling matrix (threshold=0.7).
# Types: unlabeled | unanimous+gate_pass | mild_dispute+gate_pass | severe_dispute+gate_fail
#        | multi_field_gate_fail | borderline_gate_fail | reviewed | partial_field_review
MOCK_SCENARIOS: dict[str, dict] = {
    "demo_morning_city": {
        "clip_id": "sha256:demo_morning_city",
        "run_id": "00000000-0001-4000-8000-000000000001",
        "day_period": "morning",
        "is_holiday": False,
        "secondary_day_period": "afternoon",
        "anchor_ns": START_NS + 8_000_000_000,
        "vector": [0.92, 0.08, 0.05, 0.12],
        "gate": "fail",
        "scenario_type": "severe_dispute_gate_fail",
        "note": "严重分歧·未达阈值(50%)：day_period 留空；is_holiday 一致",
        "review_status": "pending_review",
    },
    "demo_holiday_mall": {
        "clip_id": "sha256:demo_holiday_mall",
        "run_id": "00000000-0001-4000-8000-000000000004",
        "day_period": "morning",
        "is_holiday": True,
        "secondary_is_holiday": False,
        "anchor_ns": START_NS + 20_000_000_000,
        "vector": [0.88, 0.12, 0.08, 0.15],
        "gate": "fail",
        "scenario_type": "severe_dispute_gate_fail",
        "note": "严重分歧·未达阈值(50%)：is_holiday 留空；day_period 一致",
        "review_status": "pending_review",
    },
    "demo_gate_fail_both": {
        "clip_id": "sha256:demo_gate_fail_both",
        "run_id": "00000000-0001-4000-8000-000000000006",
        "anchor_ns": START_NS + 18_000_000_000,
        "vector": [0.70, 0.20, 0.15, 0.18],
        "gate": "fail",
        "scenario_type": "severe_dispute_gate_fail",
        "note": "严重分歧·未达阈值(0%)：day_period + is_holiday 双字段均留空",
        "review_status": "pending_review",
        "primary_labels": {
            "L1.1.day_period": "morning",
            "L1.1.is_holiday": True,
        },
        "secondary_labels": {
            "L1.1.day_period": "night",
            "L1.1.is_holiday": False,
        },
    },
    "demo_gate_borderline_fail": {
        "clip_id": "sha256:demo_gate_borderline_fail",
        "run_id": "00000000-0001-4000-8000-000000000007",
        "anchor_ns": START_NS + 22_000_000_000,
        "vector": [0.55, 0.35, 0.42, 0.28],
        "gate": "fail",
        "scenario_type": "borderline_gate_fail",
        "note": "临界未过阈值(66.7%<70%)：3 字段中 weather 分歧留空",
        "review_status": "pending_review",
        "primary_labels": {
            "L1.1.day_period": "morning",
            "L1.1.is_holiday": False,
            "L1.3.weather": "sunny",
        },
        "secondary_labels": {
            "L1.1.day_period": "morning",
            "L1.1.is_holiday": False,
            "L1.3.weather": "cloudy",
        },
    },
    "demo_gate_pass_majority": {
        "clip_id": "sha256:demo_gate_pass_majority",
        "run_id": "00000000-0001-4000-8000-000000000008",
        "anchor_ns": START_NS + 25_000_000_000,
        "vector": [0.48, 0.52, 0.44, 0.36],
        "gate": "pass",
        "scenario_type": "mild_dispute_gate_pass",
        "note": "轻分歧·达阈值(75%)：light_source 分歧但取 primary，全面校核可见",
        "review_status": "pending_review",
        "primary_labels": {
            "L1.1.day_period": "afternoon",
            "L1.1.is_holiday": False,
            "L1.2.light_source": "natural",
            "L1.3.weather": "sunny",
        },
        "secondary_labels": {
            "L1.1.day_period": "afternoon",
            "L1.1.is_holiday": False,
            "L1.2.light_source": "artificial",
            "L1.3.weather": "sunny",
        },
    },
    "demo_afternoon_park": {
        "clip_id": "sha256:demo_afternoon_park",
        "run_id": "00000000-0001-4000-8000-000000000003",
        "day_period": "afternoon",
        "is_holiday": False,
        "anchor_ns": START_NS + 15_000_000_000,
        "vector": [0.45, 0.40, 0.55, 0.30],
        "gate": "pass",
        "scenario_type": "unanimous_gate_pass",
        "note": "无分歧·达阈值(100%)：双模型完全一致，待校核确认",
        "review_status": "pending_review",
    },
    "demo_night_highway": {
        "clip_id": "sha256:demo_night_highway",
        "run_id": "00000000-0001-4000-8000-000000000002",
        "day_period": "night",
        "is_holiday": False,
        "anchor_ns": START_NS + 12_000_000_000,
        "vector": [0.05, 0.90, 0.88, 0.10],
        "gate": "pass",
        "scenario_type": "unanimous_reviewed",
        "note": "无分歧·达阈值(100%)：已完成人工校核样例",
        "review_status": "reviewed",
    },
    "demo_partial_field_review": {
        "clip_id": "sha256:demo_partial_field_review",
        "run_id": "00000000-0001-4000-8000-000000000009",
        "anchor_ns": START_NS + 28_000_000_000,
        "vector": [0.62, 0.18, 0.22, 0.14],
        "gate": "fail",
        "scenario_type": "partial_field_review",
        "note": "严重分歧·is_holiday 已暂存校核，day_period 仍待审",
        "review_status": "pending_review",
        "primary_labels": {
            "L1.1.day_period": "morning",
            "L1.1.is_holiday": True,
        },
        "secondary_labels": {
            "L1.1.day_period": "afternoon",
            "L1.1.is_holiday": False,
        },
        "seed_field_reviews": [
            {
                "label_id": "L1.1.is_holiday",
                "action": "correct",
                "value": False,
            }
        ],
    },
    "demo_unlabeled": {
        "clip_id": "sha256:demo_unlabeled",
        "run_id": "00000000-0001-4000-8000-000000000005",
        "day_period": None,
        "is_holiday": None,
        "labeled": False,
        "anchor_ns": START_NS + 10_000_000_000,
        "vector": [0.20, 0.20, 0.20, 0.20],
        "gate": "n/a",
        "scenario_type": "unlabeled",
        "note": "未 AI 打标：仅 parsed + aligned，无 ai/ 产物",
        "review_status": None,
    },
}


def _write_images(clip_id: str, run_id: str) -> list[str]:
    rel_paths: list[str] = []
    root = artifacts_dir(clip_id, run_id)
    for cam in ("camera0", "camera1", "camera2", "camera3"):
        rel = f"parsed/output/images/{cam}/000000.jpg"
        out = root / rel.replace("/", "\\") if "\\" in str(root) else root / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(_TINY_PNG)
        rel_paths.append(rel)
    return rel_paths


def _spec_from_scenario(name: str, cfg: dict) -> MockRunSpec:
    labeled = cfg.get("labeled")
    if labeled is None:
        labeled = bool(cfg.get("primary_labels") or cfg.get("day_period") is not None)
    return MockRunSpec(
        clip_id=cfg["clip_id"],
        run_id=cfg["run_id"],
        dir_name=name,
        start_time_ns=START_NS,
        end_time_ns=END_NS,
        duration_sec=DURATION_SEC,
        anchor_ns=int(cfg["anchor_ns"]),
        day_period=cfg.get("day_period"),
        is_holiday=cfg.get("is_holiday"),
        secondary_day_period=cfg.get("secondary_day_period"),
        secondary_is_holiday=cfg.get("secondary_is_holiday"),
        primary_labels=cfg.get("primary_labels"),
        secondary_labels=cfg.get("secondary_labels"),
        agreement_threshold=float(cfg.get("agreement_threshold", AGREEMENT_THRESHOLD)),
        vector=list(cfg.get("vector") or []),
        labeled=bool(labeled),
    )


def _seed_db(clip_id: str, run_id: str, dir_name: str, *, labeled: bool, bag_key: str) -> None:
    store.execute(
        """
        INSERT OR REPLACE INTO dim_clip (
          clip_id, clip_dir_name, content_hash, bag_oss_key, active_run_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, datetime('now'), datetime('now'))
        """,
        (clip_id, dir_name, clip_id.split(":", 1)[-1][:16], bag_key, run_id),
    )
    store.execute(
        """
        INSERT OR REPLACE INTO pipeline_run (
          run_id, clip_id, ds, status, label_granularity, started_at, updated_at, completed_at
        ) VALUES (?, ?, ?, 'completed', ?, datetime('now'), datetime('now'), datetime('now'))
        """,
        (run_id, clip_id, DS, "clip" if labeled else "frame"),
    )
    label_steps = {
        "job2_labeling",
        "job2_embedding",
        "job3_labeling_by_other_model",
        "job4_label_merge_and_compare",
    }
    for step_id in PIPELINE_STEP_ORDER:
        if step_id == "job0_discover":
            continue
        if not labeled and step_id in label_steps:
            continue
        store.execute(
            """
            INSERT OR REPLACE INTO pipeline_step (run_id, ds, step_id, status, started_at, finished_at)
            VALUES (?, ?, ?, 'success', datetime('now'), datetime('now'))
            """,
            (run_id, DS, step_id),
        )


def _seed_facts_and_review(
    name: str,
    cfg: dict,
    ai_result: dict[str, Any] | None,
) -> None:
    if not ai_result:
        return
    clip_id = cfg["clip_id"]
    run_id = cfg["run_id"]
    merged = ai_result["merged_doc"]
    multi_ai = merged.get("multi_ai_meta")
    upsert_clip_label(
        clip_id,
        run_id,
        ds=DS,
        labels_json=merged.get("labels_json") or {},
        model_version="mock-merged-v1",
        label_source="ai_merged",
        anchor_timestamp_ns=int(cfg["anchor_ns"]),
        multi_ai_meta_json=multi_ai,
    )
    embed = ai_result.get("embed_doc") or {}
    vec = embed.get("vector") or cfg.get("vector") or []
    upsert_clip_embedding(
        clip_id,
        run_id,
        ds=DS,
        vector=list(vec),
        model_version=str(embed.get("model_version") or "mock-embed-v1"),
        aggregation_method="clip_omni",
    )
    ingest_v2_ai_from_local_artifacts(clip_id, run_id, DS)

    review_status = cfg.get("review_status")
    if not review_status:
        return
    if get_review(clip_id, run_id):
        return
    summary_stub = attach_consensus_fields({}, {"multi_ai_meta_json": multi_ai})
    ai_summary = {
        "source": "ai/labels_merged.json",
        "aggregation": "dual_model_merge",
        "gate_passed": merged.get("gate_passed"),
        "clip_agreement": merged.get("clip_agreement"),
        "disputed_label_ids": summary_stub.get("disputed_label_ids") or [],
        "dispute_count": summary_stub.get("dispute_count") or 0,
        "label_consensus": summary_stub.get("label_consensus") or {},
        "multi_ai_gate": summary_stub.get("multi_ai_gate"),
    }
    if review_status == "pending_review":
        enqueue_clip(clip_id, run_id, require_job3=True)
        _seed_demo_field_reviews(cfg, clip_id, run_id, merged)
        return
    labels = dict(merged.get("labels_json") or {})
    if not labels and cfg.get("day_period"):
        labels["L1.1.day_period"] = cfg["day_period"]
        if cfg.get("is_holiday") is not None:
            labels["L1.1.is_holiday"] = cfg["is_holiday"]
    create_review(
        clip_id,
        run_id,
        labels_json=labels,
        review_status="reviewed",
        ai_source_summary_json=ai_summary,
    )


def _seed_demo_field_reviews(
    cfg: dict,
    clip_id: str,
    run_id: str,
    merged: dict[str, Any],
) -> None:
    from hmi.review.field_review_db import upsert_field_review

    labels_json = merged.get("labels_json") or {}
    for entry in cfg.get("seed_field_reviews") or []:
        label_id = str(entry["label_id"])
        action = str(entry["action"])
        ai_value = labels_json.get(label_id)
        if action == "confirm":
            value = ai_value
        elif action == "uncertain":
            value = None
        else:
            value = entry.get("value")
        upsert_field_review(
            clip_id=clip_id,
            run_id=run_id,
            label_id=label_id,
            action=action,
            value=value,
            human_doubtful=action == "uncertain",
            ai_value=ai_value,
            taxonomy_version_id=None,
            reviewer_id="demo-seed",
        )


def mock_one(name: str, *, seed_db: bool = True) -> dict:
    if name not in MOCK_SCENARIOS:
        raise KeyError(f"unknown scenario: {name}")
    cfg = MOCK_SCENARIOS[name]
    spec = _spec_from_scenario(name, cfg)
    run_root = artifacts_dir(spec.clip_id, spec.run_id)
    image_paths = _write_images(spec.clip_id, spec.run_id)
    result = write_full_mock_run(run_root, spec, image_paths=image_paths)
    checklist = artifact_checklist(run_root, labeled=spec.labeled)
    result["scenario"] = name
    result["checklist"] = checklist
    result["note"] = cfg.get("note")
    if seed_db:
        ensure_schema()
        store.ensure_db()
        bag_key = f"oss://rosbag-labels-pipeline-bucket2/rosbags/20260721/{name}.bag"
        _seed_db(spec.clip_id, spec.run_id, name, labeled=spec.labeled, bag_key=bag_key)
        _seed_facts_and_review(name, cfg, result.get("ai"))
    return result


def export_fixtures(target: Path | None = None) -> Path:
    target = target or (PROJECT_ROOT / "data" / "mock_pipeline")
    if target.is_dir():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    for name, cfg in MOCK_SCENARIOS.items():
        spec = _spec_from_scenario(name, cfg)
        dest = target / spec.clip_id.replace(":", "__") / "runs" / spec.run_id
        _write_images(spec.clip_id, spec.run_id)
        src = artifacts_dir(spec.clip_id, spec.run_id)
        if not src.is_dir():
            mock_one(name, seed_db=False)
            src = artifacts_dir(spec.clip_id, spec.run_id)
        shutil.copytree(src, dest)
        index.append(
            {
                "scenario": name,
                "clip_id": spec.clip_id,
                "run_id": spec.run_id,
                "gate": cfg.get("gate"),
                "note": cfg.get("note"),
                "path": str(dest.relative_to(target)),
            }
        )
    (target / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def _clear_demo_db() -> None:
    from hmi.app_db import db_conn

    for cfg in MOCK_SCENARIOS.values():
        store.clear_clip_data(cfg["clip_id"], cfg["run_id"], DS)
        with db_conn() as conn:
            conn.execute(
                "DELETE FROM clip_label_review WHERE clip_id=? AND run_id=?",
                (cfg["clip_id"], cfg["run_id"]),
            )
            conn.execute(
                "DELETE FROM clip_label_field_review WHERE clip_id=? AND run_id=?",
                (cfg["clip_id"], cfg["run_id"]),
            )
            conn.commit()
        root = artifacts_dir(cfg["clip_id"], cfg["run_id"])
        if root.is_dir():
            shutil.rmtree(root, ignore_errors=True)
    store.execute("DELETE FROM dim_clip WHERE clip_id LIKE 'sha256:demo_%'")


def main() -> None:
    parser = argparse.ArgumentParser(description="Mock clip-omni v2 pipeline artifacts")
    parser.add_argument("--list", action="store_true", help="List mock scenarios")
    parser.add_argument("--clip", help="Mock one scenario by dir_name")
    parser.add_argument("--all", action="store_true", help="Mock all scenarios + seed DB")
    parser.add_argument("--reset", action="store_true", help="Clear demo data before --all")
    parser.add_argument("--export-fixtures", action="store_true", help="Copy to data/mock_pipeline/")
    parser.add_argument("--no-db", action="store_true", help="Skip SQLite / review seeding")
    args = parser.parse_args()

    if args.list:
        print("Mock scenarios (agreement threshold = %.1f):\n" % AGREEMENT_THRESHOLD)
        for name, cfg in MOCK_SCENARIOS.items():
            stype = cfg.get("scenario_type") or "-"
            print(f"  {name:28}  gate={str(cfg.get('gate')):4}  [{stype}]")
            print(f"    {cfg.get('note')}")
        return

    if args.export_fixtures:
        dest = export_fixtures()
        print(f"Exported fixtures → {dest}")
        print(f"  index: {dest / 'index.json'}")
        return

    if args.all:
        if args.reset:
            ensure_schema()
            store.ensure_db()
            _clear_demo_db()
        results = []
        for name in MOCK_SCENARIOS:
            results.append(mock_one(name, seed_db=not args.no_db))
        try:
            from hmi.db import cache_clear

            cache_clear()
        except Exception:
            pass
        print("=== Mock pipeline artifacts (all scenarios) ===\n")
        for r in results:
            ok = sum(1 for _, exists in r["checklist"] if exists)
            total = len(r["checklist"])
            gate = r.get("gate_passed")
            disputed = r.get("disputed_label_ids") or []
            agreement = r.get("clip_agreement")
            agr_text = f"{agreement:.2f}" if isinstance(agreement, (int, float)) else "n/a"
            print(
                f"  {r['scenario']:28}  files={ok}/{total}  "
                f"gate={'pass' if gate else 'fail' if gate is not None else 'n/a':4}  "
                f"agreement={agr_text}  disputed={disputed}"
            )
        print(f"\nArtifacts root: data/hmi_local/artifacts/clips/")
        print("Re-run: py -3 scripts/mock_pipeline_artifacts.py --all --reset")
        return

    if args.clip:
        r = mock_one(args.clip, seed_db=not args.no_db)
        print(json.dumps({k: v for k, v in r.items() if k != "checklist"}, ensure_ascii=False, indent=2))
        print("\nChecklist:")
        for rel, ok in r["checklist"]:
            print(f"  [{'OK' if ok else 'MISSING'}] {rel}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
