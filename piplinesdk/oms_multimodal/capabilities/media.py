"""按 RunContext 解析 MC / API 媒体输入模式。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from .types import RunContext

if TYPE_CHECKING:
    from ..mc.config import McBackendConfig


def apply_run_context_to_mc_config(ctx: RunContext, mc_config: McBackendConfig) -> McBackendConfig:
    """按节点 RunContext 覆盖 MC 读图/读音频方式（非全局默认）。"""
    mode = ctx.resolved_media_mode()
    mc_config.image_mode = "oss_url" if mode == "oss" else "base64"
    if ctx.oss_bucket:
        mc_config.oss_bucket = ctx.oss_bucket
    if ctx.cloud_region:
        mc_config.cloud_region = ctx.cloud_region
    return mc_config
