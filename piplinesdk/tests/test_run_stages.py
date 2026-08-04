from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from oms_multimodal.capabilities.run_meta import write_run_json
from oms_multimodal.capabilities.stages import (
    ALL_STAGES,
    DRIVER_STAGES,
    UDF_STAGES,
    parse_stages,
    run_stages,
)
from oms_multimodal.capabilities.types import (
    EmbedResult,
    ExtractResult,
    LabelResult,
    RunContext,
    TranscribeResult,
)


class TestParseStages(unittest.TestCase):
    def test_default_all(self) -> None:
        self.assertEqual(parse_stages(None), ALL_STAGES)
        self.assertEqual(parse_stages(""), ALL_STAGES)

    def test_subset_and_aliases(self) -> None:
        s = parse_stages("extract, asr, LABEL")
        self.assertEqual(s, frozenset({"extract", "asr", "label"}))

    def test_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_stages("extract,nope")


class TestWriteRunJson(unittest.TestCase):
    def test_writes_sdk_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_run_json(
                root,
                clip_id="sha256:abc",
                run_id="run-1",
                ds="20260804",
                bag_oss_key="rosbags/x.bag",
                stages_done=("extract", "upload"),
                model_backend="mc",
            )
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["layout_version"], "sdk_v1")
            self.assertEqual(doc["clip_id"], "sha256:abc")
            self.assertEqual(doc["run_id"], "run-1")
            self.assertIn("labels", doc["sdk_files"])


class TestRunStages(unittest.TestCase):
    def test_skips_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = RunContext(run_dir=Path(tmp), clip_id="c", run_id="r", media_mode="local")
            client = MagicMock()
            bag = Path(tmp) / "out.bag"
            bag.write_bytes(b"x")
            extract = ExtractResult(
                clips_index=ctx.clips_index_path,
                videos_out=ctx.videos_path,
                clip_rows=1,
                video_rows=1,
                bag="out.bag",
                topics=[],
            )
            with (
                patch("oms_multimodal.capabilities.stages.extract_clips", return_value=extract) as ex,
                patch("oms_multimodal.capabilities.stages.transcribe_clips") as tr,
                patch("oms_multimodal.capabilities.stages.materialize_preview") as pr,
                patch("oms_multimodal.capabilities.stages.label_clips") as lb,
                patch("oms_multimodal.capabilities.stages.embed_clips") as em,
                patch("oms_multimodal.capabilities.stages.write_run_json") as wj,
            ):
                result = run_stages(
                    ctx,
                    bag,
                    client,
                    stages=frozenset({"extract"}),
                )
            ex.assert_called_once()
            tr.assert_not_called()
            pr.assert_not_called()
            lb.assert_not_called()
            em.assert_not_called()
            wj.assert_not_called()
            self.assertEqual(result.stages_done, ["extract"])
            self.assertEqual(result.errors, [])

    def test_upload_writes_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ctx = RunContext(run_dir=Path(tmp), clip_id="c", run_id="r", media_mode="local")
            client = MagicMock()
            bag = Path(tmp) / "out.bag"
            bag.write_bytes(b"x")
            with patch("oms_multimodal.capabilities.stages.write_run_json") as wj:
                wj.return_value = Path(tmp) / "run.json"
                result = run_stages(
                    ctx,
                    bag,
                    client,
                    stages=frozenset({"upload"}),
                    bag_oss_key="rosbags/out.bag",
                    ds="20260804",
                    model_backend="mc",
                )
            wj.assert_called_once()
            self.assertIn("upload", result.stages_done)


if __name__ == "__main__":
    unittest.main()
