"""Reset clip-centric demo data (wraps scripts/seed_demo_clip_data.py --reset)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
HMI_ROOT = REPO_ROOT / "hmi"
SEED_SCRIPT = HMI_ROOT / "scripts" / "seed_demo_clip_data.py"


def reset_demo_clips() -> None:
    if not SEED_SCRIPT.is_file():
        raise FileNotFoundError(f"seed script not found: {SEED_SCRIPT}")
    subprocess.run(
        [sys.executable, str(SEED_SCRIPT), "--reset"],
        cwd=str(REPO_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
