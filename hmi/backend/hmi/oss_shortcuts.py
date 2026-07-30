"""Per-user OSS browser shortcuts (stored in app.db)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from hmi.app_db import list_user_oss_shortcuts, replace_user_oss_shortcuts


class OssShortcutItem(BaseModel):
    id: str | None = None
    label: str = Field(min_length=1, max_length=64)
    prefix: str = Field(min_length=1, max_length=512)


class OssShortcutPublic(BaseModel):
    id: str
    label: str
    prefix: str


class OssShortcutsResponse(BaseModel):
    items: list[OssShortcutPublic]


class OssShortcutsPutRequest(BaseModel):
    items: list[OssShortcutItem] = Field(default_factory=list, max_length=50)


def get_shortcuts_for_user(user_id: str) -> OssShortcutsResponse:
    rows = list_user_oss_shortcuts(user_id)
    return OssShortcutsResponse(items=[OssShortcutPublic(**r) for r in rows])


def save_shortcuts_for_user(user_id: str, body: OssShortcutsPutRequest) -> OssShortcutsResponse:
    payload = [{"id": i.id, "label": i.label, "prefix": i.prefix} for i in body.items]
    rows = replace_user_oss_shortcuts(user_id, payload)
    return OssShortcutsResponse(items=[OssShortcutPublic(**r) for r in rows])
