"""ODPS access + TTL query cache."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from cachetools import TTLCache
from odps import ODPS

from hmi.config import get_settings

_query_cache: TTLCache = TTLCache(maxsize=512, ttl=600)


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


@lru_cache
def odps_client() -> ODPS:
    s = get_settings()
    return ODPS(
        s["odps_access_id"],
        s["odps_access_key"],
        project=s["odps_project"],
        endpoint=s["odps_endpoint"],
    )


def cache_clear() -> int:
    from hmi.clip_context import context_cache_clear
    from hmi.services import clips, clips_local, pipeline_status, search, search_local
    from hmi.services.overview_cache import overview_cache_clear

    n = len(_query_cache)
    _query_cache.clear()
    context_cache_clear()
    clips.label_map_cache_clear()
    clips_local.label_map_cache_clear()
    search.labeled_frames_cache_clear()
    search_local.labeled_frames_cache_clear()
    pipeline_status.bag_pipeline_cache_clear()
    overview_cache_clear()
    return n


def _cell(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[1]
    return value


def _row_to_dict(reader: Any, row: Any) -> dict[str, Any]:
    names = reader.schema.names
    out: dict[str, Any] = {}
    for i, name in enumerate(names):
        if hasattr(row, name):
            out[name] = _cell(getattr(row, name))
        else:
            out[name] = _cell(row[i])
    return out


def query(sql: str, *, cache: bool = True) -> list[dict[str, Any]]:
    if cache and sql in _query_cache:
        return _query_cache[sql]
    client = odps_client()
    with client.execute_sql(sql).open_reader() as reader:
        rows = [_row_to_dict(reader, row) for row in reader]
    if cache:
        _query_cache[sql] = rows
    return rows


def normalize_pipeline_status(raw: str | None) -> str:
    v = (raw or "").strip().lower()
    if v in {"ok", "success", "succeeded", "done", "completed"}:
        return "success"
    if v in {"failed", "error", "fail"}:
        return "failed"
    if v in {"running", "processing", "in_progress"}:
        return "running"
    if v in {"skipped", "skip"}:
        return "skipped"
    if v in {"cancelled", "canceled", "aborted", "abort"}:
        return "cancelled"
    return "pending"
