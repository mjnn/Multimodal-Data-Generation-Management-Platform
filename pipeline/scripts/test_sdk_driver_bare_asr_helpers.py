from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "pipeline" / "dataworks"))

from sdk_driver_bare_asr import (  # noqa: E402
    attach_asr_text_to_pack_rows,
    clip_id_from_audio_key,
    parse_audio_keys_json,
    select_canonical_asr_audio_keys,
)


class TestAsrAudioKeyHelpers(unittest.TestCase):
    def test_clip_id_prefers_innermost_sdk_subclip(self) -> None:
        key = (
            "clips/sha256:abc123/runs/rid/_sdk_work/output/clips/output_0000/audio.wav"
        )
        self.assertEqual(clip_id_from_audio_key(key), "output_0000")

    def test_clip_id_preview_under_oss_prefix(self) -> None:
        key = "clips/sha256:abc123/runs/rid/preview/audio.wav"
        # No .../clips/<sdk>/audio.wav tail → last /clips/ segment is bag id.
        self.assertEqual(clip_id_from_audio_key(key), "sha256:abc123")

    def test_select_prefers_work_clips_over_preview(self) -> None:
        keys = [
            "clips/sha256:abc/runs/r1/preview/audio.wav",
            "clips/sha256:abc/runs/r1/_sdk_work/output/clips/output_0000/audio.wav",
        ]
        chosen = select_canonical_asr_audio_keys(keys)
        self.assertEqual(len(chosen), 1)
        self.assertTrue(chosen[0].endswith("clips/output_0000/audio.wav"))
        self.assertIn("/_sdk_work/", chosen[0])

    def test_parse_audio_keys_json_dedupes(self) -> None:
        raw = (
            '["clips/sha256:x/runs/r/_sdk_work/output/clips/output_0000/audio.wav",'
            '"clips/sha256:x/runs/r/preview/audio.wav"]'
        )
        self.assertEqual(len(parse_audio_keys_json(raw)), 1)

    def test_attach_asr_by_sdk_clip_id(self) -> None:
        packs = [
            {
                "clip_id": "sha256:bag",
                "sdk_clip_id": "output_0000",
                "asr_text": "",
            }
        ]
        asr_rows = [
            {
                "clip_id": "sha256:bag",
                "sdk_clip_id": "output_0000",
                "text": "hello asr",
                "model": "qwen3-asr-flash",
            }
        ]
        out = attach_asr_text_to_pack_rows(packs, asr_rows, bag_clip_id="sha256:bag")
        self.assertEqual(out[0]["asr_text"], "hello asr")
        self.assertEqual(out[0]["asr_model"], "qwen3-asr-flash")

    def test_attach_asr_single_row_fallback(self) -> None:
        packs = [{"clip_id": "sha256:bag", "sdk_clip_id": "output_0000", "asr_text": ""}]
        asr_rows = [{"clip_id": "mismatched", "text": "only one"}]
        out = attach_asr_text_to_pack_rows(packs, asr_rows, bag_clip_id="sha256:bag")
        self.assertEqual(out[0]["asr_text"], "only one")


if __name__ == "__main__":
    unittest.main()
