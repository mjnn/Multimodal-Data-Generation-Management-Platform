"""Poll local rosbags/ queue and run OMS SDK pipeline into runtime artifacts."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hmi.data_source import LOCAL_ROOT, REPO_ROOT, is_local_mode
from hmi.db import cache_clear
from hmi.local import bag_upload, pipeline_run as pr, store
from hmi.local.bag_upload import resolve_local_bag_path

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_thread: threading.Thread | None = None
_stop = threading.Event()
_active_jobs = 0
_status: dict[str, Any] = {
    "enabled": False,
    "interval_sec": 20,
    "running_job": False,
    "last_error": None,
    "last_clip_id": None,
    "last_run_id": None,
    "last_finished_at": None,
}


def _env_bool(name: str, default: bool) -> bool:
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


def is_poll_enabled() -> bool:
    if not is_local_mode():
        return False
    return _env_bool("HMI_LOCAL_SDK_POLL_ENABLED", True)


def get_worker_status() -> dict[str, Any]:
    out = dict(_status)
    out["enabled"] = is_poll_enabled()
    out["running_job"] = _active_jobs > 0
    out["active_jobs"] = _active_jobs
    out["max_parallel"] = _max_parallel()
    return out


def _max_parallel() -> int:
    from hmi.local.pipeline_settings import resolve_sdk_parallel

    return resolve_sdk_parallel()


def _taxonomy_path() -> Path:
    from hmi.local.pipeline_settings import resolve_taxonomy_path

    return resolve_taxonomy_path()


def _clip_config_from_settings() -> "ClipConfig":
    from oms_multimodal.config import ClipConfig

    from hmi.local.pipeline_settings import get_pipeline_settings

    s = get_pipeline_settings()
    return ClipConfig(
        min_sec=float(s.get("min_sec") or 5.0),
        max_sec=float(s.get("max_sec") or 30.0),
        sample_fps=float(s.get("sample_fps") or 1.0),
        max_clips=int(s.get("max_clips") or 1),
    )


def _env_stale_infer_minutes() -> int:
    raw = os.getenv("HMI_LOCAL_SDK_STALE_INFER_MINUTES", "45").strip()
    try:
        return max(1, min(24 * 60, int(raw)))
    except ValueError:
        return 120


def _work_run_dir(clip_dir_name: str, clip_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", clip_dir_name).strip("_") or "clip"
    suffix = clip_id.replace("sha256:", "")[:12]
    return LOCAL_ROOT / "work" / "sdk_runs" / f"{safe}_{suffix}"


def _client_config_overrides() -> dict[str, Any]:
    from hmi.local.pipeline_settings import get_pipeline_settings, omni_label_prompt_overrides_for_worker

    s = get_pipeline_settings()
    out: dict[str, Any] = {}
    omni = str(s.get("omni_model") or "default")
    embed = str(s.get("embedding_model") or "default")
    if omni and omni != "default":
        out["omni_model"] = omni
    if embed and embed != "default":
        out["embedding_model"] = embed
    prompt_overrides = omni_label_prompt_overrides_for_worker()
    if prompt_overrides:
        out["omni_label_prompt"] = prompt_overrides
    return out


def _run_sdk_and_ingest(
    *,
    bag_path: Path,
    clip_id: str,
    run_id: str,
    ds: str,
    clip_dir_name: str,
    bag_oss_key: str,
) -> None:
    from oms_multimodal.client import OmsMultimodalClient
    from oms_multimodal.config import OutputConfig

    work_run = _work_run_dir(clip_dir_name, clip_id)
    if work_run.is_dir():
        import shutil

        shutil.rmtree(work_run, ignore_errors=True)
    work_run.mkdir(parents=True, exist_ok=True)

    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return

    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_infer", status="running")
    pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="running")
    cache_clear()

    output = OutputConfig(
        embeddings_out=work_run / "fusion_embeddings.jsonl",
        labels_out=work_run / "labels.jsonl",
        videos_out=work_run / "clip_videos.jsonl",
    )
    from oms_multimodal.config import ClientConfig

    client_cfg = ClientConfig.from_env(taxonomy_path=_taxonomy_path())
    # Local / ECS pipeline worker always uses DashScope API; ignore MODEL_BACKEND=mc.
    client_cfg.model_backend = "api"
    for key, val in _client_config_overrides().items():
        setattr(client_cfg, key, val)
    client = OmsMultimodalClient(config=client_cfg, work_dir=work_run / "work")
    try:
        result = client.process_bag(
            bag_path,
            clip_config=_clip_config_from_settings(),
            output=output,
        )
        if result.errors:
            raise RuntimeError(str(result.errors[0]))
        if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
            cache_clear()
            return
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_infer", status="success")
    except Exception as exc:
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_infer",
            status="failed",
            error_message=str(exc),
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
        cache_clear()
        raise

    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_mc_write", status="running")
    env = os.environ.copy()
    env["HMI_RUNTIME_ROOT"] = str(LOCAL_ROOT)
    script = REPO_ROOT / "hmi" / "scripts" / "import_real_data_clips.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--from-path",
            str(work_run),
            "--no-review",
            "--run-id",
            run_id,
            "--clip-id",
            clip_id,
            "--bag-oss-key",
            bag_oss_key,
        ],
        cwd=str(REPO_ROOT / "hmi"),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "import failed")[:2000]
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_mc_write",
            status="failed",
            error_message=msg,
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
        cache_clear()
        raise RuntimeError(msg)
    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return
    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_mc_write", status="success")

    pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_upload", status="running")
    try:
        from hmi.local.oss_publish import mirror_artifacts_run_to_oss, write_local_dispatch_manifest

        n = mirror_artifacts_run_to_oss(clip_id, run_id)
        if n <= 0:
            raise RuntimeError("no files mirrored to local OSS")
        write_local_dispatch_manifest(
            clip_id=clip_id,
            run_id=run_id,
            bag_oss_key=bag_oss_key,
            ds=ds,
        )
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_upload", status="success")
        pr.set_step(run_id=run_id, clip_id=clip_id, ds=ds, step_id="sdk_dispatch", status="success")
    except Exception as exc:
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_upload",
            status="failed",
            error_message=str(exc),
        )
        raise

    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return

    pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="completed")
    cache_clear()

    from hmi.services import oss_sync_poller

    if oss_sync_poller.is_auto_sync_enabled():
        try:
            from hmi.local.sync_from_oss import sync_runtime_from_local_oss

            sync_runtime_from_local_oss(clip_id, run_id, ds=ds)
            cache_clear()
        except Exception as exc:
            logger.warning("auto sync from local OSS failed: %s", exc)


def _process_one(row: dict[str, Any], *, bag_oss_key: str) -> None:
    clip_id = str(row["clip_id"])
    run_id = str(row["run_id"])
    ds = str(row["ds"])
    if pr.is_run_cancelled(run_id=run_id, clip_id=clip_id, ds=ds):
        cache_clear()
        return
    clip_dir_name = str(row.get("clip_dir_name") or clip_id[:16])
    bag_path = resolve_local_bag_path(bag_oss_key)
    if bag_path is None:
        pr.set_step(
            run_id=run_id,
            clip_id=clip_id,
            ds=ds,
            step_id="sdk_discover",
            status="failed",
            error_message="bag missing",
        )
        pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="failed")
        cache_clear()
        return
    _run_sdk_and_ingest(
        bag_path=bag_path,
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        clip_dir_name=clip_dir_name,
        bag_oss_key=bag_oss_key,
    )


def _process_one_wrapper(row: dict[str, Any], *, bag_oss_key: str) -> None:
    global _active_jobs
    clip_id = str(row.get("clip_id") or "")
    run_id = str(row.get("run_id") or "")
    try:
        _status["last_clip_id"] = clip_id
        _status["last_run_id"] = run_id
        _status["last_error"] = None
        _process_one(row, bag_oss_key=bag_oss_key)
        _status["last_finished_at"] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        logger.exception("local SDK job failed")
        _status["last_error"] = str(exc)
    finally:
        with _lock:
            _active_jobs = max(0, _active_jobs - 1)


def _tick() -> None:
    global _active_jobs
    if not is_poll_enabled():
        return
    store.ensure_db()
    stale = pr.reset_stale_sdk_infer_jobs(stale_minutes=_env_stale_infer_minutes())
    if stale:
        logger.warning("reset %s stale sdk_infer job(s) to pending", stale)
        cache_clear()
    max_parallel = _max_parallel()
    with _lock:
        slots = max_parallel - _active_jobs
        if slots <= 0:
            return
    pending = pr.list_runs_needing_sdk(limit=max(slots * 2, slots) if max_parallel > 1 else 1)
    if not pending:
        return
    for row in pending:
        clip_id = str(row.get("clip_id") or "")
        run_id = str(row.get("run_id") or "")
        ds = str(row.get("ds") or "")
        if not clip_id or not run_id or not ds:
            continue
        if not pr.try_claim_sdk_infer(run_id=run_id, clip_id=clip_id, ds=ds):
            continue
        bag_key = str(row.get("bag_oss_key") or "")
        if max_parallel == 1:
            _process_one_wrapper(row, bag_oss_key=bag_key)
            return
        with _lock:
            if _active_jobs >= max_parallel:
                pr.set_step(
                    run_id=run_id,
                    clip_id=clip_id,
                    ds=ds,
                    step_id="sdk_infer",
                    status="pending",
                )
                pr.upsert_run(run_id=run_id, clip_id=clip_id, ds=ds, status="pending")
                continue
            _active_jobs += 1
        threading.Thread(
            target=_process_one_wrapper,
            args=(row,),
            kwargs={"bag_oss_key": bag_key},
            daemon=True,
        ).start()


def _loop() -> None:
    interval = _env_int("HMI_LOCAL_SDK_POLL_INTERVAL_SEC", 20)
    _status["interval_sec"] = interval
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            logger.exception("local SDK poller tick")
        _stop.wait(interval)


def start_poller() -> None:
    global _thread
    _status["enabled"] = is_poll_enabled()
    if not is_poll_enabled():
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="local-sdk-poller", daemon=True)
    _thread.start()


def stop_poller() -> None:
    _stop.set()
