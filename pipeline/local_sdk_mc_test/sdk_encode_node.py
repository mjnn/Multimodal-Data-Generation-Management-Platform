# =============================================================================
# 本地联调：sdk_encode（encode_preview_videos）
# 参数：RUN_OUT_DIR, CLIP_ID, RUN_ID, ENCODE_PLAIN
# =============================================================================

from __future__ import annotations

import json
import os

from oms_multimodal import encode_preview_videos, resolve_encode_variants

from sdk_node_common import build_sdk_client, make_run_context, require_run_paths


def main() -> None:
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=False, load_dotenv=True)
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode="local")
    variants = resolve_encode_variants(None)
    raw = os.getenv("ENCODE_VARIANTS", "").strip()
    if raw:
        variants = [v.strip() for v in raw.split(",") if v.strip()]
    try:
        result = encode_preview_videos(ctx, client, variants=variants)
    finally:
        client.close()
    print(
        json.dumps(
            {
                "ok": True,
                "capability": "encode_preview",
                "variants": result.variants,
                "plain_count": result.plain_count,
                "bbox_count": result.bbox_count,
                "videos_out": str(result.videos_out),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
