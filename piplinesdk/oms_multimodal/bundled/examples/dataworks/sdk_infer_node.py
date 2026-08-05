# =============================================================================
# DataWorks PyODPS3 节点：SDK 推理（sdk_infer）
# 用 oms-multimodal-sdk 完成：rosbag 解析 → ASR → 预览 MP4 → 打标 → 融合向量
#
# 粘贴前在镜像/节点依赖中安装：
#   pip install /path/to/piplinesdk/oms_multimodal_sdk-0.3.1-py3-none-any.whl
#   # model_backend=mc  additionally:
#   pip install 'oms-multimodal-sdk[mc]'
#
# 工作流参数示例（api，默认）：
#   bag_local_path=/mnt/oss/rosbags/.../output.bag
#   clip_id=sha256:...
#   run_id=...
#   run_out_dir=/mnt/oss/clips/{clip_id}/runs/{run_id}
#   taxonomy_path=
#   model_backend=api
#   # Secrets：DASHSCOPE_API_KEY, DASHSCOPE_WORKSPACE_ID
#
# 工作流参数示例（mc，MaxFrame + bigdata_modelset）：
#   model_backend=mc
#   mc_omni_fallback_model=qwen3.6-plus
#   mc_modelset_project=bigdata_public_modelset
#   mc_image_mode=base64          # 推荐：帧在本地 _sdk_work，非 OSS key
#   dpe_image=sq_maxframe
#   ai_cu_quota_name= / ai_gu_quota_name=
#   total_rpm_limit=12000
#   request_timeout=300
#   # oss_url 模式才需要：oss_vl_access_key_id, oss_vl_access_key_secret, oss_bucket
# =============================================================================

from __future__ import annotations

import json
import os
from pathlib import Path
from datetime import datetime, timezone

from oms_multimodal import ClipConfig, OutputConfig

from sdk_node_common import (
    build_sdk_client,
    get_arg,
    make_run_context,
    require_arg,
    resolve_backend,
    resolve_media_mode,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    bag_path = Path(require_arg("bag_local_path"))
    run_out = Path(require_arg("run_out_dir"))
    clip_id = require_arg("clip_id")
    run_id = require_arg("run_id")
    ds = get_arg("ds") or datetime.now(timezone.utc).strftime("%Y%m%d")
    backend = resolve_backend()
    run_out.mkdir(parents=True, exist_ok=True)
    work_dir = run_out / "_sdk_work"

    client, client_config, mc_config = build_sdk_client(
        backend=backend,
        require_taxonomy=True,
        load_dotenv=False,
        work_dir=work_dir,
    )
    media_mode = resolve_media_mode("local")
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode=media_mode)
    try:
        result = client.process_bag(
            bag_path,
            clip_config=ClipConfig(min_sec=15.0, max_sec=20.0, sample_fps=1.0),
            output=OutputConfig(
                labels_out=run_out / "labels.jsonl",
                embeddings_out=run_out / "fusion_embeddings.jsonl",
                videos_out=run_out / "clip_videos.jsonl",
            ),
            run_context=ctx,
        )
    finally:
        client.close()

    run_json = {
        "layout_version": "sdk_v1",
        "clip_id": clip_id,
        "run_id": run_id,
        "ds": ds,
        "sdk_files": {
            "labels": "labels.jsonl",
            "embeddings": "fusion_embeddings.jsonl",
            "videos": "clip_videos.jsonl",
        },
        "preview_manifest": "preview/manifest.json",
        "completed_at": _utc_now(),
        "model_backend": backend,
    }
    if backend == "mc" and mc_config is not None:
        run_json["mc"] = {
            "modelset_project": mc_config.modelset_project,
            "omni_fallback_model": mc_config.omni_fallback_model,
            "image_mode": mc_config.resolved_image_mode(),
            "media_mode": media_mode,
            "asr_model": os.environ.get("ASR_MODEL", "qwen3-asr-flash"),
            "embedding_model": os.environ.get("EMBEDDING_MODEL", "qwen3-vl-embedding"),
            "omni_model": os.environ.get("OMNI_MODEL", "qwen3.5-omni-plus"),
        }
    (run_out / "run.json").write_text(json.dumps(run_json, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {"ok": True, "model_backend": backend, "result": result.to_dict()},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
