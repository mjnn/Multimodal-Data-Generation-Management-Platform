"""Auth API routes."""

from __future__ import annotations

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from hmi.app_db import authenticate_user, get_user_by_id
from hmi.auth.deps import get_current_user
from hmi.auth.jwt_utils import (
    ACCESS_COOKIE,
    ACCESS_TOKEN_MINUTES,
    REFRESH_COOKIE,
    REFRESH_TOKEN_DAYS,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from hmi.auth.models import LoginRequest, LoginResponse, MeResponse, UserPublic

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
    response.set_cookie(
        key=ACCESS_COOKIE,
        value=access_token,
        httponly=True,
        samesite="lax",
        max_age=ACCESS_TOKEN_MINUTES * 60,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        samesite="lax",
        max_age=REFRESH_TOKEN_DAYS * 24 * 3600,
        path="/api/auth",
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, response: Response) -> LoginResponse:
    user = authenticate_user(body.username, body.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "invalid username or password"},
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
            detail={"code": "401_UNAUTHORIZED", "message": "refresh token missing"},
        )
    try:
        payload = decode_token(token, expected_type="refresh")
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "invalid refresh token"},
        ) from exc

    user = get_user_by_id(str(payload["sub"]))
    if user is None or not user["is_active"]:
        raise HTTPException(
            status_code=401,
            detail={"code": "401_UNAUTHORIZED", "message": "user not found or inactive"},
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
