"""JWT create/decode helpers."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

ACCESS_TOKEN_MINUTES = 30
REFRESH_TOKEN_DAYS = 7
ALGORITHM = "HS256"

ACCESS_COOKIE = "hmi_access_token"
REFRESH_COOKIE = "hmi_refresh_token"


def _jwt_secret() -> str:
    secret = os.environ.get("HMI_JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("HMI_JWT_SECRET is not set in environment")
    return secret


def _expiry(minutes: int = 0, days: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes, days=days)


def create_access_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": user["id"],
        "username": user["username"],
        "roles": user.get("roles") or [],
        "type": "access",
        "exp": _expiry(minutes=ACCESS_TOKEN_MINUTES),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def create_refresh_token(user: dict[str, Any]) -> str:
    payload = {
        "sub": user["id"],
        "username": user["username"],
        "roles": user.get("roles") or [],
        "type": "refresh",
        "exp": _expiry(days=REFRESH_TOKEN_DAYS),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=ALGORITHM)


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    payload = jwt.decode(token, _jwt_secret(), algorithms=[ALGORITHM])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected token type {expected_type}")
    return payload
