# =============================================================================
# 本地联调：sdk_bbox（annotate_bboxes）
# 参数：RUN_OUT_DIR, CLIP_ID, RUN_ID, BBOX_DETECTOR
# =============================================================================

from __future__ import annotations

import json

from oms_multimodal import annotate_bboxes

from sdk_node_common import build_sdk_client, make_run_context, require_run_paths


def main() -> None:
    run_out, clip_id, run_id = require_run_paths()
    client, _, _ = build_sdk_client(require_taxonomy=False, load_dotenv=True)
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode="local")
    try:
        result = annotate_bboxes(ctx, client)
    finally:
        client.close()
    print(
        json.dumps(
            {
                "ok": True,
                "capability": "annotate_bbox",
                "frame_count": result.frame_count,
                "box_count": result.box_count,
                "bboxes_out": str(result.bboxes_out),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
