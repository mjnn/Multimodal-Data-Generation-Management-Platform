"""Poll OSS for uploaded bags that never got a DataWorks API trigger (fallback).

HMI upload → RunManualDagNodes is the primary path. This poller catches orphans:
- ``POST /api/upload/rosbag`` (upload-only)
- enqueue that uploaded then failed before/during OpenAPI
- bags dropped under configured prefixes outside HMI

Bags modified within ``HMI_CLOUD_BAG_POLL_MIN_AGE_SEC`` are ignored so the
primary API path can finish without double-trigger.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import oss2

from hmi.config import get_settings
from hmi.data_source import get_data_source, is_cloud_mode
from hmi.oss_signer import _bucket
from hmi.services import dataworks_trigger
from hmi.services.cloud_pipeline_execution import known_bag_oss_keys, record_triggered_bags

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_poller_thread: threading.Thread | None = None
_stop_event = threading.Event()
_trigger_running = False
_runtime_status: dict[str, Any] = {
    "enabled": False,
    "running_trigger": False,
    "interval_sec": 60,
    "last_scan_at": None,
    "last_orphan_count": 0,
    "last_triggered_keys": [],
    "last_dag_id": None,
    "last_error": None,
    "prefixes": [],
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def is_poll_enabled() -> bool:
    """Default on in cloud mode when not force-disabled."""
    if _env_bool("HMI_CLOUD_BAG_POLL_FORCE_OFF", False):
        return False
    if not _env_bool("HMI_CLOUD_BAG_POLL_ENABLED", True):
        return False
    return is_cloud_mode()


def scan_prefixes() -> list[str]:
    """OSS prefixes to list for .bag objects."""
    raw = os.getenv("HMI_CLOUD_BAG_POLL_PREFIXES", "").strip()
    if raw:
        return [p.strip().strip("/") + "/" for p in raw.replace(";", ",").split(",") if p.strip()]
    settings = get_settings()
    data_prefix = str(settings.get("oss_data_prefix") or "rosbags").strip().strip("/") + "/"
    prefixes = [data_prefix]
    if data_prefix != "rosbags/":
        prefixes.append("rosbags/")
    # de-dupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in prefixes:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _object_age_sec(obj: Any) -> float | None:
    lm = getattr(obj, "last_modified", None)
    if lm is None:
        return None
    if isinstance(lm, datetime):
        ts = lm if lm.tzinfo else lm.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds())
    return None


def list_bag_objects(prefix: str, *, max_keys: int = 1000) -> list[dict[str, Any]]:
    """List .bag object keys under prefix with age_sec.

    OSS ListObjects ``max-keys`` must be 1..1000 (per-page); ObjectIterator pages.
    """
    bucket = _bucket()
    prefix = prefix.lstrip("/")
    page_size = max(1, min(1000, int(max_keys)))
    items: list[dict[str, Any]] = []
    for obj in oss2.ObjectIterator(bucket, prefix=prefix, max_keys=page_size):
        if getattr(obj, "is_prefix", lambda: False)():
            continue
        key = str(getattr(obj, "key", "") or "").lstrip("/")
        if not key.lower().endswith(".bag"):
            continue
        age = _object_age_sec(obj)
        items.append({"key": key, "age_sec": age, "size": int(getattr(obj, "size", 0) or 0)})
        if len(items) >= 5000:
            break
    return items


def _bag_already_in_mc(bag_key: str) -> bool:
    try:
        from hmi.clip_context import find_clip_id_by_bag_key

        return bool(find_clip_id_by_bag_key(bag_key))
    except Exception as exc:
        logger.debug("dim_clip lookup failed for %s: %s", bag_key[:48], exc)
        return False


def find_orphan_bag_keys(
    *,
    prefixes: list[str] | None = None,
    known: set[str] | None = None,
    min_age_sec: int | None = None,
    max_age_sec: int | None = None,
    check_mc: bool = True,
) -> list[str]:
    """Return bag keys on OSS that look untriggered."""
    prefixes = prefixes or scan_prefixes()
    known = known if known is not None else known_bag_oss_keys()
    min_age = min_age_sec if min_age_sec is not None else max(0, _env_int("HMI_CLOUD_BAG_POLL_MIN_AGE_SEC", 180))
    max_age = max_age_sec if max_age_sec is not None else max(0, _env_int("HMI_CLOUD_BAG_POLL_MAX_AGE_SEC", 7 * 24 * 3600))

    orphans: list[str] = []
    seen: set[str] = set()
    for prefix in prefixes:
        try:
            objs = list_bag_objects(prefix)
        except Exception:
            logger.exception("cloud_bag_poller: list failed prefix=%s", prefix)
            continue
        for obj in objs:
            key = obj["key"]
            if key in seen or key in known:
                continue
            age = obj.get("age_sec")
            if age is not None:
                if age < min_age:
                    continue
                if max_age > 0 and age > max_age:
                    continue
            if check_mc and _bag_already_in_mc(key):
                continue
            seen.add(key)
            orphans.append(key)
    orphans.sort()
    return orphans


def _poll_once() -> None:
    global _trigger_running
    if not is_poll_enabled():
        _runtime_status["enabled"] = False
        return
    if get_data_source() != "cloud":
        _runtime_status["enabled"] = False
        return

    try:
        dataworks_trigger.require_dataworks_config()
    except dataworks_trigger.DataWorksConfigError as exc:
        _runtime_status["enabled"] = False
        _runtime_status["last_error"] = str(exc)
        return

    prefixes = scan_prefixes()
    _runtime_status["prefixes"] = prefixes
    _runtime_status["enabled"] = True
    _runtime_status["last_scan_at"] = datetime.now(timezone.utc).isoformat()
    _runtime_status["last_error"] = None

    orphans = find_orphan_bag_keys(prefixes=prefixes)
    _runtime_status["last_orphan_count"] = len(orphans)
    if not orphans:
        _runtime_status["last_triggered_keys"] = []
        return

    max_bags = max(1, min(32, _env_int("HMI_CLOUD_BAG_POLL_MAX_BAGS", 4)))
    batch = orphans[:max_bags]

    with _lock:
        if _trigger_running:
            return
        _trigger_running = True
        _runtime_status["running_trigger"] = True

    try:
        logger.info(
            "cloud_bag_poller: triggering %s orphan bag(s) (of %s found)",
            len(batch),
            len(orphans),
        )
        ds = datetime.now(timezone.utc).strftime("%Y%m%d")
        trigger = dataworks_trigger.trigger_sdk_pipeline(batch, ds=ds)
        record_triggered_bags(
            batch,
            dag_id=trigger["dag_id"],
            source="poller",
        )
        _runtime_status["last_triggered_keys"] = batch
        _runtime_status["last_dag_id"] = trigger["dag_id"]
        logger.info("cloud_bag_poller: DagId=%s keys=%s", trigger["dag_id"], batch)
    except Exception as exc:
        _runtime_status["last_error"] = str(exc)
        logger.exception("cloud_bag_poller: trigger failed")
    finally:
        with _lock:
            _trigger_running = False
            _runtime_status["running_trigger"] = False


def _poll_loop() -> None:
    interval = max(30, _env_int("HMI_CLOUD_BAG_POLL_INTERVAL_SEC", 60))
    _runtime_status["interval_sec"] = interval
    logger.info("cloud_bag_poller: started interval=%ss prefixes=%s", interval, scan_prefixes())
    # First tick after a short delay so API uploads aren't raced at startup
    if _stop_event.wait(min(30, interval)):
        return
    while True:
        try:
            _poll_once()
        except Exception:
            logger.exception("cloud_bag_poller: poll tick failed")
        if _stop_event.wait(interval):
            break


def run_scan_now() -> dict[str, Any]:
    """Synchronous orphan scan + optional trigger (for ops API)."""
    _poll_once()
    return get_poller_status()


def get_poller_status() -> dict[str, Any]:
    return {
        **_runtime_status,
        "enabled": bool(_runtime_status.get("enabled")) and is_poll_enabled(),
        "poll_enabled_config": is_poll_enabled(),
        "cloud_mode": is_cloud_mode(),
    }


def start_poller() -> None:
    global _poller_thread
    _runtime_status["poll_enabled_config"] = is_poll_enabled()
    if not is_poll_enabled():
        _runtime_status["enabled"] = False
        return
    if _poller_thread and _poller_thread.is_alive():
        return
    _stop_event.clear()
    _poller_thread = threading.Thread(
        target=_poll_loop,
        name="hmi-cloud-bag-trigger-poller",
        daemon=True,
    )
    _poller_thread.start()


def stop_poller() -> None:
    _stop_event.set()
