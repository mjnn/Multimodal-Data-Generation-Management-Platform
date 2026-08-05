#!/usr/bin/env python3
"""M9.3 — unit tests for verify_sdk_v1_run validators (no cloud)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PIPELINE_ROOT = REPO_ROOT / "pipeline"
HMI_BACKEND = REPO_ROOT / "hmi" / "backend"
PIPELINE_SCRIPTS = PIPELINE_ROOT / "scripts"
for _p in (REPO_ROOT / "shared", PIPELINE_ROOT, PIPELINE_SCRIPTS, HMI_BACKEND):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from verify_sdk_v1_run import (  # noqa: E402
    expected_sdk_steps,
    sdk_required_oss_files,
    validate_dispatch_manifest,
    validate_jsonl_row,
    validate_run_json,
    verify_local_artifacts,
)


class TestSdkV1Validators(unittest.TestCase):
    def test_expected_sdk_steps(self) -> None:
        steps = expected_sdk_steps()
        self.assertIn("sdk_infer", steps)
        self.assertIn("sdk_dispatch", steps)
        self.assertEqual(steps[0], "sdk_discover")

    test_run_json_valid = lambda self: self.assertEqual(
        validate_run_json(
            {
                "layout_version": "sdk_v1",
                "clip_id": "sha256:abc",
                "run_id": "run-1",
                "sdk_files": {"labels": "labels.jsonl"},
            },
            clip_id="sha256:abc",
            run_id="run-1",
        ),
        [],
    )

    def test_run_json_invalid_layout(self) -> None:
        errs = validate_run_json({"layout_version": "v2"}, clip_id="c", run_id="r")
        self.assertTrue(any("layout_version" in e for e in errs))

    def test_dispatch_manifest(self) -> None:
        errs = validate_dispatch_manifest(
            {
                "layout_version": "sdk_v1",
                "clip_id": "sha256:x",
                "run_id": "uuid",
                "run_oss_prefix": "clips/sha256:x/runs/uuid/",
            },
            clip_id="sha256:x",
            run_id="uuid",
        )
        self.assertEqual(errs, [])

    def test_validate_jsonl_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "labels.jsonl"
            path.write_text(json.dumps({"clip_id": "c", "labels": {}}) + "\n", encoding="utf-8")
            self.assertEqual(validate_jsonl_row(path, require_keys=("clip_id", "labels")), [])

    def test_verify_local_artifacts_minimal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "run.json").write_text(
                json.dumps(
                    {
                        "layout_version": "sdk_v1",
                        "clip_id": "sha256:t",
                        "run_id": "r1",
                        "sdk_files": {},
                    }
                ),
                encoding="utf-8",
            )
            (root / "labels.jsonl").write_text(
                json.dumps({"clip_id": "sha256:t", "labels": {"a": 1}}) + "\n",
                encoding="utf-8",
            )
            (root / "fusion_embeddings.jsonl").write_text(
                json.dumps({"clip_id": "sha256:t", "embedding": [0.1, 0.2]}) + "\n",
                encoding="utf-8",
            )
            (root / "clip_videos.jsonl").write_text(
                json.dumps({"clip_id": "sha256:t"}) + "\n",
                encoding="utf-8",
            )
            preview = root / "preview"
            preview.mkdir()
            (preview / "clip_preview_camera0.mp4").write_bytes(b"\x00")
            (preview / "audio.wav").write_bytes(b"RIFF")

            checks = verify_local_artifacts(root, clip_id="sha256:t", run_id="r1")
            failed = [c for c in checks if not c.ok]
            self.assertEqual(failed, [], msg=str(failed))

    def test_sdk_required_oss_files(self) -> None:
        files = sdk_required_oss_files()
        self.assertIn("labels.jsonl", files)
        self.assertIn("preview/audio.wav", files)


if __name__ == "__main__":
    unittest.main()
