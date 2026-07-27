#!/usr/bin/env python3
"""Sync .env credentials into odpscmd + ossutil config files.

Keeps a single source of truth (.env) for local CLI tools. Does not print secrets.

Usage:
  python scripts/sync_cloud_cli_config.py
  python scripts/sync_cloud_cli_config.py --odps-config D:/odpscmd_public/conf/odps_config.ini
  python scripts/sync_cloud_cli_config.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
from repo_paths import CONFIG_PATH, ENV_PATH, PIPELINE_ROOT

from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings

DEFAULT_ODPS_CONFIG = Path(r"D:\odpscmd_public\conf\odps_config.ini")
DEFAULT_OSSUTIL_CONFIG = Path.home() / ".ossutilconfig"

ODPS_CONFIG_TEMPLATE = """\
###################################### Required fields ############################################
project_name={project}
access_id={access_id}
access_key={access_key}
end_point={endpoint}

###################################### Optional fields ############################################
log_view_host=http://logview.odps.aliyun.com
use_instance_tunnel=true
instance_tunnel_max_record=10000
"""

OSSUTIL_CONFIG_TEMPLATE = """\
[default]
accessKeyId={access_id}
accessKeySecret={access_key}
region={oss_region}
endpoint={endpoint}
"""


def _oss_region(region: str) -> str:
    """ossutil expects cn-shanghai; .env may use cn_shanghai."""
    return region.replace("_", "-")


def _write_text(path: Path, content: str, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] would write {path} ({len(content)} bytes)")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Wrote {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync .env -> odpscmd/ossutil config files")
    parser.add_argument("--env-file", type=Path, default=ENV_PATH)
    parser.add_argument("--config", type=Path, default=CONFIG_PATH)
    parser.add_argument("--odps-config", type=Path, default=DEFAULT_ODPS_CONFIG)
    parser.add_argument("--ossutil-config", type=Path, default=DEFAULT_OSSUTIL_CONFIG)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    load_cloud_env(args.env_file)
    with args.config.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    settings = require_odps_settings(resolve_cloud_settings(config))

    odps_text = ODPS_CONFIG_TEMPLATE.format(
        project=settings["odps_project"],
        access_id=settings["odps_access_id"],
        access_key=settings["odps_access_key"],
        endpoint=settings["odps_endpoint"],
    )
    ossutil_text = OSSUTIL_CONFIG_TEMPLATE.format(
        access_id=settings["odps_access_id"],
        access_key=settings["odps_access_key"],
        oss_region=_oss_region(settings["region"]),
        endpoint=settings["oss_endpoint"],
    )

    _write_text(args.odps_config, odps_text, dry_run=args.dry_run)
    _write_text(args.ossutil_config, ossutil_text, dry_run=args.dry_run)

    print("Done. Config files contain plaintext AK/SK — never commit them.")


if __name__ == "__main__":
    main()
