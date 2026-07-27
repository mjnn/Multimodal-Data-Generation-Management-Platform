#!/usr/bin/env python3
"""Seed clip-centric demo data for HMI local mode (wraps mock pipeline artifacts).

Usage (from repo root):
  py -3 scripts/seed_demo_clip_data.py
  py -3 scripts/seed_demo_clip_data.py --reset
  py -3 scripts/seed_demo_clip_data.py --export-fixtures
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
HMI_ROOT = REPO_ROOT / "hmi"
BACKEND = HMI_ROOT / "backend"
for _p in (REPO_ROOT / "shared", BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH
PROJECT_ROOT = HMI_ROOT
PY = sys.executable
MOCK_SCRIPT = REPO_ROOT / "archive" / "legacy-scripts" / "mock_pipeline_artifacts.py"
REAL_SCRIPT = HMI_ROOT / "scripts" / "import_real_data_clips.py"
REAL_DATA_ROOT = HMI_ROOT / "data" / "real_data"


def _has_real_data() -> bool:
    if not REAL_DATA_ROOT.is_dir():
        return False
    batch = REAL_DATA_ROOT / "pipeline_latest"
    if batch.is_dir():
        for child in batch.iterdir():
            if (
                child.is_dir()
                and (child / "labels.jsonl").is_file()
                and (child / "fusion_embeddings.jsonl").is_file()
            ):
                return True
    return any(
        p.is_dir()
        and p.name != "pipeline_latest"
        and (p / "labels.jsonl").is_file()
        and (p / "fusion_embeddings.jsonl").is_file()
        for p in REAL_DATA_ROOT.iterdir()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed clip-centric demo data")
    parser.add_argument("--reset", action="store_true", help="Remove existing demo clips first")
    parser.add_argument("--export-fixtures", action="store_true", help="Export to data/mock_pipeline/")
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force mock pipeline scenarios (default: import data/real_data when present)",
    )
    args = parser.parse_args()

    if args.export_fixtures:
        cmd = [PY, str(MOCK_SCRIPT), "--export-fixtures"]
        subprocess.run(cmd, check=True, cwd=str(HMI_ROOT))
        return

    use_real = _has_real_data() and not args.mock
    if use_real:
        cmd = [PY, str(REAL_SCRIPT), "--source", "pipeline_latest"]
        if args.reset:
            cmd.append("--reset")
        subprocess.run(cmd, check=True, cwd=str(HMI_ROOT))
        print("\n演示建议：")
        print("  1. 数据总览 — 真实本地跑批 clip（data/real_data）")
        print("  2. 校核队列 — 每条 clip 为 pending_review，可逐字段确认真实模型标签")
        print("  3. 重新导入: py -3 scripts/import_real_data_clips.py --reset")
        print("  4. 回退 mock: py -3 scripts/seed_demo_clip_data.py --reset --mock")
        return

    cmd = [PY, str(MOCK_SCRIPT)]
    if args.reset:
        cmd.append("--reset")
    cmd.append("--all")
    subprocess.run(cmd, check=True, cwd=str(HMI_ROOT))

    print("\n演示建议：")
    print("  1. 数据总览 — 9 条 demo，覆盖 AI 打标全场景（见 --list）")
    print("  2. AI 分歧校核 — gate 未过留空 / 单字段分歧 / 双字段分歧 / 临界未过阈值")
    print("  3. 全面校核 — gate 通过轻分歧(majority) / 无分歧待确认 / 已校核样例")
    print("  4. 产物验证 — py -3 scripts/mock_pipeline_artifacts.py --list")
    print("\n重新生成: py -3 scripts/seed_demo_clip_data.py --reset")


if __name__ == "__main__":
    main()
