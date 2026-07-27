"""Poll OSS dispatch manifest and sync MC+OSS into local HMI store (ECS / long-running HMI)."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hmi.data_source import HMI_ROOT, REPO_ROOT, set_data_source

_shared = REPO_ROOT / "shared"
if str(_shared) not in sys.path:
    sys.path.insert(0, str(_shared))
from repo_paths import ENV_PATH
from cloud_config import load_cloud_env
from hmi.db import cache_clear
from hmi.local import store
from hmi.services.pipeline_status import DISPATCH_MANIFEST_KEY, _read_dispatch_manifest

logger = logging.getLogger(__name__)

_META_FINGERPRINT = "poll_last_fingerprint"
_META_STATUS = "poll_last_sync_status"
_META_AT = "poll_last_sync_at"
_META_ERROR = "poll_last_error"
_META_CLIP = "poll_last_clip_id"
_META_RUN = "poll_last_run_id"
_META_AUTO_SYNC = "oss_auto_sync_enabled"

_lock = threading.Lock()
_poller_thread: threading.Thread | None = None
_stop_event = threading.Event()
_sync_running = False
_runtime_status: dict[str, Any] = {
    "enabled": False,
    "running_sync": False,
    "interval_sec": 30,
    "manifest_key": DISPATCH_MANIFEST_KEY,
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
        return max(5, int(raw))
    except ValueError:
        return default


def is_auto_sync_enabled() -> bool:
    """Runtime toggle persisted in local meta; default off."""
    store.ensure_db()
    raw = store.get_meta(_META_AUTO_SYNC)
    if raw is None:
        return False
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_poll_enabled() -> bool:
    """Effective auto-sync: runtime toggle only (default off). Env may force-disable."""
    if _env_bool("HMI_OSS_SYNC_POLL_FORCE_OFF", False):
        return False
    return is_auto_sync_enabled()


def set_auto_sync_enabled(enabled: bool) -> None:
    store.ensure_db()
    store.set_meta(_META_AUTO_SYNC, "1" if enabled else "0")
    _runtime_status["auto_sync_enabled"] = enabled
    if enabled:
        start_poller()
    else:
        stop_poller()


def _manifest_fingerprint(manifest: dict[str, Any]) -> str | None:
    action = str(manifest.get("action") or "").strip()
    if action != "run":
        return None
    clip_id = str(manifest.get("clip_id") or "").strip()
    run_id = str(manifest.get("run_id") or "").strip()
    dispatched_at = str(manifest.get("dispatched_at") or "").strip()
    if not clip_id or not run_id:
        return None
    return f"{clip_id}|{run_id}|{dispatched_at}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persist_status(
    *,
    status: str,
    fingerprint: str | None = None,
    clip_id: str | None = None,
    run_id: str | None = None,
    error: str | None = None,
) -> None:
    store.ensure_db()
    store.set_meta(_META_STATUS, status)
    store.set_meta(_META_AT, _utc_now())
    if fingerprint is not None:
        store.set_meta(_META_FINGERPRINT, fingerprint)
    if clip_id is not None:
        store.set_meta(_META_CLIP, clip_id)
    if run_id is not None:
        store.set_meta(_META_RUN, run_id)
    if error is not None:
        store.set_meta(_META_ERROR, error[:2000])
    elif status == "success":
        store.set_meta(_META_ERROR, "")


def get_poller_status() -> dict[str, Any]:
    store.ensure_db()
    out = dict(_runtime_status)
    out.update(
        {
            "enabled": is_poll_enabled(),
            "auto_sync_enabled": is_auto_sync_enabled(),
            "last_fingerprint": store.get_meta(_META_FINGERPRINT),
            "last_sync_status": store.get_meta(_META_STATUS),
            "last_sync_at": store.get_meta(_META_AT),
            "last_sync_error": store.get_meta(_META_ERROR),
            "last_sync_clip_id": store.get_meta(_META_CLIP),
            "last_sync_run_id": store.get_meta(_META_RUN),
            "manifest": _read_dispatch_manifest(),
        }
    )
    return out


def _run_sync_subprocess(clip_id: str, run_id: str) -> tuple[bool, str]:
    script = HMI_ROOT / "scripts" / "sync_hmi_local.py"
    if not script.is_file():
        return False, f"sync script missing: {script}"
    cmd = [
        sys.executable,
        str(script),
        "--clip-id",
        clip_id,
        "--run-id",
        run_id,
    ]
    logger.info("oss_sync_poller: starting sync clip_id=%s run_id=%s", clip_id, run_id[:8])
    proc = subprocess.run(
        cmd,
        cwd=str(HMI_ROOT),
        capture_output=True,
        text=True,
        timeout=_env_int("HMI_OSS_SYNC_TIMEOUT_SEC", 7200),
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        return False, tail or f"exit code {proc.returncode}"
    return True, (proc.stdout or "")[-500:]


def _after_sync_success() -> None:
    cache_clear()
    if _env_bool("HMI_OSS_SYNC_AUTO_LOCAL", True):
        try:
            set_data_source("local")
        except Exception as exc:
            logger.warning("oss_sync_poller: auto local mode failed: %s", exc)


def _sync_worker(fingerprint: str, clip_id: str, run_id: str) -> None:
    global _sync_running
    try:
        _persist_status(status="running", fingerprint=fingerprint, clip_id=clip_id, run_id=run_id)
        ok, detail = _run_sync_subprocess(clip_id, run_id)
        if ok:
            _after_sync_success()
            _persist_status(status="success", fingerprint=fingerprint, clip_id=clip_id, run_id=run_id)
            logger.info("oss_sync_poller: sync done clip_id=%s", clip_id[:24])
        else:
            _persist_status(
                status="failed",
                fingerprint=fingerprint,
                clip_id=clip_id,
                run_id=run_id,
                error=detail,
            )
            logger.error("oss_sync_poller: sync failed: %s", detail[:300])
    except Exception as exc:
        _persist_status(
            status="failed",
            fingerprint=fingerprint,
            clip_id=clip_id,
            run_id=run_id,
            error=str(exc),
        )
        logger.exception("oss_sync_poller: sync worker error")
    finally:
        with _lock:
            _sync_running = False
            _runtime_status["running_sync"] = False


def _local_run_ready(clip_id: str, run_id: str) -> bool:
    """True when local DB already has a completed run (post-sync)."""
    row = store.query_one(
        "SELECT status FROM pipeline_run WHERE clip_id=? AND run_id=? LIMIT 1",
        (clip_id, run_id),
    )
    return bool(row and str(row.get("status") or "").lower() == "completed")


def _maybe_trigger_sync(manifest: dict[str, Any]) -> None:
    global _sync_running
    fingerprint = _manifest_fingerprint(manifest)
    if not fingerprint:
        return
    clip_id = str(manifest["clip_id"]).strip()
    run_id = str(manifest["run_id"]).strip()

    store.ensure_db()
    last = store.get_meta(_META_FINGERPRINT) or ""
    last_status = store.get_meta(_META_STATUS) or ""
    last_run = store.get_meta(_META_RUN) or ""
    # Skip only when this exact dispatch was synced and local already has the completed run.
    if (
        fingerprint == last
        and last_status == "success"
        and last_run == run_id
        and _local_run_ready(clip_id, run_id)
    ):
        return

    with _lock:
        if _sync_running:
            return
        _sync_running = True
        _runtime_status["running_sync"] = True

    threading.Thread(
        target=_sync_worker,
        args=(fingerprint, clip_id, run_id),
        name="hmi-oss-sync",
        daemon=True,
    ).start()


def _poll_once() -> None:
    manifest = _read_dispatch_manifest()
    if not manifest:
        return
    _maybe_trigger_sync(manifest)


def _poll_loop() -> None:
    interval = _env_int("HMI_OSS_SYNC_POLL_INTERVAL_SEC", 30)
    _runtime_status["interval_sec"] = interval
    logger.info(
        "oss_sync_poller: started interval=%ss manifest=%s",
        interval,
        DISPATCH_MANIFEST_KEY,
    )
    while not _stop_event.wait(interval):
        try:
            _poll_once()
        except Exception:
            logger.exception("oss_sync_poller: poll tick failed")


def start_poller() -> None:
    global _poller_thread
    load_cloud_env(ENV_PATH)
    if not is_poll_enabled():
        _runtime_status["enabled"] = False
        _runtime_status["auto_sync_enabled"] = is_auto_sync_enabled()
        return
    _runtime_status["enabled"] = True
    _runtime_status["auto_sync_enabled"] = True
    if _poller_thread and _poller_thread.is_alive():
        return
    _stop_event.clear()
    _poller_thread = threading.Thread(target=_poll_loop, name="hmi-oss-sync-poller", daemon=True)
    _poller_thread.start()
    threading.Thread(target=_poll_once, name="hmi-oss-sync-initial", daemon=True).start()


def stop_poller() -> None:
    _stop_event.set()
