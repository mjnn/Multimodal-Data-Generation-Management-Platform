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
from oms_multimodal.mc.content_parts import (
    file_base64,
    mc_native_media_enabled,
    pick_preview_video_path,
    populate_media_columns,
    resolve_omni_mc_mode,
    speech_context_without_asr,
)
from oms_multimodal.mc.config import McBackendConfig
from oms_multimodal.mc.runtime import (
    is_omni_model_name,
    normalize_catalog_endpoint,
    resolve_mc_catalog_endpoint,
    resolve_odps_entry,
)
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


class TestMcContentParts(unittest.TestCase):
    def test_mc_native_media_enabled_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MC_OMNI_NATIVE_MEDIA", None)
            self.assertTrue(mc_native_media_enabled())

    def test_mc_native_media_disabled(self) -> None:
        with patch.dict(os.environ, {"MC_OMNI_NATIVE_MEDIA": "false"}, clear=False):
            self.assertFalse(mc_native_media_enabled())

    def test_populate_media_columns_base64(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(b"RIFF")
            wav_path = tmp.name
        try:
            cfg = McBackendConfig(image_mode="base64")
            row: dict[str, str] = {}
            populate_media_columns(row, config=cfg, local_path=wav_path, column_prefix="audio")
            self.assertIn("audio_b64", row)
            self.assertEqual(row["audio_b64"], file_base64(wav_path))
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def test_speech_context_without_asr_skips_asr(self) -> None:
        clip = Mock()
        clip.fusion_text.return_value = "event-a"
        clip.mel_feature_text = "mel-panel"
        clip.asr_text = "should-not-appear"
        text = speech_context_without_asr(clip)
        self.assertIn("event-a", text)
        self.assertIn("mel-panel", text)
        self.assertNotIn("should-not-appear", text)

    def test_resolve_omni_mc_mode_native_video(self) -> None:
        clip = Mock()
        clip.clip_video_path = "/tmp/preview.mp4"
        clip.clip_video_paths = {}
        clip.audio = None
        with patch("oms_multimodal.mc.content_parts.Path.is_file", return_value=True):
            mode = resolve_omni_mc_mode(
                omni_model="qwen3.5-omni-plus",
                effective_model="qwen3.5-omni-plus",
                clip=clip,
                use_native_media=True,
            )
        self.assertEqual(mode, "omni_native")

    def test_resolve_omni_mc_mode_vl_fallback(self) -> None:
        clip = Mock()
        clip.clip_video_path = None
        clip.clip_video_paths = {}
        clip.audio = None
        clip.frames = []
        mode = resolve_omni_mc_mode(
            omni_model="qwen3.5-omni-plus",
            effective_model="qwen3.6-plus",
            clip=clip,
            use_native_media=True,
        )
        self.assertEqual(mode, "vl_fallback")


class TestMcRuntimeHelpers(unittest.TestCase):
    def test_is_omni_model_name(self) -> None:
        self.assertTrue(is_omni_model_name("qwen3.5-omni-plus"))
        self.assertFalse(is_omni_model_name("qwen3.6-plus"))

    def test_resolve_odps_entry_explicit(self) -> None:
        sentinel = object()
        self.assertIs(resolve_odps_entry(sentinel), sentinel)

    def test_normalize_catalog_endpoint_internal(self) -> None:
        url = normalize_catalog_endpoint("https://catalogapi.cn-shanghai.maxcompute.aliyun.com")
        self.assertIn("aliyun-inc.com", url)
        self.assertNotIn(".aliyun.com", url.replace(".aliyun-inc.com", ""))

    def test_resolve_mc_catalog_endpoint_default_internal(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            url = resolve_mc_catalog_endpoint(cloud_region="cn_shanghai")
        self.assertEqual(url, "https://catalogapi.cn-shanghai.maxcompute.aliyun-inc.com")

    def test_resolve_mc_catalog_endpoint_explicit(self) -> None:
        url = resolve_mc_catalog_endpoint(
            explicit="http://catalogapi.cn-beijing.maxcompute.aliyun.com"
        )
        self.assertEqual(url, "http://catalogapi.cn-beijing.maxcompute.aliyun-inc.com")


if __name__ == "__main__":
    unittest.main()
