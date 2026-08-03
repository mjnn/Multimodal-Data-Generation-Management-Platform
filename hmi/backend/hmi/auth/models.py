"""Auth request/response models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserPublic(BaseModel):
    id: str
    username: str
    display_name: str
    roles: list[str]
    is_active: bool


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class MeResponse(BaseModel):
    user: UserPublic


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=8)
    display_name: str | None = Field(default=None, max_length=64)


class RegisterResponse(BaseModel):
    ok: bool = True
    message: str
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserPublic


class UpdateMeRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1)
