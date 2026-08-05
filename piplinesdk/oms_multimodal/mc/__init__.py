"""MaxCompute / MaxFrame 模型后端（``MODEL_BACKEND=mc``）。"""
from __future__ import annotations

from .config import DEFAULT_MODELSET_PROJECT, McBackendConfig
from .runtime import McRuntime, resolve_odps_entry

__all__ = [
    "DEFAULT_MODELSET_PROJECT",
    "McAsrClient",
    "McBackendConfig",
    "McFusionEmbeddingClient",
    "McOmniLabelClient",
    "McRuntime",
    "resolve_odps_entry",
]


def __getattr__(name: str):
    if name == "McAsrClient":
        from .asr_client import McAsrClient

        return McAsrClient
    if name == "McFusionEmbeddingClient":
        from .embedding_client import McFusionEmbeddingClient

        return McFusionEmbeddingClient
    if name == "McOmniLabelClient":
        from .omni_client import McOmniLabelClient

        return McOmniLabelClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
