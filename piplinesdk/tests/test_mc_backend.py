"""Tests for MODEL_BACKEND=mc scaffolding (no MaxFrame required)."""
from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from oms_multimodal import OmsMultimodalClient
from oms_multimodal.asr_client import AsrConfig
from oms_multimodal.config import ClientConfig
from oms_multimodal.exceptions import ConfigurationError
from oms_multimodal.mc.config import McBackendConfig
from oms_multimodal.mc.runtime import is_omni_model_name, resolve_odps_entry
from oms_multimodal.model_factory import create_asr_client, create_embedding_client, create_omni_client


class TestMcBackendConfig(unittest.TestCase):
    def test_resolved_image_mode_auto_without_oss(self) -> None:
        cfg = McBackendConfig(image_mode="auto")
        self.assertEqual(cfg.resolved_image_mode(), "base64")

    def test_resolved_image_mode_auto_with_oss_creds(self) -> None:
        cfg = McBackendConfig(
            image_mode="auto",
            oss_bucket="rosbag-labels-bucket",
            oss_access_key_id="ak",
            oss_access_key_secret="sk",
        )
        self.assertEqual(cfg.resolved_image_mode(), "oss_url")

    def test_from_env_omni_fallback(self) -> None:
        with patch.dict(os.environ, {"MC_OMNI_FALLBACK_MODEL": "qwen3.6-plus"}, clear=False):
            cfg = McBackendConfig.from_env()
        self.assertEqual(cfg.omni_fallback_model, "qwen3.6-plus")


class TestModelFactory(unittest.TestCase):
    def test_api_backend_returns_dashscope_clients(self) -> None:
        cfg = ClientConfig(api_key="sk-test", workspace_id="ws-test", model_backend="api")
        asr = create_asr_client(backend="api", config=cfg)
        omni = create_omni_client(backend="api", config=cfg)
        emb = create_embedding_client(backend="api", config=cfg)
        self.assertEqual(type(asr).__name__, "AsrClient")
        self.assertEqual(type(omni).__name__, "OmniLabelClient")
        self.assertEqual(type(emb).__name__, "FusionEmbeddingClient")

    def test_mc_backend_requires_maxframe(self) -> None:
        cfg = ClientConfig(model_backend="mc", mc_odps_entry=object())
        with patch.dict(
            os.environ,
            {
                "MC_OMNI_FALLBACK_MODEL": "qwen3.6-plus",
            },
            clear=False,
        ):
            cfg = ClientConfig.from_env()
            cfg.model_backend = "mc"
            cfg.mc_odps_entry = object()
            with (
                patch(
                    "oms_multimodal.mc.runtime.require_maxframe",
                    side_effect=ConfigurationError(
                        "MODEL_BACKEND=mc requires optional deps: "
                        "pip install 'oms-multimodal-sdk[mc]'"
                    ),
                ),
                self.assertRaises(ConfigurationError) as ctx,
            ):
                create_omni_client(backend="mc", config=cfg)
        self.assertIn("oms-multimodal-sdk[mc]", str(ctx.exception))

    def test_mc_omni_without_fallback_uses_omni_model(self) -> None:
        """Omni 已上架：无 fallback 时直接用 omni_model catalog 名。"""
        cfg = ClientConfig(
            model_backend="mc",
            omni_model="qwen3.5-omni-plus",
            mc_odps_entry=object(),
        )
        with patch("oms_multimodal.model_factory.create_mc_runtime") as mock_rt:
            mock_rt.return_value.config = McBackendConfig(odps_entry=object())
            with patch("oms_multimodal.mc.omni_client.require_maxframe"):
                client = create_omni_client(backend="mc", config=cfg)
        self.assertEqual(type(client).__name__, "McOmniLabelClient")
        self.assertEqual(client.model, "qwen3.5-omni-plus")

    def test_mc_omni_with_fallback_prefers_fallback(self) -> None:
        cfg = ClientConfig(
            model_backend="mc",
            omni_model="qwen3.5-omni-plus",
            mc_odps_entry=object(),
        )
        with patch("oms_multimodal.model_factory.create_mc_runtime") as mock_rt:
            mock_rt.return_value.config = McBackendConfig(
                odps_entry=object(),
                omni_fallback_model="qwen3.6-plus",
            )
            with patch("oms_multimodal.mc.omni_client.require_maxframe"):
                client = create_omni_client(backend="mc", config=cfg)
        self.assertEqual(client.model, "qwen3.6-plus")


class TestOmsMultimodalClientMcBackend(unittest.TestCase):
    def test_make_run_context_uses_client_work_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run"
            work_dir = run_dir / "custom-work"
            client = OmsMultimodalClient(work_dir=work_dir, load_dotenv=False)

            ctx = client.make_run_context(
                run_dir,
                media_mode="local",
                clip_id="sha256:abc",
                run_id="run-1",
            )

        self.assertEqual(ctx.run_dir, run_dir)
        self.assertEqual(ctx.work_dir, work_dir)
        self.assertEqual(ctx.clip_id, "sha256:abc")
        self.assertEqual(ctx.run_id, "run-1")
        self.assertEqual(ctx.media_mode, "local")

    def test_mc_backend_uses_factories_with_one_shared_runtime(self) -> None:
        runtime = Mock()
        asr_client = object()
        omni_client = object()
        embedding_client = object()
        cfg = ClientConfig(
            model_backend="mc",
            asr_config=AsrConfig(enabled=True),
            mc_odps_entry=object(),
        )
        with (
            patch("oms_multimodal.client.create_mc_runtime", return_value=runtime) as create_runtime,
            patch("oms_multimodal.client.create_asr_client", return_value=asr_client) as create_asr,
            patch("oms_multimodal.client.create_omni_client", return_value=omni_client) as create_omni,
            patch(
                "oms_multimodal.client.create_embedding_client",
                return_value=embedding_client,
            ) as create_embedding,
        ):
            client = OmsMultimodalClient(config=cfg, load_dotenv=False)

            self.assertIs(client._get_asr_client(), asr_client)
            self.assertIs(client._get_omni_client(), omni_client)
            self.assertIs(client._get_embedding_client(), embedding_client)
            create_runtime.assert_called_once()
            self.assertIs(create_asr.call_args.kwargs["mc_runtime"], runtime)
            self.assertIs(create_omni.call_args.kwargs["mc_runtime"], runtime)
            self.assertIs(create_embedding.call_args.kwargs["mc_runtime"], runtime)

    def test_close_is_callable_and_idempotently_destroys_mc_runtime(self) -> None:
        runtime = Mock()
        cfg = ClientConfig(model_backend="mc", mc_odps_entry=object())
        with patch("oms_multimodal.client.create_mc_runtime", return_value=runtime):
            client = OmsMultimodalClient(config=cfg, load_dotenv=False)
            self.assertTrue(callable(client.close))
            client._get_embedding_client()

            client.close()
            client.close()

        runtime.destroy.assert_called_once_with()


class TestMcRuntimeHelpers(unittest.TestCase):
    def test_is_omni_model_name(self) -> None:
        self.assertTrue(is_omni_model_name("qwen3.5-omni-plus"))
        self.assertFalse(is_omni_model_name("qwen3.6-plus"))

    def test_resolve_odps_entry_explicit(self) -> None:
        sentinel = object()
        self.assertIs(resolve_odps_entry(sentinel), sentinel)


if __name__ == "__main__":
    unittest.main()
