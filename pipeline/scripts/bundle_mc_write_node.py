#!/usr/bin/env python3
"""Bundle mc_write_idempotent + pipeline_dispatch + mc_write node."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PIPELINE_ROOT.parent
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, REPO_ROOT / "hmi" / "backend"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT
BUNDLE = PIPELINE_ROOT / "scripts" / "bundle_dataworks_node.py"


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: bundle_mc_write_node.py dataworks/jobN_mc_write_node.py")
    node = sys.argv[1]
    cmd = [
        sys.executable,
        str(BUNDLE),
        node,
        "--helpers",
        "mc_write_idempotent,pipeline_dispatch",
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
