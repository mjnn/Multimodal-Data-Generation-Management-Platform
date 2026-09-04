"""Tests for LLM_PROVIDER / AIGW settings resolution."""

from __future__ import annotations

import os
import unittest
from unittest import mock


class TestLlmProvider(unittest.TestCase):
    def tearDown(self) -> None:
        for key in list(os.environ):
            if key.startswith(("LLM_", "OMNI_", "ASR_", "EMBEDDING_", "AIGW_")):
                os.environ.pop(key, None)

    def test_default_dashscope(self) -> None:
        from oms_multimodal.llm_provider import resolve_llm_provider

        self.assertEqual(resolve_llm_provider("omni"), "dashscope")

    def test_global_aigw(self) -> None:
        from oms_multimodal.llm_provider import resolve_llm_provider

        os.environ["LLM_PROVIDER"] = "aigw"
        self.assertEqual(resolve_llm_provider("omni"), "aigw")
        self.assertEqual(resolve_llm_provider("asr"), "aigw")
        self.assertEqual(resolve_llm_provider("embedding"), "aigw")

    def test_per_capability_override(self) -> None:
        from oms_multimodal.llm_provider import resolve_llm_provider

        os.environ["LLM_PROVIDER"] = "aigw"
        os.environ["ASR_PROVIDER"] = "dashscope"
        self.assertEqual(resolve_llm_provider("omni"), "aigw")
        self.assertEqual(resolve_llm_provider("asr"), "dashscope")

    def test_load_aigw_settings_requires_url_key(self) -> None:
        from oms_multimodal.llm_provider import load_aigw_settings

        with self.assertRaises(RuntimeError):
            load_aigw_settings()
        os.environ["AIGW_BASE_URL"] = "https://ali.aigw.csvw.com/model/ark/llm/master-agent/v1"
        with self.assertRaises(RuntimeError):
            load_aigw_settings()
        os.environ["AIGW_API_KEY"] = "tok"
        os.environ["AIGW_MODEL"] = "ep-test"
        s = load_aigw_settings()
        self.assertTrue(s.base_url.endswith("/v1"))
        self.assertEqual(s.omni_model, "ep-test")
        self.assertEqual(s.asr_model, "ep-test")
        self.assertFalse(s.omni_stream)

    def test_omni_client_aigw_skips_workspace(self) -> None:
        from oms_multimodal.omni_client import OmniLabelClient

        os.environ["LLM_PROVIDER"] = "aigw"
        os.environ["AIGW_BASE_URL"] = "https://example.invalid/v1"
        os.environ["AIGW_API_KEY"] = "tok"
        os.environ["AIGW_OMNI_MODEL"] = "ep-omni"
        with mock.patch("oms_multimodal.omni_client.make_openai_client") as make:
            make.return_value = mock.Mock()
            client = OmniLabelClient(provider="aigw")
        self.assertEqual(client.provider, "aigw")
        self.assertEqual(client.model, "ep-omni")
        self.assertFalse(client._stream)
        make.assert_called_once()


if __name__ == "__main__":
    unittest.main()
