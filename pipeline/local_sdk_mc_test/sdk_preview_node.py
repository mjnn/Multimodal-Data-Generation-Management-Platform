# =============================================================================
# 本地联调：sdk_preview（与 DataWorks sdk_preview_node 同业务）
# 前置：extract → _sdk_work/
# =============================================================================

from __future__ import annotations

import json

from oms_multimodal import materialize_preview

from sdk_node_common import build_sdk_client, make_run_context, require_run_paths


def main() -> None:
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=False, load_dotenv=True)
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
