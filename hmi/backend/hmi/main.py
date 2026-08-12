"""Rosbag HMI FastAPI application."""

from __future__ import annotations

import logging
import os
import mimetypes
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hmi.admin import admin_router
from hmi.app_db import ensure_schema
from hmi.auth import AuthMiddleware, auth_router
from hmi.auth.deps import (
    get_current_user,
    require_admin,
    require_clip_explorer_access,
    require_non_anonymous,
    require_oss_access,
    require_oss_write,
    require_overview_access,
    require_pipeline_access,
    require_pipeline_write,
)
from hmi.config import get_settings
from hmi.oss_shortcuts import OssShortcutsPutRequest, get_shortcuts_for_user, save_shortcuts_for_user
from hmi.taxonomy import taxonomy_router
from hmi.review import review_assignment_router, review_router, review_v2_router
from hmi.dataset import dataset_router
from hmi.data_source import (
    get_data_source,
    is_local_mode,
    local_db_exists,
    set_data_source,
    LOCAL_ROOT,
)
from hmi.db import cache_clear
from hmi.hmi_baseline_reset import get_reset_progress, reset_hmi_artifacts_to_baseline
from hmi.local.pipeline_router import router as pipeline_local_router
from hmi.local.store import get_meta
from hmi.router import clips_svc, search_svc
from hmi.services import oss_manage, oss_sync_poller, pipeline_status, upload


def _warmup() -> None:
    try:
        clips_svc().list_clips_light()
    except Exception:
        pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    get_settings()  # loads .env before poller reads HMI_OSS_SYNC_POLL_ENABLED
    ensure_schema()
    from hmi.data_source import ensure_runtime_layout
    from hmi.local.store import ensure_db
    from hmi.services import local_sdk_worker
    from hmi.test_mode import enforce_data_source_for_test_mode, is_test_mode

    ensure_runtime_layout()
    mode = enforce_data_source_for_test_mode()
    if mode == "local":
        ensure_db()
        if os.getenv("HMI_MIRROR_ARTIFACTS_TO_OSS", "1").strip().lower() in {"1", "true", "yes", "on"}:
            try:
                from hmi.local.oss_publish import mirror_all_artifact_runs_to_oss

                stats = mirror_all_artifact_runs_to_oss()
                if stats.get("files"):
                    logging.getLogger(__name__).info(
                        "mirrored artifact runs to local OSS: %s", stats
                    )
            except Exception:
                logging.getLogger(__name__).exception("artifact→OSS mirror on startup failed")
    elif not is_test_mode():
        logging.getLogger(__name__).info("HMI_TEST_MODE off → data_source forced to cloud")
    threading.Thread(target=_warmup, daemon=True).start()
    oss_sync_poller.start_poller()
    local_sdk_worker.start_poller()
    from hmi.services import cloud_bag_trigger_poller

    cloud_bag_trigger_poller.start_poller()
    try:
        yield
    finally:
        local_sdk_worker.stop_poller()
        oss_sync_poller.stop_poller()
        cloud_bag_trigger_poller.stop_poller()


