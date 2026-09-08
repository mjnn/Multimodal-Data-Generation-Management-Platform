"""channel_count expands catalog template ports into ch1..chN."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


class TestExpandOutputPorts(unittest.TestCase):
    def test_no_expand_returns_template(self) -> None:
        from hmi.platform.recipe_pipeline import expand_output_ports

        op = {"output_ports": [{"id": "out", "types": ["asr_jsonl"], "title": "转写"}]}
        ports = expand_output_ports(op, {"channel_count": 4})
        self.assertEqual([p["id"] for p in ports], ["out"])

    def test_channel_count_four_named(self) -> None:
        from hmi.platform.recipe_pipeline import expand_output_ports

        op = {
            "expand_outputs_from": "channel_count",
            "output_ports": [{"id": "out", "types": ["mel_matrix"], "title": "梅尔频谱"}],
        }
        ports = expand_output_ports(
            op,
            {"channel_count": 4, "port_titles": {"ch2": "驾驶位"}},
        )
        self.assertEqual([p["id"] for p in ports], ["ch1", "ch2", "ch3", "ch4"])
        self.assertEqual([p["channel_index"] for p in ports], [0, 1, 2, 3])
        self.assertEqual(ports[0]["types"], ["mel_matrix"])
        self.assertEqual(ports[1]["title"], "驾驶位")
        self.assertIn("梅尔", ports[0]["title"])

    def test_clamp_and_default(self) -> None:
        from hmi.platform.recipe_pipeline import channel_count_from_params

        self.assertEqual(channel_count_from_params(None), 1)
        self.assertEqual(channel_count_from_params({"channel_count": 0}), 1)
        self.assertEqual(channel_count_from_params({"channel_count": 99}), 16)
        self.assertEqual(channel_count_from_params({"channel_count": "3"}), 3)

    def test_allowed_output_ids_uses_expanded_ports(self) -> None:
        from hmi.platform.io_contract import allowed_output_ids
        from hmi.platform.operators import OPERATORS

        self.assertEqual(OPERATORS["mel_spectrogram"].get("expand_outputs_from"), "channel_count")
        node = {
            "op_id": "mel_spectrogram",
            "params": {"channel_count": 2, "port_titles": {"ch1": "FL"}},
        }
        ids = allowed_output_ids(node)
        self.assertIn("ch1", ids)
        self.assertIn("ch2", ids)


if __name__ == "__main__":
    unittest.main()
