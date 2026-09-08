#!/usr/bin/env python3
"""本地无 MC：taxonomy 树裁剪 + extract → bbox → encode 冒烟。

不调用 ASR/Label/Embed（不需要 ODPS / DashScope）。适合先调通 SDK 产物。

用法::

    cd pipeline/local_sdk_mc_test
    # .env 至少设 BAG_LOCAL_PATH / RUN_OUT_DIR
    py -3.11 run_local_sdk_smoke.py
    py -3.11 run_local_sdk_smoke.py --skip-extract   # 复用已有 clips_index
    py -3.11 run_local_sdk_smoke.py --detector stub
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
_REPO = HERE.parents[1]
_SDK = _REPO / "piplinesdk"
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))

from sdk_node_common import (  # noqa: E402
    build_sdk_client,
    get_float_arg,
    load_local_env,
    make_run_context,
    require_arg,
    require_run_paths,
)


def _check_taxonomy() -> dict:
    from oms_multimodal import (
        LabelingTaxonomyOptions,
        crop_taxonomy_for_labeling,
        make_enum_tree_schema,
        enum_tree_node,
        minimal_enum_tree_example,
        normalize_tree_value,
        tree_depth,
        validate_enum_tree_schema,
    )

    # Scaffold only — platform authors build real trees; this is the depth API smoke.
    example = minimal_enum_tree_example()
    assert tree_depth(example) == 2
    assert validate_enum_tree_schema(example) == []
    built = make_enum_tree_schema(enum_tree_node("root", "leaf"))
    assert tree_depth(built) == 2

    tax = {
        "labels": [
            {
                "id": "demo.tree",
                "level_code": "L_DEMO",
                "value_schema": example,
            }
        ]
    }
    cropped, _ = crop_taxonomy_for_labeling(
        tax, options=LabelingTaxonomyOptions(depth=1, output_mode="path")
    )
    schema_d1 = cropped["labels"][0]["value_schema"]
    assert tree_depth(schema_d1) == 1
    path = normalize_tree_value(example, "a1", output_mode="path")
    assert path == ["group_a", "a1"]
    return {
        "scaffold_depth": tree_depth(example),
        "crop_depth_1": tree_depth(schema_d1),
        "norm_path": path,
    }


def _run_pipeline(*, skip_extract: bool, detector: str) -> dict:
    from oms_multimodal import ClipConfig, annotate_bboxes, encode_preview_videos, extract_clips, resolve_detector

    bag = Path(require_arg("bag_local_path"))
    if not bag.is_file():
        raise FileNotFoundError(f"bag not found: {bag}")
    run_out, clip_id, run_id = require_run_paths()
    os.environ.setdefault("BBOX_DETECTOR", detector)
    os.environ.setdefault("BBOX_ELEMENT", os.getenv("BBOX_ELEMENT", "element"))
    os.environ.setdefault("ENCODE_PLAIN", "true")
    os.environ.setdefault("ENCODE_BBOX", "true")
    os.environ.setdefault("EXTRACT_INLINE_ENCODE", "false")

    client, _, _ = build_sdk_client(require_taxonomy=False, load_dotenv=True)
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode="local")
    out: dict = {"run_dir": str(run_out), "detector": detector}

    try:
        if not skip_extract:
            er = extract_clips(
                ctx,
                bag,
                client=client,
                clip_config=ClipConfig(
                    min_sec=get_float_arg("clip_min_sec", 15.0),
                    max_sec=get_float_arg("clip_max_sec", 20.0),
                    sample_fps=get_float_arg("sample_fps", 1.0),
                ),
            )
            out["extract_clip_rows"] = er.clip_rows
        elif not ctx.clips_index_path.is_file():
            raise FileNotFoundError(f"missing clips_index: {ctx.clips_index_path}; run without --skip-extract")

        br = annotate_bboxes(ctx, client, detector=resolve_detector(detector))
        out["bbox"] = {
            "frame_count": br.frame_count,
            "box_count": br.box_count,
            "bboxes_out": str(br.bboxes_out),
        }
        enc = encode_preview_videos(ctx, client, variants=("plain", "bbox"))
        out["encode"] = {
            "plain_count": enc.plain_count,
            "bbox_count": enc.bbox_count,
            "videos_out": str(enc.videos_out),
            "errors": enc.errors[:3],
        }
    finally:
        client.close()

    # Artifact presence
    out["artifacts"] = {
        "clips_index": ctx.clips_index_path.is_file(),
        "bboxes_jsonl": ctx.bboxes_path.is_file(),
        "clip_videos_jsonl": ctx.videos_path.is_file(),
    }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Local SDK smoke (no MC): taxonomy + bbox + encode")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument(
        "--detector",
        default=os.getenv("BBOX_DETECTOR", "stub"),
        help="noop|stub|opencv|yolo (default stub for offline smoke)",
    )
    parser.add_argument("--taxonomy-only", action="store_true", help="only check taxonomy trees")
    args = parser.parse_args()

    env_path = load_local_env(override=False)
    print(f"env={env_path or '(none)'}")

    tax = _check_taxonomy()
    print(json.dumps({"ok": True, "step": "taxonomy", **tax}, ensure_ascii=False))
    if args.taxonomy_only:
        return

    result = _run_pipeline(skip_extract=args.skip_extract, detector=args.detector)
    print(json.dumps({"ok": True, "step": "bbox_encode", **result}, ensure_ascii=False))
    if not result["artifacts"]["clips_index"] or not result["artifacts"]["bboxes_jsonl"]:
        raise SystemExit("smoke failed: missing artifacts")
    print("======== LOCAL SDK SMOKE OK ========")


if __name__ == "__main__":
    main()
