# =============================================================================
# DataWorks PyODPS3：sdk_extract（原子能力 extract）
# 输入：bag_local_path（OSS 挂载）
# 输出：clips_index.jsonl, clip_videos.jsonl, run_dir/_sdk_work/
# 参数：run_out_dir, clip_id, run_id, media_mode=local（默认）
# =============================================================================

from __future__ import annotations

import json
from pathlib import Path

from oms_multimodal import ClipConfig, extract_clips

from sdk_node_common import build_sdk_client, make_run_context, require_arg, require_run_paths


def main() -> None:
    bag_path = Path(require_arg("bag_local_path"))
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=False, load_dotenv=False)
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode="local")
    try:
        result = extract_clips(
            ctx,
            bag_path,
            client=client,
            clip_config=ClipConfig(min_sec=15.0, max_sec=20.0, sample_fps=1.0),
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
