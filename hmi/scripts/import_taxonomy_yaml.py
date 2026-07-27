#!/usr/bin/env python3
"""Import config/oms_label_taxonomy.yaml into app.db taxonomy tables."""

from __future__ import annotations

import argparse
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
BACKEND_ROOT = BACKEND
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(PROJECT_ROOT))

from hmi.config import TAXONOMY_PATH
from hmi.taxonomy_import import import_taxonomy_from_yaml


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Import OMS label taxonomy YAML into SQLite app.db"
    )
    parser.add_argument(
        "--yaml",
        type=Path,
        default=TAXONOMY_PATH,
        help=f"Taxonomy YAML path (default: {TAXONOMY_PATH.name})",
    )
    parser.add_argument(
        "--version-code",
        help="Override version_code (default: YAML version field or v1)",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Publish after import (draft → published)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing draft version nodes",
    )
    args = parser.parse_args()

    try:
        result = import_taxonomy_from_yaml(
            args.yaml.resolve(),
            version_code=args.version_code,
            publish=args.publish,
            force=args.force,
        )
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"{result.action}: {result.version_code} "
        f"(id={result.version_id}, nodes={result.node_count})"
    )
    print(f"  yaml={result.yaml_path}")
    print(f"  {result.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
