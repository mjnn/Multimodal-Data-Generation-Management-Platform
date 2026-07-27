"""Deterministic OMS L1.1 time labels from rosbag record_time_ns (Job3 post-process)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_LABEL_TIMEZONE = "Asia/Shanghai"

L1_TIME_LABEL_IDS: tuple[str, ...] = (
    "L1.1.timestamp",
    "L1.1.day_period",
    "L1.1.commute_flag",
    "L1.1.is_holiday",
)


def _local_dt(timestamp_ns: int, timezone: str) -> datetime:
    return datetime.fromtimestamp(int(timestamp_ns) / 1e9, tz=ZoneInfo(timezone))


def day_period_from_hour(hour: int) -> str:
    if 5 <= hour < 7:
        return "dawn"
    if 7 <= hour < 11:
        return "morning"
    if 11 <= hour < 13:
        return "noon"
    if 13 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 19:
        return "dusk"
    if 19 <= hour < 22:
        return "evening"
    return "night"


def commute_flag_from_local_dt(local_dt: datetime) -> str:
    if local_dt.weekday() >= 5:
        return "non_commute"
    hour_fraction = local_dt.hour + local_dt.minute / 60.0 + local_dt.second / 3600.0
    if 7 <= hour_fraction < 9:
        return "morning_commute"
    if 17 <= hour_fraction < 19:
        return "evening_commute"
    return "non_commute"


def is_weekend_holiday(local_dt: datetime) -> str:
    """Weekend-only; statutory holidays need a separate calendar source."""
    return "true" if local_dt.weekday() >= 5 else "false"


def derive_l1_time_labels(
    timestamp_ns: int,
    *,
    timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> dict[str, Any]:
    local_dt = _local_dt(timestamp_ns, timezone)
    return {
        "L1.1.timestamp": {
            "timestamp_ms": int(timestamp_ns) // 1_000_000,
            "timezone": timezone,
        },
        "L1.1.day_period": day_period_from_hour(local_dt.hour),
        "L1.1.commute_flag": commute_flag_from_local_dt(local_dt),
        "L1.1.is_holiday": is_weekend_holiday(local_dt),
    }


def apply_l1_time_label_overrides(
    values: dict[str, Any],
    timestamp_ns: int,
    *,
    timezone: str = DEFAULT_LABEL_TIMEZONE,
) -> dict[str, Any]:
    """Override VL/stub values with record_time_ns-derived L1.1 labels."""
    merged = dict(values) if isinstance(values, dict) else {}
    merged.update(derive_l1_time_labels(timestamp_ns, timezone=timezone))
    return merged
