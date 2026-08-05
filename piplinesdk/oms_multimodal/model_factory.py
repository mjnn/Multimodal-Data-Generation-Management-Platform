"""按 ``MODEL_BACKEND`` 创建 ASR / 打标 / Embedding 客户端。"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .asr_client import AsrClient, AsrConfig
from .config import ClientConfig, ModelBackend
from .embedding_client import FusionEmbeddingClient
from .exceptions import ConfigurationError
from .omni_client import OmniLabelClient

if TYPE_CHECKING:
    from .mc.config import McBackendConfig
    from .mc.runtime import McRuntime


def _mc_backend_config_cls():
    from .mc.config import McBackendConfig

    return McBackendConfig


def _mc_runtime_cls():
    from .mc.runtime import McRuntime

    return McRuntime


def create_mc_runtime(config: ClientConfig) -> McRuntime:
    McBackendConfig = _mc_backend_config_cls()
    McRuntime = _mc_runtime_cls()
    mc_cfg = config.mc_config or McBackendConfig.from_env(odps_entry=config.mc_odps_entry)
    if config.mc_odps_entry is not None:
        mc_cfg.odps_entry = config.mc_odps_entry
    return McRuntime(config=mc_cfg)


def create_asr_client(
    *,
    backend: ModelBackend,
    config: ClientConfig,
    mc_runtime: McRuntime | None = None,
    asr_config: AsrConfig | None = None,
    api_key: str | None = None,
    workspace_id: str | None = None,
) -> AsrClient | Any:
    cfg = asr_config or config.asr_config or AsrConfig.from_env()
    if backend == "api":
        return AsrClient(config=cfg, api_key=api_key or config.api_key, workspace_id=workspace_id or config.workspace_id)
    from .mc.asr_client import McAsrClient

    runtime = mc_runtime or create_mc_runtime(config)
    mc_cfg = runtime.config
    return McAsrClient(runtime=runtime, config=mc_cfg, asr_config=cfg)


def create_omni_client(
    *,
    backend: ModelBackend,
    config: ClientConfig,
    mc_runtime: McRuntime | None = None,
    api_key: str | None = None,
    workspace_id: str | None = None,
    region: str | None = None,
) -> OmniLabelClient | Any:
    if backend == "api":
        return OmniLabelClient(
            model=config.omni_model,
            api_key=api_key or config.api_key,
            workspace_id=workspace_id or config.workspace_id,
            region=region or config.region,
            omni_label_prompt=config.omni_label_prompt,
        )
    from .mc.omni_client import McOmniLabelClient

    runtime = mc_runtime or create_mc_runtime(config)
    return McOmniLabelClient(
        runtime=runtime,
        config=runtime.config,
        model=config.omni_model,
        omni_label_prompt=config.omni_label_prompt,
    )


def create_embedding_client(
    *,
    backend: ModelBackend,
    config: ClientConfig,
    mc_runtime: McRuntime | None = None,
    api_key: str | None = None,
) -> FusionEmbeddingClient | Any:
    if backend == "api":
        return FusionEmbeddingClient(
            model=config.embedding_model,
            dimension=config.embedding_dimension,
            api_key=api_key or config.api_key,
        )
    from .mc.embedding_client import McFusionEmbeddingClient

    runtime = mc_runtime or create_mc_runtime(config)
    return McFusionEmbeddingClient(
        runtime=runtime,
        config=runtime.config,
        model=config.embedding_model,
        dimension=config.embedding_dimension,
    )


def validate_backend_config(backend: ModelBackend, config: ClientConfig) -> None:
    if backend == "api":
        return
    if backend != "mc":
        raise ConfigurationError(f"Unknown model_backend: {backend!r}")
    create_mc_runtime(config)
