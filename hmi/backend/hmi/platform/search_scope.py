"""Require a DataType workspace id on search / overview queries."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

OMS_DATA_TYPE_ID = "oms_cabin"
IVI_DATA_TYPE_ID = "ivi_ui_stub"


def require_data_type_id(data_type_id: str | None) -> str:
    tid = (data_type_id or "").strip() or OMS_DATA_TYPE_ID
    from hmi.platform.store import get_data_type

    recipe = get_data_type(tid)
    if recipe is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "UNKNOWN_DATA_TYPE", "message": f"unknown data_type_id={tid}"},
        )
    return tid


def uses_oms_legacy_index(data_type_id: str) -> bool:
    return data_type_id == OMS_DATA_TYPE_ID


def empty_search_page(page: int, page_size: int) -> dict[str, Any]:
    return {"items": [], "total": 0, "page": page, "page_size": page_size}


def empty_overview_query() -> dict[str, Any]:
    return {
        "total": 0,
        "items": [],
        "semantic_mode": "none",
        "embedding_used": False,
        "message": None,
    }
