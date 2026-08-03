"""Admin user management API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from hmi.app_db import create_user, delete_user, get_user_by_id, list_users, update_user
from hmi.audit import query_audit_logs
from hmi.auth.deps import require_admin
from hmi.auth.models import UserPublic
from hmi.system_env import get_system_env_snapshot, save_system_env

router = APIRouter(prefix="/api/admin", tags=["admin"])


class CreateUserBody(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=8)
    display_name: str | None = None
    roles: list[str] = Field(default_factory=list)


class UpdateUserBody(BaseModel):
    display_name: str | None = None
    is_active: bool | None = None
    roles: list[str] | None = None
    password: str | None = Field(default=None, min_length=8)


class SystemEnvBody(BaseModel):
    env: dict[str, str | None] = Field(default_factory=dict)


@router.get("/system-env")
def api_get_system_env(_admin: dict = Depends(require_admin)) -> dict[str, Any]:
    return get_system_env_snapshot(reveal_secrets=True)


@router.put("/system-env")
def api_put_system_env(
    body: SystemEnvBody,
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return save_system_env(body.env)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": str(exc)},
        ) from exc


def _user_public(user: dict[str, Any]) -> UserPublic:
    return UserPublic(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        roles=user.get("roles") or [],
        is_active=user["is_active"],
    )


@router.get("/users")
def api_list_users(_admin: dict = Depends(require_admin)) -> list[UserPublic]:
    return [_user_public(u) for u in list_users()]


@router.post("/users", status_code=201)
def api_create_user(body: CreateUserBody, _admin: dict = Depends(require_admin)) -> UserPublic:
    try:
        user = create_user(
            body.username,
            body.password,
            display_name=body.display_name,
            roles=body.roles,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": str(exc)},
        ) from exc
    return _user_public(user)


@router.patch("/users/{user_id}")
def api_update_user(
    user_id: str,
    body: UpdateUserBody,
    _admin: dict = Depends(require_admin),
) -> UserPublic:
    if get_user_by_id(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "user not found"},
        )
    try:
        user = update_user(
            user_id,
            display_name=body.display_name,
            is_active=body.is_active,
            roles=body.roles,
            password=body.password,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": str(exc)},
        ) from exc
    return _user_public(user)


@router.delete("/users/{user_id}")
def api_delete_user(user_id: str, admin: dict = Depends(require_admin)) -> dict[str, bool]:
    if get_user_by_id(user_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "404_NOT_FOUND", "message": "user not found"},
        )
    if user_id == admin["id"]:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "400_BAD_REQUEST",
                "message": "use DELETE /api/auth/me to delete your own account",
            },
        )
    try:
        delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": str(exc)},
        ) from exc
    return {"ok": True}


@router.get("/audit")
def api_list_audit_logs(
    action: str | None = Query(default=None),
    resource_type: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_admin),
) -> dict[str, Any]:
    items, total = query_audit_logs(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        actor_id=actor_id,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}
