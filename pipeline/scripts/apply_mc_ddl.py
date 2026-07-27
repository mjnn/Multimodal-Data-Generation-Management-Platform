#!/usr/bin/env python3
"""Apply MaxCompute DDL from sql/maxcompute/aig_rosbag__ddl.sql."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml
from odps import ODPS

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings


def load_config(config_path: Path) -> dict:
    with config_path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)
    if not isinstance(config, dict):
        raise ValueError(f"Invalid config file: {config_path}")
    return config


def split_sql_statements(sql_text: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            statement = "\n".join(buffer).strip()
            if statement.endswith(";"):
                statement = statement[:-1].strip()
            if statement:
                statements.append(statement)
            buffer = []
    if buffer:
        trailing = "\n".join(buffer).strip()
        if trailing:
            statements.append(trailing.rstrip(";").strip())
    return statements


def extract_table_name(statement: str) -> str | None:
    match = re.search(
        r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([`\"A-Za-z0-9_]+)",
        statement,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply MaxCompute DDL for aig_rosbag__ tables.")
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument(
        "--ddl",
        type=Path,
        default=PIPELINE_ROOT / "sql" / "maxcompute" / "aig_rosbag__ddl.sql",
    )
    parser.add_argument("--env-file", type=Path, help="Optional .env path")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print statements without executing against MaxCompute.",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only verify ODPS connection and resolved settings.",
    )
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    config = load_config(args.config.resolve())
    settings = resolve_cloud_settings(config)

    print(f"ODPS project: {settings['odps_project'] or '(empty)'}")
    print(f"ODPS endpoint: {settings['odps_endpoint']}")
    print(f"OSS bucket (config): {settings['oss_bucket'] or '(empty)'}")
    print(f"Region: {settings['region']}")

    ddl_path = args.ddl.resolve()
    statements = split_sql_statements(ddl_path.read_text(encoding="utf-8"))
    if not statements:
        raise SystemExit(f"No SQL statements found in: {ddl_path}")

    if args.dry_run:
        for index, statement in enumerate(statements, start=1):
            table_name = extract_table_name(statement) or f"statement_{index}"
            print(f"-- [{index}] {table_name}")
            print(statement)
            print()
        print(f"Dry run: {len(statements)} DDL statement(s) from {ddl_path}")
        return

    settings = require_odps_settings(settings)
    odps = ODPS(
        settings["odps_access_id"],
        settings["odps_access_key"],
        project=settings["odps_project"],
        endpoint=settings["odps_endpoint"],
    )

    if args.check_only:
        tables = list(odps.list_tables())
        print(f"Connection OK. Project has {len(tables)} table(s).")
        return

    for index, statement in enumerate(statements, start=1):
        table_name = extract_table_name(statement) or f"statement_{index}"
        print(f"[{index}/{len(statements)}] Creating {table_name} ...")
        instance = odps.execute_sql(statement)
        instance.wait_for_success()

    print(f"Applied {len(statements)} DDL statement(s) from {ddl_path}")


if __name__ == "__main__":
    main()
