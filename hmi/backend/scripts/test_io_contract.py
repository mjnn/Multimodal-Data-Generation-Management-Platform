"""DAG I/O contract: min inputs, closed bindings, producer artifacts, consume flags."""

from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


def _write_sine_wav(path: Path, *, fs: int = 8000, duration_s: float = 0.4) -> None:
    n = int(fs * duration_s)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(fs)
        frames = bytearray()
        for i in range(n):
            sample = int(16000 * math.sin(2 * math.pi * 440.0 * i / fs))
            frames.extend(struct.pack("<h", sample))
        handle.writeframes(bytes(frames))


def _graph(*, parse_mods: list[str] | None = None, label_from: str = "frames", extra_wav_edge: bool = False):
    mods = parse_mods if parse_mods is not None else ["frames", ".wav", ".json"]
    edges = [
        {"id": "s-p", "source": "src", "source_port": "out", "target": "parse", "target_port": "in"},
        {"id": "p-l", "source": "parse", "source_port": label_from, "target": "lab", "target_port": "in"},
    ]
    if extra_wav_edge:
        edges.append(
            {"id": "p-l-wav", "source": "parse", "source_port": ".wav", "target": "lab", "target_port": "in"}
        )
    return {
        "nodes": [
            {
                "key": "src",
                "type": "source",
                "op_id": "source",
                "title": "bag",
                "params": {"required": True, "kinds": [".bag"]},
                "position": {"x": 0, "y": 0},
            },
            {
                "key": "parse",
                "type": "op",
                "op_id": "parse_bag",
                "title": "解析",
                "params": {"emit_modalities": mods},
                "position": {"x": 0, "y": 80},
            },
            {
                "key": "lab",
                "type": "label",
                "op_id": "label",
                "title": "打标",
                "params": {},
                "position": {"x": 0, "y": 160},
            },
        ],
        "edges": edges,
    }


class TestDiagnoseGraph(unittest.TestCase):
    def test_label_without_edges_min_input(self) -> None:
        from hmi.platform.io_contract import diagnose_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(
            {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "s",
                        "params": {"required": False, "kinds": [".bag"]},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "lab",
                        "type": "label",
                        "op_id": "label",
                        "title": "打标",
                        "params": {},
                        "position": {"x": 0, "y": 80},
                    },
                ],
                "edges": [],
            }
        )
        diag = diagnose_graph(g)
        self.assertEqual(diag["lab"]["level"], "warn")
        self.assertIn("min_input", diag["lab"]["codes"])
        self.assertEqual(diag["src"]["level"], "ok")

    def test_label_bound_to_undeclared_wav(self) -> None:
        from hmi.platform.io_contract import diagnose_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames"], label_from=".wav"))
        diag = diagnose_graph(g)
        self.assertEqual(diag["lab"]["level"], "warn")
        self.assertIn("unbound_kind", diag["lab"]["codes"])

    def test_frames_edge_is_ok(self) -> None:
        from hmi.platform.io_contract import diagnose_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(label_from="frames"))
        diag = diagnose_graph(g)
        self.assertEqual(diag["lab"]["level"], "ok")
        self.assertEqual(diag["parse"]["level"], "ok")


class TestConsumeFlags(unittest.TestCase):
    def test_wav_edge_enables_audio(self) -> None:
        from hmi.platform.io_contract import consume_flags
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(label_from="frames", extra_wav_edge=True))
        flags = consume_flags(g["nodes"][2], g)
        self.assertTrue(flags["include_audio"])

    def test_frames_only_disables_audio(self) -> None:
        from hmi.platform.io_contract import consume_flags
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(label_from="frames"))
        flags = consume_flags(g["nodes"][2], g)
        self.assertFalse(flags["include_audio"])

    def test_legacy_out_bundle_includes_wav_when_emitted(self) -> None:
        from hmi.platform.io_contract import consume_flags
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(label_from="out"))
        flags = consume_flags(g["nodes"][2], g)
        self.assertTrue(flags["include_audio"])

    def test_legacy_out_without_wav_emit_disables_audio(self) -> None:
        from hmi.platform.io_contract import consume_flags
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames"], label_from="out"))
        flags = consume_flags(g["nodes"][2], g)
        self.assertFalse(flags["include_audio"])


