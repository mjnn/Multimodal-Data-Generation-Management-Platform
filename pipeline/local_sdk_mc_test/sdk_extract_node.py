# =============================================================================
# 本地联调：sdk_extract（与 DataWorks sdk_extract_node 同业务）
# 参数：BAG_LOCAL_PATH, RUN_OUT_DIR, CLIP_ID, RUN_ID, CLIP_MIN_SEC, …
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path

from oms_multimodal import ClipConfig, extract_clips

from sdk_node_common import build_sdk_client, get_float_arg, make_run_context, require_arg, require_run_paths


def main() -> None:
    bag_path = Path(require_arg("bag_local_path"))
    if not bag_path.is_file():
        raise FileNotFoundError(f"bag not found: {bag_path}")
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=False, load_dotenv=True)
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode="local")
    try:
        result = extract_clips(
            ctx,
            bag_path,
            client=client,
            clip_config=ClipConfig(
                min_sec=get_float_arg("clip_min_sec", 15.0),
                max_sec=get_float_arg("clip_max_sec", 20.0),
                sample_fps=get_float_arg("sample_fps", 1.0),
            ),
        )
    finally:
        client.close()
    print(
        json.dumps(
            {
                "ok": True,
                "capability": "extract",
                "clip_rows": result.clip_rows,
                "video_rows": result.video_rows,
                "clips_index": str(result.clips_index),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