app = FastAPI(title="多模数据管理平台 API", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(taxonomy_router)
app.include_router(review_router)
app.include_router(review_v2_router)
app.include_router(review_assignment_router)
app.include_router(dataset_router)
app.include_router(pipeline_local_router)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class DataSourceBody(BaseModel):
    data_source: str


@app.get("/api/health")
def health() -> dict[str, Any]:
    from hmi.test_mode import enforce_data_source_for_test_mode, is_test_mode

    mode = enforce_data_source_for_test_mode()
    out: dict[str, Any] = {
        "ok": True,
        "data_source": mode,
        "test_mode": is_test_mode(),
        "local_db": local_db_exists(),
    }
    if is_local_mode():
        out["project"] = "local"
        out["local_runtime_root"] = str(LOCAL_ROOT)
        out["last_sync_clip"] = get_meta("last_clip_id")
        out["last_sync_run"] = get_meta("last_run_id")
        if not local_db_exists():
            out["ok"] = False
            out["error"] = "local db missing; run hmi/scripts/init_local_runtime.py"
    else:
        try:
            settings = get_settings()
            out["project"] = settings["odps_project"]
        except Exception as exc:
            out["ok"] = False
            out["error"] = str(exc)
    poll = oss_sync_poller.get_poller_status()
    out["oss_sync_poller"] = {
        "enabled": poll.get("enabled"),
        "auto_sync_enabled": poll.get("auto_sync_enabled"),
        "running_sync": poll.get("running_sync"),
        "last_sync_status": poll.get("last_sync_status"),
        "last_sync_at": poll.get("last_sync_at"),
        "last_sync_clip_id": poll.get("last_sync_clip_id"),
    }
    from hmi.services import cloud_bag_trigger_poller, local_sdk_worker

    # Self-heal: switching to local via UI/env must not leave poller "enabled" but thread-dead.
    out["local_sdk_poller"] = local_sdk_worker.ensure_poller_running()
    out["cloud_bag_poller"] = cloud_bag_trigger_poller.get_poller_status()
    return out


class SyncPollerBody(BaseModel):
    enabled: bool


@app.get("/api/sync/poller")
def api_sync_poller_status(_user: dict = Depends(require_pipeline_access)) -> dict[str, Any]:
    """OSS dispatch poll → local sync status."""
    return oss_sync_poller.get_poller_status()


@app.get("/api/pipeline/cloud-bag-poller")
def api_cloud_bag_poller_status(
    _user: dict = Depends(require_pipeline_access),
) -> dict[str, Any]:
    from hmi.services import cloud_bag_trigger_poller

    return cloud_bag_trigger_poller.get_poller_status()


@app.post("/api/pipeline/cloud-bag-poller/scan")
def api_cloud_bag_poller_scan_now(
    _user: dict = Depends(require_pipeline_write),
) -> dict[str, Any]:
    """Manual orphan scan + DataWorks trigger (online mode)."""
    from hmi.data_source import is_cloud_mode
    from hmi.services import cloud_bag_trigger_poller

    if not is_cloud_mode():
        raise HTTPException(400, "cloud bag poller only runs in online mode")
    return cloud_bag_trigger_poller.run_scan_now()


@app.put("/api/sync/poller")
def api_set_sync_poller(
    body: SyncPollerBody,
    _user: dict = Depends(require_pipeline_write),
) -> dict[str, Any]:
    """Enable or disable automatic OSS → local sync (default off)."""
    oss_sync_poller.set_auto_sync_enabled(body.enabled)
    return oss_sync_poller.get_poller_status()


@app.get("/api/config/data-source")
def api_get_data_source() -> dict[str, Any]:
    from hmi.test_mode import enforce_data_source_for_test_mode, is_test_mode

    return {
        "data_source": enforce_data_source_for_test_mode(),
        "test_mode": is_test_mode(),
    }


@app.post("/api/config/data-source")
def api_set_data_source(
    body: DataSourceBody,
    _user: dict[str, Any] = Depends(require_non_anonymous),
) -> dict[str, Any]:
    from hmi.test_mode import is_test_mode

    if body.data_source.strip().lower() == "local" and not is_test_mode():
        raise HTTPException(
            403,
            detail={
                "code": "TEST_MODE_REQUIRED",
                "message": "非测试模式仅支持云端数据源；请在系统参数中开启 HMI_TEST_MODE",
            },
        )
    try:
        mode = set_data_source(body.data_source)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    from hmi.services import cloud_bag_trigger_poller, local_sdk_worker

    if mode == "local":
        from hmi.local.store import ensure_db

        ensure_db()
        local_sdk_worker.start_poller()
    else:
        local_sdk_worker.stop_poller()
        cloud_bag_trigger_poller.start_poller()
    cache_clear()
    return {
        "data_source": mode,
        "test_mode": is_test_mode(),
        "local_sdk_poller": local_sdk_worker.get_worker_status(),
    }


@app.post("/api/cache-clear")
def api_cache_clear(_user: dict[str, Any] = Depends(require_non_anonymous)) -> dict[str, int]:
    return {"cleared": cache_clear()}


@app.get("/api/local-files/clips/{clip_id}/runs/{run_id}/{file_path:path}")
def api_local_file(
    clip_id: str,
    run_id: str,
    file_path: str,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> FileResponse:
    if not is_local_mode():
        raise HTTPException(400, "local-files only available in local data mode")
    from hmi.data_source import artifact_path

    clip_id = unquote(clip_id)
    path = artifact_path(clip_id, run_id, file_path)
    if not path.is_file():
        raise HTTPException(404, f"file not found: {file_path}")
    root = artifact_path(clip_id, run_id, "").resolve()
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise HTTPException(403, "path escape") from exc
    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@app.get("/api/clips")
def api_list_clips(
    light: bool = Query(False),
    refresh: bool = Query(False, description="Bypass overview TTL cache"),
    _user: dict[str, Any] = Depends(require_overview_access),
) -> list[dict[str, Any]]:
    try:
        svc = clips_svc()
        if light:
            return svc.list_clips_light(refresh=refresh)
        return svc.list_clips()
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/clips/demo")
def api_list_demo_clips(
    _user: dict[str, Any] = Depends(require_overview_access),
) -> list[dict[str, Any]]:
    try:
        svc = clips_svc()
        if hasattr(svc, "list_demo_clips"):
            return svc.list_demo_clips()
        return []
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/hmi/reset-artifacts/status")
def api_reset_hmi_artifacts_status(
    _admin: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    return get_reset_progress()


@app.post("/api/hmi/reset-artifacts")
def api_reset_hmi_artifacts(_admin: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    try:
        result = reset_hmi_artifacts_to_baseline()
        cache_clear()
        return result
    except PermissionError as exc:
        raise HTTPException(
            403,
            detail={"code": "TEST_MODE_REQUIRED", "message": str(exc)},
        ) from exc
    except RuntimeError as exc:
        msg = str(exc)
        if "已有重置任务" in msg:
            raise HTTPException(
                409,
                detail={"code": "RESET_IN_PROGRESS", "message": msg},
            ) from exc
        raise HTTPException(
            500,
            detail={"code": "HMI_RESET_FAILED", "message": msg},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            500,
            detail={"code": "HMI_RESET_FAILED", "message": str(exc)},
        ) from exc


@app.get("/api/clips/batch-stats")
def api_batch_clip_stats(
    refresh: bool = Query(False, description="Bypass overview TTL cache"),
    _user: dict[str, Any] = Depends(require_overview_access),
) -> dict[str, dict[str, Any]]:
    try:
        return clips_svc().batch_all_clip_stats(refresh=refresh)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/clips/{clip_id}/stats")
def api_clip_stats(
    clip_id: str,
    run_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().get_clip_stats(clip_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/clips/{clip_id}")
def api_get_clip(
    clip_id: str,
    run_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().get_clip_overview(clip_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/clips/{clip_id}/explorer-bootstrap")
def api_explorer_bootstrap(
    clip_id: str,
    run_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().get_explorer_bootstrap(clip_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/clips/{clip_id}/runs")
def api_clip_runs(
    clip_id: str,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> list[dict[str, Any]]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().list_clip_runs(clip_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/clips/{clip_id}/timeline-meta")
def api_timeline_meta(
    clip_id: str,
    run_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().get_timeline_meta(clip_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/clips/{clip_id}/timeline")
def api_timeline(
    clip_id: str,
    timestamp_ns: int = Query(...),
    window_ms: int = Query(200),
    run_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().get_timeline_at(clip_id, timestamp_ns, window_ms, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/clips/{clip_id}/bboxes")
def api_clip_bboxes(
    clip_id: str,
    run_id: str = Query(..., min_length=1),
    timestamp_ns: int | None = Query(default=None),
    window_ms: int = Query(200, ge=0, le=5000),
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    """BBox detections from bboxes.jsonl near the playhead (Clip 详情)."""
    from hmi.data_source import is_local_mode
    from hmi.media.bbox_jsonl import bboxes_at_timestamp, load_bbox_frames

    clip_id = unquote(clip_id)
    rid = run_id.strip()
    if not is_local_mode():
        return {
            "clip_id": clip_id,
            "run_id": rid,
            "timestamp_ns": timestamp_ns,
            "window_ms": window_ms,
            "has_bboxes": False,
            "frame_count": 0,
            "frames_at_cursor": [],
            "detections": [],
            "message": "云端暂未提供 bboxes.jsonl 明细",
        }
    if timestamp_ns is None:
        frames = load_bbox_frames(clip_id, rid)
        return {
            "clip_id": clip_id,
            "run_id": rid,
            "timestamp_ns": None,
            "window_ms": window_ms,
            "has_bboxes": bool(frames),
            "frame_count": len(frames),
            "frames_at_cursor": [],
            "detections": [],
        }
    return bboxes_at_timestamp(clip_id, rid, int(timestamp_ns), window_ms=window_ms)


@app.get("/api/clips/{clip_id}/events")
def api_events(
    clip_id: str,
    run_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> list[dict[str, Any]]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().get_events(clip_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/clips/{clip_id}/audio-segments")
def api_audio_segments(
    clip_id: str,
    run_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> list[dict[str, Any]]:
    clip_id = unquote(clip_id)
    try:
        return clips_svc().get_audio_segments(clip_id, run_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/api/search")
def api_search(
    keyword: str = Query(""),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> dict[str, Any]:
    return search_svc().search_labels(keyword, page, page_size)


class OverviewClipQueryBody(BaseModel):
    label_filters: dict[str, Any] | None = None
    semantic_query: str = ""
    top_k: int = 200
    # Text lexical floor; embedding uses a higher fixed floor in clip_query_common.
    min_score: float = 0.25


@app.post("/api/clips/query")
def api_clips_query(
    body: OverviewClipQueryBody,
    _user: dict[str, Any] = Depends(require_overview_access),
) -> dict[str, Any]:
    """数据总览：标签筛选 + 场景描述语义检索（返回匹配 clip_id 列表）。"""
    top_k = max(1, min(int(body.top_k or 200), 500))
    min_score = float(body.min_score if body.min_score is not None else 0.25)
    min_score = max(0.0, min(min_score, 1.0))
    return search_svc().query_overview_clips(
        label_filters=body.label_filters,
        semantic_query=body.semantic_query or "",
        top_k=top_k,
        min_score=min_score,
    )


@app.get("/api/search/clusters")
def api_search_clusters(
    keyword: str = Query(""),
    label_id: str | None = None,
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> list[dict[str, Any]]:
    return search_svc().search_label_clusters(keyword, label_id)


@app.get("/api/label-taxonomy")
def api_label_taxonomy(
    version_id: str | None = Query(default=None),
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> list[dict[str, Any]]:
    if version_id:
        from hmi.taxonomy.compat import get_label_taxonomy
        from hmi.taxonomy_db import get_version

        if get_version(version_id) is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "404_NOT_FOUND", "message": "taxonomy version not found"},
            )
        return get_label_taxonomy(version_id)
    return search_svc().get_label_taxonomy()


@app.get("/api/label-suggestions")
def api_label_suggestions(
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> list[str]:
    return search_svc().get_label_suggestions()


@app.get("/api/similar")
def api_similar(
    id: str = Query(..., alias="id"),
    top_k: int = Query(8, ge=1, le=50),
    min_score: float = Query(0.75, ge=0.0, le=1.0),
    _user: dict[str, Any] = Depends(require_clip_explorer_access),
) -> list[dict[str, Any]]:
    try:
        return search_svc().find_similar(id, top_k=top_k, min_score=min_score)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc



@app.get("/api/oss/info")
def api_oss_info(_user: dict = Depends(require_oss_access)) -> dict[str, Any]:
    try:
        return oss_manage.get_oss_info()
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/oss/shortcuts")
def api_get_oss_shortcuts(user: dict = Depends(require_oss_access)):
    return get_shortcuts_for_user(user["id"])


@app.put("/api/oss/shortcuts")
def api_put_oss_shortcuts(body: OssShortcutsPutRequest, user: dict = Depends(require_oss_access)):
    try:
        return save_shortcuts_for_user(user["id"], body)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/oss/list")
def api_oss_list(
    prefix: str = Query(""),
    delimiter: str = Query("/"),
    max_keys: int = Query(500, ge=1, le=1000),
    _user: dict = Depends(require_oss_access),
) -> dict[str, Any]:
    try:
        return oss_manage.list_objects(prefix=prefix, delimiter=delimiter, max_keys=max_keys)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/oss/upload")
async def api_oss_upload(
    file: UploadFile = File(...),
    prefix: str = Query(""),
    _user: dict = Depends(require_oss_write),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(400, "filename required")
    data = await file.read()
    try:
        key = oss_manage.resolve_upload_key(prefix, file.filename)
        return oss_manage.upload_bytes(key, data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"OSS upload failed: {exc}") from exc


@app.delete("/api/oss/object")
def api_oss_delete_object(
    key: str = Query(...),
    _user: dict = Depends(require_oss_write),
) -> dict[str, Any]:
    try:
        return oss_manage.delete_objects([key])
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


class OssDeleteBody(BaseModel):
    keys: list[str]


@app.post("/api/oss/delete-batch")
def api_oss_delete_batch(
    body: OssDeleteBody,
    _user: dict = Depends(require_oss_write),
) -> dict[str, Any]:
    try:
        return oss_manage.delete_objects(body.keys)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/oss/delete-prefix")
def api_oss_delete_prefix(
    prefix: str = Query(...),
    _user: dict = Depends(require_oss_write),
) -> dict[str, Any]:
    try:
        return oss_manage.delete_prefix(prefix)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.post("/api/oss/mkdir")
def api_oss_mkdir(
    prefix: str = Query(...),
    _user: dict = Depends(require_oss_write),
) -> dict[str, Any]:
    try:
        return oss_manage.mkdir(prefix)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/oss/download-url")
def api_oss_download_url(
    key: str = Query(...),
    _user: dict = Depends(require_oss_access),
) -> dict[str, str]:
    try:
        return oss_manage.download_url(key)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/oss/preview")
def api_oss_preview(
    key: str = Query(...),
    _user: dict = Depends(require_oss_access),
) -> dict[str, Any]:
    try:
        return oss_manage.preview_object(key)
    except FileNotFoundError:
        raise HTTPException(404, "object not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/oss/file")
def api_oss_file(
    key: str = Query(...),
    _user: dict = Depends(require_oss_access),
):
    from hmi.data_source import is_local_mode

    try:
        if is_local_mode():
            path = oss_manage.local_file_path(key)
            media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            return FileResponse(path, media_type=media, filename=path.name)
        signed = oss_manage.download_url(key)["url"]
        from starlette.responses import RedirectResponse

        return RedirectResponse(url=signed, status_code=302)
    except FileNotFoundError:
        raise HTTPException(404, "object not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/oss/bag-pipeline")
def api_oss_bag_pipeline(
    key: str = Query(...),
    refresh: bool = Query(False),
    _user: dict = Depends(require_pipeline_access),
) -> dict[str, Any]:
    try:
        return pipeline_status.get_bag_pipeline(key, refresh=refresh)
    except Exception as exc:
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/pipeline/settings")
def api_get_pipeline_settings(
    _user: dict = Depends(require_pipeline_access),
) -> dict[str, Any]:
    from hmi.local.pipeline_settings import (
        get_bbox_detector_options,
        get_bbox_yolo_class_catalog,
        get_bbox_yolo_class_presets,
        get_model_option_lists,
        get_omni_label_prompt_schema,
        get_pipeline_settings,
        is_yolo_ready,
    )
    from hmi.taxonomy_db import list_pipeline_taxonomy_versions

    from oms_multimodal.label_prompt import default_omni_label_prompt

    settings = get_pipeline_settings()
    versions = [
        {
            "id": v["id"],
            "version_code": v["version_code"],
            "status": v["status"],
            "archive_reason": v.get("archive_reason"),
        }
        for v in list_pipeline_taxonomy_versions()
    ]
    return {
        "settings": settings,
        "options": {
            **get_model_option_lists(),
            "taxonomy_versions": versions,
            "omni_label_prompt_defaults": default_omni_label_prompt(),
            "omni_label_prompt_fields": get_omni_label_prompt_schema(),
            "bbox_detectors": get_bbox_detector_options(),
            "bbox_yolo_classes": get_bbox_yolo_class_catalog(),
            "bbox_yolo_presets": get_bbox_yolo_class_presets(),
            "bbox_yolo_available": is_yolo_ready(),
        },
    }


@app.put("/api/pipeline/settings")
def api_put_pipeline_settings(
    body: dict[str, Any],
    _user: dict = Depends(require_pipeline_write),
) -> dict[str, Any]:
    from hmi.local.pipeline_settings import save_pipeline_settings

    allowed = {
        "omni_model",
        "embedding_model",
        "taxonomy_version_id",
        "sample_fps",
        "min_sec",
        "max_sec",
        "max_clips",
        "sdk_parallel",
        "omni_label_prompt",
        "bbox_enabled",
        "bbox_detector",
        "bbox_element",
        "encode_plain",
        "encode_bbox",
        "bbox_yolo_model",
        "bbox_yolo_conf",
        "bbox_yolo_classes",
        "bbox_in_label_prompt",
        "bbox_face_attrs",
    }
    updates = {k: body[k] for k in allowed if k in body}
    try:
        saved = save_pipeline_settings(updates)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"settings": saved}


@app.get("/api/pipeline/executions")
def api_list_pipeline_executions(
    page: int = 1,
    page_size: int = 10,
    refresh: bool = Query(False, description="Bypass execution refresh throttle / bag cache"),
    _user: dict = Depends(require_pipeline_access),
) -> dict[str, Any]:
    if is_local_mode():
        from hmi.local.pipeline_execution import list_executions

        return list_executions(page=page, page_size=page_size)
    from hmi.services.cloud_pipeline_execution import list_executions as list_cloud_executions

    return list_cloud_executions(page=page, page_size=page_size, refresh=refresh)


@app.post("/api/pipeline/executions")
async def api_create_pipeline_execution(
    files: list[UploadFile] = File(...),
    trigger: bool = Query(
        True,
        description="Cloud only: false = upload to OSS only (no DataWorks OpenAPI). "
        "Periodic DW schedules discover bags under rosbags/.",
    ),
    _user: dict = Depends(require_pipeline_write),
) -> dict[str, Any]:
    if not files:
        raise HTTPException(400, "at least one file required")

    from hmi.db import cache_clear
    from hmi.local.source_upload import classify_source_filename

    batch_files: list[tuple[str, bytes]] = []
    kinds: set[str] = set()
    for upload in files:
        name = upload.filename or ""
        kind = classify_source_filename(name)
        if kind is None:
            raise HTTPException(
                400,
                f"unsupported file type: {name} "
                "(accept .bag / video mp4|webm|mov|mkv / audio wav|mp3|m4a|flac|ogg / text txt|json|md|csv)",
            )
        kinds.add(kind)
        data = await upload.read()
        batch_files.append((name, data))

    has_media = bool(kinds & {"video", "audio", "text"})

    if is_local_mode():
        from hmi.local.pipeline_execution import enqueue_pipeline_sources_batch, enqueue_rosbags_batch

        try:
            if has_media:
                result = enqueue_pipeline_sources_batch(batch_files)
            else:
                result = enqueue_rosbags_batch(batch_files)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"enqueue failed: {exc}") from exc
        cache_clear()
        return result

    if has_media:
        raise HTTPException(
            400,
            "原始视频/音频/文本上传目前仅支持本地模式；云端请继续上传 .bag，或切换数据源为 local",
        )

    from hmi.services.cloud_pipeline_execution import enqueue_rosbags_cloud
    from hmi.services.dataworks_trigger import DataWorksConfigError, DataWorksThrottleError

    try:
        result = enqueue_rosbags_cloud(batch_files, trigger=bool(trigger))
    except DataWorksThrottleError as exc:
        raise HTTPException(429, detail={"code": "DATAWORKS_THROTTLED", "message": str(exc)}) from exc
    except DataWorksConfigError as exc:
        raise HTTPException(503, detail={"code": "DATAWORKS_CONFIG", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "BAD_REQUEST", "message": str(exc)}) from exc
    except Exception as exc:
        logging.getLogger(__name__).exception("cloud enqueue failed")
        msg = str(exc)
        if "Throttling" in msg or "熔断" in msg or "调用次数已达上限" in msg:
            raise HTTPException(
                429, detail={"code": "DATAWORKS_THROTTLED", "message": msg}
            ) from exc
        raise HTTPException(
            500, detail={"code": "CLOUD_ENQUEUE_FAILED", "message": f"cloud enqueue failed: {exc}"}
        ) from exc
    cache_clear()
    return result


@app.post("/api/upload/rosbag")
async def api_upload_rosbag(
    file: UploadFile = File(...),
    _user: dict = Depends(require_pipeline_write),
) -> dict[str, Any]:
    if not file.filename or not file.filename.lower().endswith(".bag"):
        raise HTTPException(400, "Only .bag files are accepted")
    data = await file.read()
    if is_local_mode():
        from hmi.db import cache_clear
        from hmi.local import bag_upload

        try:
            saved = bag_upload.save_uploaded_rosbag(file.filename, data)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f"local save failed: {exc}") from exc
        cache_clear()
        return upload.create_local_upload_task(
            file.filename,
            len(data),
            oss_key=str(saved["oss_key"]),
            bag_oss_key=str(saved["bag_oss_key"]),
            clip_id=str(saved["clip_id"]),
            run_id=str(saved["run_id"]),
        )
    from hmi.oss_signer import upload_rosbag_bytes

    try:
        oss_key = upload_rosbag_bytes(file.filename, data)
    except Exception as exc:
        raise HTTPException(500, f"OSS upload failed: {exc}") from exc
    return upload.create_upload_task(file.filename, len(data), oss_key)


@app.get("/api/upload/tasks")
def api_upload_tasks(_user: dict = Depends(require_pipeline_access)) -> list[dict[str, Any]]:
    return upload.list_upload_tasks()


def _mount_frontend() -> None:
    dist = os.environ.get("FRONTEND_DIST", "").strip()
    if not dist:
        return
    static_dir = Path(dist)
    if not static_dir.is_dir():
        return

    no_cache = {
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache",
    }

    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    def spa_index() -> FileResponse:
        return FileResponse(static_dir / "index.html", headers=no_cache)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = static_dir / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(static_dir / "index.html", headers=no_cache)


@app.middleware("http")
async def html_no_cache(request, call_next):
    response = await call_next(request)
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


_mount_frontend()
