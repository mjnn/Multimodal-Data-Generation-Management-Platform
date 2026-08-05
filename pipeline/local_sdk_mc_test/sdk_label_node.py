# =============================================================================
# 本地联调：sdk_label（与 DataWorks sdk_label_node 同业务）
# 前置：clips_index.jsonl + 可选 asr.jsonl
# 本地默认 media_mode=local（帧在 _sdk_work）；上云 upload 后用 oss
# =============================================================================

from __future__ import annotations

import json

from oms_multimodal import label_clips

from sdk_node_common import build_sdk_client, make_run_context, require_run_paths, resolve_media_mode


def main() -> None:
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=True)
    ctx = make_run_context(
        client,
        run_out,
        clip_id=clip_id,
        run_id=run_id,
        media_mode=resolve_media_mode("local"),
    )
    try:
        result = label_clips(ctx, client, run_asr=False, merge_asr_file=True)
    finally:
        client.close()
    print(
        json.dumps(
            {
                "ok": True,
                "capability": "label",
                "row_count": result.row_count,
                "errors": result.errors,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
