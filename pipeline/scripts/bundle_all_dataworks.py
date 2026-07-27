#!/usr/bin/env python3
"""Regenerate all DataWorks bundled paste files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

JOBS: tuple[tuple[str, list[str]], ...] = (
    ("bundle_pipeline_dispatch.py", ["dataworks/job0_dispatch_node.py"]),
    ("bundle_pipeline_dispatch.py", ["dataworks/job1_parse_node.py"]),
    ("bundle_pipeline_dispatch.py", ["dataworks/job1_align_node.py"]),
    ("bundle_pipeline_dispatch.py", ["dataworks/job2_labeling_node.py"]),
    ("bundle_pipeline_dispatch.py", ["dataworks/job2_embedding_node.py"]),
    ("bundle_pipeline_dispatch.py", ["dataworks/job3_labeling_by_other_model_node.py"]),
    ("bundle_pipeline_dispatch.py", ["dataworks/job4_label_merge_and_compare_node.py"]),
    ("bundle_dataworks_node.py", ["dataworks/job2_asr_node.py"]),
    ("bundle_dataworks_node.py", ["dataworks/job3_label_node.py"]),
    ("bundle_dataworks_node.py", ["dataworks/job4_embed_node.py"]),
    ("bundle_mc_write_node.py", ["dataworks/job1_mc_write_node.py"]),
    ("bundle_mc_write_node.py", ["dataworks/job2_mc_write_node.py"]),
    ("bundle_mc_write_node.py", ["dataworks/job3_mc_write_node.py"]),
    ("bundle_mc_write_node.py", ["dataworks/job4_mc_write_node.py"]),
)


def main() -> None:
    for script, args in JOBS:
        cmd = [PY, str(ROOT / "scripts" / script), *(str(ROOT / a) for a in args)]
        print(">", " ".join(cmd))
        subprocess.run(cmd, check=True, cwd=ROOT)
    print("All bundled files updated under dataworks/bundled/")


if __name__ == "__main__":
    main()
