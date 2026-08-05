# =============================================================================
# DataWorks PyODPS3：sdk_embed（原子能力 embed）
# 前置：clips_index.jsonl + labels.jsonl
# 参数：run_out_dir, clip_id, run_id, model_backend, media_mode=oss（默认）
# =============================================================================

from __future__ import annotations

import json

from oms_multimodal import embed_clips

from sdk_node_common import build_sdk_client, make_run_context, require_run_paths, resolve_media_mode


def main() -> None:
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=False)
    ctx = make_run_context(
        client,
        run_out,
        clip_id=clip_id,
        run_id=run_id,
        media_mode=resolve_media_mode("oss"),
    )
    try:
        result = embed_clips(ctx, client)
    finally:
        client.close()
    print(
        json.dumps(
            {
                "ok": True,
                "capability": "embed",
                "row_count": result.row_count,
                "errors": result.errors,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
