# =============================================================================
# 本地联调：sdk_asr（与 DataWorks sdk_asr_node 同业务）
# 前置：extract → clips_index.jsonl
# =============================================================================

from __future__ import annotations

import json

from oms_multimodal import transcribe_clips

from sdk_node_common import build_sdk_client, make_run_context, require_run_paths, resolve_media_mode


def main() -> None:
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client()
    ctx = make_run_context(
        client,
        run_out,
        clip_id=clip_id,
        run_id=run_id,
        media_mode=resolve_media_mode("local"),
    )
    try:
        result = transcribe_clips(ctx, client)
    finally:
        client.close()
    print(
        json.dumps(
            {
                "ok": True,
                "capability": "transcribe",
                "row_count": result.row_count,
                "errors": result.errors,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
