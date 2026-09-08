"""Runtime kernel: op_id plugins + DAG execute with SDK stubs."""

from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "hmi" / "backend"))
sys.path.insert(0, str(REPO / "shared"))


def _label_ok(node, ctx):
    if node.get("op_id") == "label":
        return {"labels": {"values": {"x": 1}}, "labels_tree": {"values": {"x": 1}}}
    return {}


def _write_sine_wav(path: Path, *, fs: int = 8000, duration_s: float = 0.4) -> None:
    n = int(fs * duration_s)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(fs)
        frames = bytearray()
        for i in range(n):
            sample = int(16000 * math.sin(2 * math.pi * 440.0 * i / fs))
            frames.extend(struct.pack("<h", sample))
        w.writeframes(bytes(frames))


class TestCapabilityKernel(unittest.TestCase):
    def test_catalog_ops_are_registered(self) -> None:
        from hmi.platform.capability_kernel import plugin_for
        from hmi.platform.operators import CATALOG

        for op_id in CATALOG:
            self.assertIsNotNone(plugin_for(op_id), op_id)

    def test_asr_ctx_patch_averages_confidence(self) -> None:
        from hmi.platform.capability_sdk import asr_ctx_patch

        root = Path(tempfile.mkdtemp())
        (root / "asr.jsonl").write_text(
            json.dumps({"clip_id": "a", "text": "hi", "confidence": 0.8})
            + "\n"
            + json.dumps({"clip_id": "b", "text": "there", "avg_confidence": 0.4})
            + "\n",
            encoding="utf-8",
        )
        patch = asr_ctx_patch(root)
        self.assertAlmostEqual(patch["asr"]["avg_confidence"], 0.6)
        self.assertIn("hi", patch["asr"]["text"])

    def test_execute_graph_asr_if_uses_ctx_from_transcribe(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        g = validate_graph(
            {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "s",
                        "params": {"required": True, "kinds": ["audio"]},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "asr",
                        "type": "op",
                        "op_id": "transcribe",
                        "title": "ASR",
                        "params": {},
                        "position": {"x": 0, "y": 80},
                    },
                    {
                        "key": "iff",
                        "type": "if",
                        "title": "if",
                        "params": {},
                        "condition": {
                            "all": [{"field": "asr.avg_confidence", "op": "gte", "value": 0.5}]
                        },
                        "position": {"x": 0, "y": 160},
                    },
                    {
                        "key": "lab",
                        "type": "label",
                        "op_id": "label",
                        "title": "打标",
                        "params": {},
                        "position": {"x": 0, "y": 240},
                    },
                    {
                        "key": "skip",
                        "type": "op",
                        "op_id": "embed",
                        "title": "向量",
                        "params": {},
                        "position": {"x": 160, "y": 240},
                    },
                ],
                "edges": [
                    {"id": "a", "source": "src", "source_port": "out", "target": "asr", "target_port": "in"},
                    {"id": "b", "source": "asr", "source_port": "out", "target": "iff", "target_port": "in"},
                    {"id": "c", "source": "iff", "source_port": "then", "target": "lab", "target_port": "in"},
                    {"id": "d", "source": "iff", "source_port": "else", "target": "skip", "target_port": "in"},
                ],
            }
        )
        called: list[str] = []

        def sdk_runner(node, ctx):
            called.append(str(node.get("op_id")))
            if node.get("op_id") == "transcribe":
                return {"asr": {"avg_confidence": 0.9, "text": "ok", "row_count": 1}}
            if node.get("op_id") == "label":
                return {"labels": {"values": {"x": 1}}, "labels_tree": {"values": {"x": 1}}}
            if node.get("op_id") == "embed":
                return {"embeddings": {"row_count": 1}}
            return {}

        out = execute_recipe_graph(g, ctx0={"source": {"kind": "audio"}}, sdk_runner=sdk_runner)
        self.assertEqual(called, ["transcribe", "label"])
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["lab"], "success")
        self.assertEqual(statuses["skip"], "skipped")
        self.assertEqual(out["ctx"]["asr"]["avg_confidence"], 0.9)

    def test_unimplemented_local_capability_fails(self) -> None:
        from unittest.mock import patch

        from hmi.platform import capability_kernel as ck

        extra = {"ghost_local_op": {"backend": "local", "writes": []}}
        with patch.dict(ck.OP_PLUGINS, extra, clear=False):
            adapters = ck.build_adapters(sdk_runner=lambda n, c: {})
            with self.assertRaises(RuntimeError) as ctx:
                adapters["ghost_local_op"]({"key": "g", "op_id": "ghost_local_op"}, {})
            self.assertIn("capability 未实现: ghost_local_op", str(ctx.exception))

    def test_text_to_json_generic_json_from_manifest(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        root = Path(tempfile.mkdtemp())
        src = root / "source"
        run_dir = root / "run"
        src.mkdir()
        run_dir.mkdir()
        payload = {"scene": {"name": "highway"}, "n": 3}
        (src / "payload.json").write_text(json.dumps(payload), encoding="utf-8")
        man_path = src / "source_manifest.json"
        man_path.write_text(
            json.dumps({"text": "payload.json", "text_path": "payload.json"}),
            encoding="utf-8",
        )
        g = validate_graph(
            {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "s",
                        "params": {"required": True, "kinds": [".json"]},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "t2j",
                        "type": "op",
                        "op_id": "text_to_json",
                        "title": "结构化",
                        "params": {"schema_id": "generic_json"},
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
                "edges": [
                    {"id": "a", "source": "src", "source_port": "out", "target": "t2j", "target_port": "in"},
                    {"id": "b", "source": "t2j", "source_port": "out", "target": "lab", "target_port": "in"},
                ],
            }
        )
        out = execute_recipe_graph(
            g,
            ctx0={
                "run_dir": str(run_dir),
                "source_manifest_path": str(man_path),
                "source": {"kind": ".json"},
            },
            sdk_runner=_label_ok,
        )
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["t2j"], "success")
        self.assertEqual(out["ctx"]["structured_json"]["n"], 3)
        self.assertEqual(out["ctx"]["structured_json"]["scene"]["name"], "highway")
        written = json.loads((run_dir / "structured.json").read_text(encoding="utf-8"))
        self.assertEqual(written["n"], 3)

    def test_text_to_json_generic_text_wraps_raw(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        root = Path(tempfile.mkdtemp())
        src = root / "source"
        run_dir = root / "run"
        src.mkdir()
        run_dir.mkdir()
        (src / "note.txt").write_text("hello cabin", encoding="utf-8")
        man_path = src / "source_manifest.json"
        man_path.write_text(
            json.dumps({"text": "note.txt", "text_path": "note.txt"}),
            encoding="utf-8",
        )
        g = validate_graph(
            {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "s",
                        "params": {"required": True, "kinds": [".txt"]},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "t2j",
                        "type": "op",
                        "op_id": "text_to_json",
                        "title": "结构化",
                        "params": {"schema_id": "generic_text"},
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
                "edges": [
                    {"id": "a", "source": "src", "source_port": "out", "target": "t2j", "target_port": "in"},
                    {"id": "b", "source": "t2j", "source_port": "out", "target": "lab", "target_port": "in"},
                ],
            }
        )
        out = execute_recipe_graph(
            g,
            ctx0={
                "run_dir": str(run_dir),
                "source_manifest_path": str(man_path),
                "source": {"kind": ".txt"},
            },
            sdk_runner=_label_ok,
        )
        self.assertEqual(out["ctx"]["structured_json"], {"raw": "hello cabin"})

    def test_text_to_json_invalid_json_fails(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        root = Path(tempfile.mkdtemp())
        src = root / "source"
        src.mkdir()
        (src / "bad.json").write_text("not json {", encoding="utf-8")
        man_path = src / "source_manifest.json"
        man_path.write_text(
            json.dumps({"text": "bad.json", "text_path": "bad.json"}),
            encoding="utf-8",
        )
        g = validate_graph(
            {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "s",
                        "params": {"required": True, "kinds": [".json"]},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "t2j",
                        "type": "op",
                        "op_id": "text_to_json",
                        "title": "结构化",
                        "params": {"schema_id": "generic_json"},
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
                "edges": [
                    {"id": "a", "source": "src", "source_port": "out", "target": "t2j", "target_port": "in"},
                    {"id": "b", "source": "t2j", "source_port": "out", "target": "lab", "target_port": "in"},
                ],
            }
        )
        with self.assertRaises(RuntimeError) as err:
            execute_recipe_graph(
                g,
                ctx0={
                    "source_manifest_path": str(man_path),
                    "source": {"kind": ".json"},
                },
                sdk_runner=_label_ok,
            )
        self.assertRegex(str(err.exception), r"JSON|解析")

    def test_text_to_json_unknown_schema_fails(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        root = Path(tempfile.mkdtemp())
        src = root / "source"
        src.mkdir()
        (src / "payload.json").write_text("{}", encoding="utf-8")
        man_path = src / "source_manifest.json"
        man_path.write_text(
            json.dumps({"text": "payload.json", "text_path": "payload.json"}),
            encoding="utf-8",
        )
        g = validate_graph(
            {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "s",
                        "params": {"required": True, "kinds": [".json"]},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "t2j",
                        "type": "op",
                        "op_id": "text_to_json",
                        "title": "结构化",
                        "params": {"schema_id": "nope"},
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
                "edges": [
                    {"id": "a", "source": "src", "source_port": "out", "target": "t2j", "target_port": "in"},
                    {"id": "b", "source": "t2j", "source_port": "out", "target": "lab", "target_port": "in"},
                ],
            }
        )
        with self.assertRaises(RuntimeError) as err:
            execute_recipe_graph(
                g,
                ctx0={
                    "source_manifest_path": str(man_path),
                    "source": {"kind": ".json"},
                },
                sdk_runner=_label_ok,
            )
        self.assertIn("schema", str(err.exception).lower())

    def test_text_to_json_feeds_json_extract(self) -> None:
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe_graph import validate_graph

        root = Path(tempfile.mkdtemp())
        src = root / "source"
        src.mkdir()
        (src / "payload.json").write_text(
            json.dumps({"scene": {"name": "highway"}}),
            encoding="utf-8",
        )
        man_path = src / "source_manifest.json"
        man_path.write_text(
            json.dumps({"text": "payload.json", "text_path": "payload.json"}),
            encoding="utf-8",
        )
        g = validate_graph(
            {
                "nodes": [
                    {
                        "key": "src",
                        "type": "source",
                        "op_id": "source",
                        "title": "s",
                        "params": {"required": True, "kinds": [".json"]},
                        "position": {"x": 0, "y": 0},
                    },
                    {
                        "key": "t2j",
                        "type": "op",
                        "op_id": "text_to_json",
                        "title": "结构化",
                        "params": {"schema_id": "generic_json"},
                        "position": {"x": 0, "y": 80},
                    },
                    {
                        "key": "ext",
                        "type": "op",
                        "op_id": "json_extract",
                        "title": "提取",
                        "params": {"path_keys": ["scene", "name"]},
                        "position": {"x": 0, "y": 160},
                    },
                    {
                        "key": "lab",
                        "type": "label",
                        "op_id": "label",
                        "title": "打标",
                        "params": {},
                        "position": {"x": 0, "y": 240},
                    },
                ],
                "edges": [
                    {"id": "a", "source": "src", "source_port": "out", "target": "t2j", "target_port": "in"},
                    {"id": "b", "source": "t2j", "source_port": "out", "target": "ext", "target_port": "in"},
                    {"id": "c", "source": "ext", "source_port": "out", "target": "lab", "target_port": "in"},
                ],
            }
        )
        out = execute_recipe_graph(
            g,
            ctx0={
                "source_manifest_path": str(man_path),
                "source": {"kind": ".json"},
            },
            sdk_runner=_label_ok,
        )
        self.assertEqual(out["ctx"]["json_extract"]["value"], "highway")

    def test_audio_array_seed_graph_runs_on_kernel(self) -> None:
        """Array recipe graph must execute local NVH plugins (not dedicated worker bypass)."""
        import numpy as np
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.capability_sdk import run_sdk_node
        from hmi.platform.recipe import seed_recipes
        from hmi.platform.recipe_graph import validate_graph

        rec = seed_recipes()["audio_array_spec"]
        graph = validate_graph(rec["graph"])
        for node in graph["nodes"]:
            if node.get("op_id") == "label":
                params = dict(node.get("params") or {})
                params["model"] = "nvh_sem_heuristic"
                node["params"] = params

        root = Path(tempfile.mkdtemp())
        src = root / "source"
        run_dir = root / "run"
        src.mkdir()
        run_dir.mkdir()
        fs = 8000.0
        n = int(fs * 0.4)
        t = np.arange(n, dtype=np.float64) / fs
        pcm = np.stack(
            [0.02 * np.sin(2 * np.pi * 440 * t + i * 0.1) for i in range(4)],
            axis=1,
        ).astype(np.float32)
        np.save(src / "pcm_pa.npy", pcm)
        (src / "head_meta.json").write_text(
            json.dumps(
                {
                    "format": "head_acoustics_hdf_v4",
                    "fs_hz": fs,
                    "duration_s": n / fs,
                    "n_channels": 4,
                    "unit": "Pa",
                    "channels": [
                        {"name": "VL", "map_factor": 1.0},
                        {"name": "VR", "map_factor": 1.0},
                        {"name": "HL", "map_factor": 1.0},
                        {"name": "HR", "map_factor": 1.0},
                    ],
                }
            ),
            encoding="utf-8",
        )
        man = {
            "audio": str(src / "pcm_pa.npy"),
            "sources_by_kind": {"audio": "src-audio-1"},
            "source_ids": ["src-audio-1"],
        }
        man_path = src / "source_manifest.json"
        man_path.write_text(json.dumps(man), encoding="utf-8")

        recipe = dict(rec)
        stages = dict(recipe.get("stages") or {})
        stages["label"] = {"enabled": True, "model": "nvh_sem_heuristic"}
        recipe["stages"] = stages

        def sdk_runner(node, ctx):
            return run_sdk_node(
                node,
                ctx,
                run_dir=run_dir,
                bag_path=None,
                client=None,
                clip_config=None,
                recipe=recipe,
            )

        out = execute_recipe_graph(
            graph,
            ctx0={
                "clip_id": "clip-array",
                "run_id": "run-array",
                "run_dir": str(run_dir),
                "source_manifest_path": str(man_path),
                "source": {"kind": ".dat", "slot_id": "audio_primary"},
            },
            sdk_runner=sdk_runner,
        )
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses["parse_head_dat"], "success")
        self.assertEqual(statuses["stft_spectrogram"], "success")
        self.assertEqual(statuses["mel_spectrogram"], "success")
        self.assertEqual(statuses["third_octave"], "success")
        self.assertEqual(statuses["spl_timeline"], "success")
        self.assertEqual(statuses["stage-label"], "success")
        self.assertTrue((run_dir / "pcm_pa.npy").is_file())
        self.assertTrue((run_dir / "audio_spec" / "VL" / "mel.png").is_file())
        self.assertTrue((run_dir / "audio_spec" / "VL" / "stft.png").is_file())
        self.assertTrue((run_dir / "audio_spec" / "VL" / "third_octave.json").is_file())
        self.assertTrue((run_dir / "audio_spec" / "VL" / "spl_timeline.jsonl").is_file())
        self.assertTrue((run_dir / "nvh_labels.json").is_file())
        self.assertIn("pcm_pa_wavs", out["ctx"])
        self.assertIn("mel_matrix", out["ctx"])

    def test_audio_defect_seed_graph_runs_on_relative_wav(self) -> None:
        """Lake wav packages use audio.wav + relative manifest; mel/spl must not require HEAD .dat."""
        from hmi.platform.capability_kernel import execute_recipe_graph
        from hmi.platform.recipe import seed_recipes
        from hmi.platform.recipe_graph import validate_graph

        rec = seed_recipes()["audio_defect"]
        graph = validate_graph(rec["graph"])
        mel_key = next(n["key"] for n in graph["nodes"] if n.get("op_id") == "mel_spectrogram")
        spl_key = next(n["key"] for n in graph["nodes"] if n.get("op_id") == "spl_timeline")
        wav_slot = next(
            n["key"]
            for n in graph["nodes"]
            if n.get("type") == "source" and ".wav" in (n.get("params") or {}).get("kinds", [])
        )

        root = Path(tempfile.mkdtemp())
        src = root / "source"
        run_dir = root / "run"
        src.mkdir()
        run_dir.mkdir()
        _write_sine_wav(src / "audio.wav")
        man_path = src / "source_manifest.json"
        man_path.write_text(
            json.dumps({"audio": "audio.wav", "sources_by_kind": {"audio": "src-wav-1"}}),
            encoding="utf-8",
        )

        out = execute_recipe_graph(
            graph,
            ctx0={
                "clip_id": "clip-wav",
                "run_id": "run-wav",
                "run_dir": str(run_dir),
                "source_manifest_path": str(man_path),
                "source": {"kind": ".wav", "slot_id": wav_slot},
            },
            sdk_runner=_label_ok,
        )
        statuses = {r["key"]: r["status"] for r in out["run"]}
        self.assertEqual(statuses[mel_key], "success", out["run"])
        self.assertEqual(statuses[spl_key], "success", out["run"])
        spec = run_dir / "audio_spec"
        ch_dirs = [p for p in spec.iterdir() if p.is_dir()] if spec.is_dir() else []
        self.assertTrue(ch_dirs, "expected per-channel audio_spec")
        self.assertTrue((ch_dirs[0] / "mel.png").is_file())
        self.assertTrue((ch_dirs[0] / "spl_timeline.jsonl").is_file())
        self.assertIn("mel_matrix", out["ctx"])
        self.assertIn("spl_jsonl", out["ctx"])


if __name__ == "__main__":
    unittest.main()
