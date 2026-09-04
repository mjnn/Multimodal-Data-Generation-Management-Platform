"""HMI 在反代子路径下的公共前缀（如 /tools/rosbag-labels）。

HMI_PUBLIC_API_BASE=/tools/rosbag-labels/api → UI 前缀 /tools/rosbag-labels。
直连 :8012 时浏览器仍请求带前缀的 assets/api；中间件剥前缀后走现有 /assets 与 /api。
nginx 已剥前缀时，请求本来就是 /assets、/api，本模块 no-op。
"""

from __future__ import annotations

import os
from typing import Any


def ui_public_prefix() -> str:
    api_base = (os.environ.get("HMI_PUBLIC_API_BASE") or "/api").strip().rstrip("/")
    if not api_base.startswith("/"):
        api_base = f"/{api_base}"
    if api_base.endswith("/api") and api_base != "/api":
        return api_base[: -len("/api")].rstrip("/") or ""
    return ""


def strip_ui_prefix_scope(scope: dict[str, Any]) -> None:
    prefix = ui_public_prefix()
    if not prefix:
        return
    path = str(scope.get("path") or "")
    if path != prefix and not path.startswith(prefix + "/"):
        return
    scope["path"] = path[len(prefix) :] or "/"
    raw = scope.get("raw_path")
    if not isinstance(raw, (bytes, bytearray)):
        return
    pref_b = prefix.encode("ascii")
    if raw == pref_b or raw.startswith(pref_b + b"/"):
        scope["raw_path"] = raw[len(pref_b) :] or b"/"