class TestProducerArtifacts(unittest.TestCase):
    def test_missing_wav_fails_parse_node(self) -> None:
        from hmi.platform.io_contract import missing_produces
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames", ".wav"]))
        parse = next(n for n in g["nodes"] if n["key"] == "parse")
        root = Path(tempfile.mkdtemp())
        (root / "clips_index.jsonl").write_text("{}\n", encoding="utf-8")
        missing = missing_produces(parse, ctx={"run_dir": str(root)})
        self.assertIn(".wav", missing)

    def test_wav_file_satisfies_parse(self) -> None:
        from hmi.platform.io_contract import missing_produces
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames", ".wav"]))
        parse = next(n for n in g["nodes"] if n["key"] == "parse")
        root = Path(tempfile.mkdtemp())
        (root / "clips_index.jsonl").write_text(
            json.dumps({"clip_id": "c", "audio": {"audio_path": str(root / "a.wav")}}) + "\n",
            encoding="utf-8",
        )
        (root / "a.wav").write_bytes(b"RIFF")
        missing = missing_produces(parse, ctx={"run_dir": str(root)})
        self.assertEqual(missing, [])

    def test_ctx_asr_satisfies_transcribe(self) -> None:
        from hmi.platform.io_contract import missing_produces

        node = {
            "key": "asr",
            "type": "op",
            "op_id": "transcribe",
            "params": {},
        }
        missing = missing_produces(node, ctx={"asr": {"text": "hi"}})
        self.assertEqual(missing, [])


class TestExecuteUntil(unittest.TestCase):
    def test_until_parse_skips_label_and_does_not_require_it(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames"], label_from="frames"))
        called: list[str] = []

        def sdk_runner(node, ctx):
            called.append(str(node.get("op_id")))
            if node.get("op_id") == "parse_bag":
                return {"extract": {"clip_rows": 1}}
            raise AssertionError("label should not run")

        out = execute_recipe_graph(
            g,
            ctx0={"run_dir": str(Path(tempfile.mkdtemp()))},
            sdk_runner=sdk_runner,
            until_key="parse",
            require_label=False,
            include_ai=False,
        )
        self.assertEqual(called, ["parse_bag"])
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["parse"], "success")
        self.assertNotIn("lab", statuses)

    def test_include_ai_false_checks_label_without_calling(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames"], label_from="frames"))
        called: list[str] = []

        def sdk_runner(node, ctx):
            called.append(str(node.get("op_id")))
            return {"extract": {"clip_rows": 1}}

        out = execute_recipe_graph(
            g,
            ctx0={},
            sdk_runner=sdk_runner,
            until_key="lab",
            require_label=False,
            include_ai=False,
        )
        self.assertEqual(called, ["parse_bag"])
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["lab"], "checked")


class TestProbeAndProducerFail(unittest.TestCase):
    def test_probe_without_source(self) -> None:
        from hmi.platform.io_probe import probe_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames"], label_from="frames"))
        out = probe_graph(g, until_key="parse", source_ids=[])
        self.assertFalse(out["ok"])
        self.assertIn("需要数据源才能试跑", str(out.get("error") or ""))

    def test_probe_mel_uses_lake_wav_manifest(self) -> None:
        """Inspector 试跑 gets local_path=source_manifest.json; kernel must still find audio.wav."""
        from hmi.platform.io_probe import probe_graph
        from hmi.platform.recipe import seed_recipes
        from hmi.platform.recipe_graph import validate_graph

        src = Path(tempfile.mkdtemp()) / "source"
        src.mkdir()
        _write_sine_wav(src / "audio.wav")
        man_path = src / "source_manifest.json"
        man_path.write_text(
            json.dumps({"audio": "audio.wav", "audio_path": "audio.wav"}),
            encoding="utf-8",
        )
        graph = validate_graph(seed_recipes()["audio_defect"]["graph"])
        mel_key = next(n["key"] for n in graph["nodes"] if n.get("op_id") == "mel_spectrogram")
        fake_src = {
            "source_id": "sha256:probe-wav",
            "kind": ".wav",
            "filename": "audio.wav",
            "local_path": str(man_path),
            "local_oss_key": "",
        }
        with patch("hmi.platform.io_probe.get_source", return_value=fake_src):
            out = probe_graph(graph, until_key=mel_key, source_ids=["sha256:probe-wav"])
        self.assertTrue(out.get("ok"), out)
        self.assertNotIn("缺失", str(out.get("error") or ""))
        self.assertIn("mel_matrix", out.get("produces_found") or [])

    def test_execute_missing_wav_fails_parse_node(self) -> None:
        from hmi.platform.graph_runtime import execute_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(_graph(parse_mods=["frames", ".wav"], label_from="frames"))
        root = Path(tempfile.mkdtemp())
        (root / "clips_index.jsonl").write_text("{}\n", encoding="utf-8")

        def parse_ok(_node, _ctx):
            return {"extract": {"clip_rows": 1}}

        with self.assertRaises(RuntimeError) as ctx:
            execute_graph(
                g,
                ctx0={"run_dir": str(root)},
                adapters={"parse_bag": parse_ok, "label": lambda n, c: {}},
                until_key="parse",
                require_label=False,
            )
        self.assertIn("节点 parse 未按期望输出", str(ctx.exception))
        self.assertIn(".wav", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
