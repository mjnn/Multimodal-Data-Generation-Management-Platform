"""HTTP middleware: require JWT on /api/* except public paths."""

from __future__ import annotations

import jwt
from starlette.requests import Request
from starlette.responses import JSONResponse

from hmi.app_db import get_user_by_id
from hmi.auth.deps import extract_bearer_token, public_api_path
from hmi.auth.jwt_utils import decode_token


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        path = request.url.path

        if not path.startswith("/api/") or public_api_path(path):
            await self.app(scope, receive, send)
            return

        token = extract_bearer_token(request)
        if not token:
            response = JSONResponse(
                status_code=401,
                content={
                    "detail": {
                        "code": "401_UNAUTHORIZED",
                        "message": "authentication required",
                    }
                },
            )
            await response(scope, receive, send)
            return

        try:
            payload = decode_token(token, expected_type="access")
            user = get_user_by_id(str(payload["sub"]))
            if user is None or not user["is_active"]:
                raise jwt.InvalidTokenError("inactive user")
        except jwt.PyJWTError:
            response = JSONResponse(
                status_code=401,
                content={
                    "detail": {
                        "code": "401_UNAUTHORIZED",
                        "message": "invalid or expired token",
                    }
                },
            )
            await response(scope, receive, send)
            return

        scope.setdefault("state", {})
        scope["state"]["user"] = user

        await self.app(scope, receive, send)
