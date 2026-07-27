"""Local app metadata (latest published taxonomy, etc.)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hmi.config import PROJECT_ROOT

APP_META_PATH = PROJECT_ROOT / "data" / "app_meta.json"


def read_app_meta() -> dict[str, Any]:
    if not APP_META_PATH.is_file():
        return {}
    try:
        with APP_META_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def write_app_meta(updates: dict[str, Any]) -> dict[str, Any]:
    APP_META_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged = {**read_app_meta(), **updates}
    with APP_META_PATH.open("w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return merged
