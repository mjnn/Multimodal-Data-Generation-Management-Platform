"""Auth API routes."""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from hmi.app_db import authenticate_user, create_user, delete_user, get_user_by_id, update_user
from hmi.auth.deps import get_current_user
from hmi.auth.roles import DEFAULT_REGISTRATION_ROLES
from hmi.auth.jwt_utils import (
    ACCESS_COOKIE,
    ACCESS_TOKEN_MINUTES,
    REFRESH_COOKIE,
    REFRESH_TOKEN_DAYS,
    auth_cookie_paths,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from hmi.auth.models import (
    ChangePasswordRequest,
    DeleteAccountRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    RegisterRequest,
    RegisterResponse,
    UpdateMeRequest,
    UserPublic,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_public(user: dict) -> UserPublic:
    return UserPublic(
        id=user["id"],
        username=user["username"],
        display_name=user["display_name"],
        roles=user.get("roles") or [],
        is_active=user["is_active"],
    )


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    access_path, refresh_path = auth_cookie_paths()
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path=access_path,
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_DAYS * 24 * 3600,
        path=refresh_path,
    )


def _clear_auth_cookies(response: Response) -> None:
    access_path, refresh_path = auth_cookie_paths()
    response.delete_cookie(ACCESS_COOKIE, path=access_path)
    response.delete_cookie(REFRESH_COOKIE, path=refresh_path)


@router.post("/register", response_model=RegisterResponse)
def register(body: RegisterRequest, response: Response) -> RegisterResponse:
    import os

    allow = os.getenv("HMI_ALLOW_REGISTRATION", "1").strip().lower()
    if allow in {"0", "false", "no", "off"}:
        raise HTTPException(
            status_code=403,
            detail={"code": "403_FORBIDDEN", "message": "注册已关闭"},
        )
    try:
        user = create_user(
            body.username.strip(),
            body.password,
            display_name=(body.display_name or body.username).strip(),
            roles=list(DEFAULT_REGISTRATION_ROLES),
            is_active=True,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "400_BAD_REQUEST", "message": str(exc)},
        ) from exc

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user)
    _set_auth_cookies(response, access_token, refresh_token)

    return RegisterResponse(
        ok=True,
        message="注册成功，当前为匿名账号，仅可查看数据总览。如需管线、校核等功能请联系管理员分配角色",
        access_token=access_token,
        expires_in=ACCESS_TOKEN_MINUTES * 60,
        user=_user_public(user),
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response) -> LoginResponse:
    user = authenticate_user(body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "用户名或密码错误"},
        )

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user)
    _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_MINUTES * 60,
        user=_user_public(user),
    )


@router.post("/refresh", response_model=LoginResponse)
def refresh_token(request: Request, response: Response) -> LoginResponse:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "刷新令牌缺失，请重新登录"},
        )
    try:
        payload = decode_token(token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "刷新令牌无效，请重新登录"},
        ) from exc

    user = get_user_by_id(str(payload["sub"]))
    if user is None or not user["is_active"]:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "用户不存在或已禁用"},
        )

    access_token = create_access_token(user)
    refresh_token = create_refresh_token(user)
    _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        access_token=access_token,
        expires_in=ACCESS_TOKEN_MINUTES * 60,
        user=_user_public(user),
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    _clear_auth_cookies(response)
    return {"ok": True}


@router.get("/me", response_model=MeResponse)
def me(user: dict = Depends(get_current_user)) -> MeResponse:
    return MeResponse(user=_user_public(user))


@router.patch("/me", response_model=MeResponse)
def patch_me(body: UpdateMeRequest, user: dict = Depends(get_current_user)) -> MeResponse:
    if body.display_name is None:
        return MeResponse(user=_user_public(user))
    try:
        updated = update_user(user["id"], display_name=body.display_name.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return MeResponse(user=_user_public(updated))


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(get_current_user)) -> dict[str, bool]:
    if authenticate_user(user["username"], body.current_password) is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "400_BAD_REQUEST", "message": "当前密码不正确"},
        )
    try:
        update_user(user["id"], password=body.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/me")
def delete_me(
    body: DeleteAccountRequest,
    response: Response,
    user: dict = Depends(get_current_user),
) -> dict[str, bool]:
    if authenticate_user(user["username"], body.password) is None:
        raise HTTPException(
            status_code=400,
            detail={"code": "400_BAD_REQUEST", "message": "密码不正确"},
        )
    try:
        delete_user(user["id"])
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "422_VALIDATION", "message": str(exc)},
        ) from exc
    _clear_auth_cookies(response)
    return {"ok": True}
