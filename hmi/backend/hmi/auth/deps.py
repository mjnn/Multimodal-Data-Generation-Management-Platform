"""FastAPI dependencies for authenticated routes."""

from __future__ import annotations

from typing import Any

import jwt
from fastapi import Depends, HTTPException, Request

from hmi.app_db import get_user_by_id
from hmi.auth.jwt_utils import ACCESS_COOKIE, decode_token
from hmi.auth.roles import ROLE_ANONYMOUS, has_standard_role, normalized_roles

PUBLIC_API_PATHS = frozenset(
    {
        "/api/health",
        "/api/auth/login",
        "/api/auth/refresh",
        "/api/auth/register",
    }
)


def public_api_path(path: str) -> bool:
    if path in PUBLIC_API_PATHS:
        return True
    return False


def extract_bearer_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        return token or None
    cookie_token = request.cookies.get(ACCESS_COOKIE)
    if cookie_token:
        return cookie_token
    return None


def resolve_user_from_token(token: str) -> dict[str, Any]:
    try:
        payload = decode_token(token, expected_type="access")
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "登录已失效，请重新登录"},
        ) from exc

    user = get_user_by_id(str(payload["sub"]))
    if user is None or not user["is_active"]:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "用户不存在或已禁用"},
        )
    return user


def get_current_user(request: Request) -> dict[str, Any]:
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    token = extract_bearer_token(request)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "请先登录"},
        )
    user = resolve_user_from_token(token)
    request.state.user = user
    return user


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if "admin" not in (user.get("roles") or []):
        raise HTTPException(
            status_code=403,
            detail={"code": "403_FORBIDDEN", "message": "需要管理员权限"},
        )
    return user


def require_oss_access(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    roles = user.get("roles") or []
    if not any(r in roles for r in ("admin", "dataset_manager")):
        raise HTTPException(
            status_code=403,
            detail={"code": "403_FORBIDDEN", "message": "OSS 访问需要管理员或数据集管理员权限"},
        )
    return user


def require_pipeline_access(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    roles = user.get("roles") or []
    if not any(r in roles for r in ("admin", "dataset_manager", "pipeline_manager")):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "403_FORBIDDEN",
                "message": "管线访问需要管理员、数据集管理员或管线管理员权限",
            },
        )
    return user


def require_pipeline_write(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return require_pipeline_access(user)


def require_oss_write(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return require_oss_access(user)


def require_reviewer(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    roles = user.get("roles") or []
    if not any(r in roles for r in ("admin", "reviewer")):
        raise HTTPException(
            status_code=403,
            detail={"code": "403_FORBIDDEN", "message": "校核访问需要管理员或校核员权限"},
        )
    return user


def require_dataset_read(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    roles = user.get("roles") or []
    if not any(r in roles for r in ("admin", "dataset_manager", "model_trainer")):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "403_FORBIDDEN",
                "message": "数据集读取需要管理员、数据集管理员或模型训练员权限",
            },
        )
    return user


def require_dataset_manager(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    roles = user.get("roles") or []
    if not any(r in roles for r in ("admin", "dataset_manager")):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "403_FORBIDDEN",
                "message": "数据集写入需要管理员或数据集管理员权限",
            },
        )
    return user


def require_overview_access(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """数据总览：匿名或任意标准角色。"""
    roles = normalized_roles(user.get("roles"))
    if ROLE_ANONYMOUS in roles or has_standard_role(roles):
        return user
    raise HTTPException(
        status_code=403,
        detail={
            "code": "403_FORBIDDEN",
            "message": "无权访问数据总览",
        },
    )


def require_clip_explorer_access(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """Clip 时间轴 / 检索：须具备除 anonymous 外的业务角色。"""
    if not has_standard_role(user.get("roles")):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "403_FORBIDDEN",
                "message": "Clip 详情与检索需要管理员分配的业务角色（匿名账号仅可查看数据总览）",
            },
        )
    return user


def require_non_anonymous(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if not has_standard_role(user.get("roles")):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "403_FORBIDDEN",
                "message": "此操作需要除匿名外的业务角色",
            },
        )
    return user
