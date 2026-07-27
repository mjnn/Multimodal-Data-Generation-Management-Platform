#!/usr/bin/env python3
"""Create the first admin user if none exists (PRD R6)."""

from __future__ import annotations

import argparse
import getpass
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

from hmi.app_db import create_user, ensure_schema, get_user_by_username, list_users


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap first HMI admin user")
    parser.add_argument("--username", default="admin", help="Admin username (default: admin)")
    parser.add_argument("--display-name", default="Administrator", help="Display name")
    parser.add_argument("--password", help="Password (min 8 chars); prompt if omitted")
    parser.add_argument("--force-new", action="store_true", help="Create even if other users exist")
    args = parser.parse_args()

    ensure_schema()
    existing = get_user_by_username(args.username.strip())
    if existing:
        print(f"User already exists: {args.username} (id={existing['id']})")
        return 0

    users = list_users()
    if users and not args.force_new:
        print(f"Users already exist ({len(users)}). Use --force-new to add another admin.")
        return 1

    password = args.password
    if not password:
        password = getpass.getpass("Password (min 8 chars): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.", file=sys.stderr)
            return 1

    try:
        user = create_user(
            args.username.strip(),
            password,
            display_name=args.display_name,
            roles=["admin"],
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Created admin user: {user['username']} (id={user['id']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
