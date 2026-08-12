"""HMI test-mode flag (system env HMI_TEST_MODE).

When off (default): UI hides local/cloud switch and forces cloud data source.
When on: local/cloud switch + 「重置测试数据」 are available.
"""

from __future__ import annotations

import os


def env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def is_test_mode() -> bool:
    return env_flag("HMI_TEST_MODE", default=False)


def enforce_data_source_for_test_mode() -> str:
    """When test mode is off, persist and return cloud as the active source."""
    from hmi.data_source import get_data_source, set_data_source

    if is_test_mode():
        return get_data_source()
    if get_data_source() != "cloud":
        return set_data_source("cloud")
    return "cloud"
