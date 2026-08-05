# =============================================================================
# DataWorks PyODPS3：sdk_preview（原子能力 preview）
# 前置：sdk_extract 已写 _sdk_work/
# 输出：run_dir/preview/clip_preview_*.mp4, audio.wav
# 参数：run_out_dir, clip_id, run_id（仅用于日志）
# =============================================================================

from __future__ import annotations

import json

from oms_multimodal import materialize_preview

from sdk_node_common import build_sdk_client, make_run_context, require_run_paths


def main() -> None:
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=False, load_dotenv=False)
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode="local")
    try:
        preview_dir = materialize_preview(ctx)
    finally:
        client.close()
    mp4_count = len(list(preview_dir.glob("clip_preview_*.mp4")))
    print(
        json.dumps(
            {
                "ok": True,
                "capability": "preview",
                "preview_dir": str(preview_dir),
                "mp4_count": mp4_count,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
