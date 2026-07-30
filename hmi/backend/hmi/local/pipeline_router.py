"""Local pipeline control API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hmi.auth.deps import require_pipeline_write
from hmi.data_source import is_local_mode

router = APIRouter(prefix="/api/pipeline", tags=["pipeline-local"])


class PipelineRetryBody(BaseModel):
    clip_id: str
    run_id: str | None = None


@router.post("/runs/retry")
def api_pipeline_run_retry(
    body: PipelineRetryBody,
    _user: dict = Depends(require_pipeline_write),
) -> dict[str, Any]:
    if not is_local_mode():
        raise HTTPException(status_code=400, detail="pipeline retry is only available in local mode")
    clip_id = body.clip_id.strip()
    if not clip_id:
        raise HTTPException(status_code=422, detail="clip_id required")
    run_id = (body.run_id or "").strip() or None
    try:
        from hmi.local.pipeline_retry import reset_local_pipeline_to_post_upload

        return reset_local_pipeline_to_post_upload(clip_id=clip_id, run_id=run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/executions/{run_id}/cancel")
def api_cancel_pipeline_execution(
    run_id: str,
    _user: dict = Depends(require_pipeline_write),
) -> dict[str, Any]:
    if not is_local_mode():
        raise HTTPException(status_code=400, detail="cancel execution is only available in local mode")
    try:
        from hmi.local.pipeline_execution import cancel_execution

        return cancel_execution(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
