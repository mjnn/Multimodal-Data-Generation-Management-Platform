#!/usr/bin/env python3
"""Reset an HMI user's password (for ops / bootstrap)."""

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

from hmi.app_db import authenticate_user, create_user, ensure_schema, get_user_by_username, update_user


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset HMI user password")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", required=True)
    args = parser.parse_args()

    ensure_schema()
    user = get_user_by_username(args.username.strip())
    if user is None:
        create_user(
            args.username.strip(),
            args.password,
            display_name="Administrator",
            roles=["admin"],
        )
        print(f"Created user {args.username}")
    else:
        update_user(user["id"], password=args.password)
        print(f"Reset password for {args.username}")
    ok = authenticate_user(args.username.strip(), args.password) is not None
    print(f"auth_ok={ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
