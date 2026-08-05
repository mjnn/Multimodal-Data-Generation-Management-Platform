# =============================================================================
# 本地联调：sdk_infer（复合 infer_full，等价 process_bag）
# 适合一次性冒烟；原子节点分步排错用 run_pipeline.py
# =============================================================================

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from oms_multimodal import ClipConfig, OutputConfig

from sdk_node_common import (
    build_sdk_client,
    get_arg,
    get_float_arg,
    make_run_context,
    require_arg,
    resolve_backend,
    resolve_media_mode,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    bag_path = Path(require_arg("bag_local_path"))
    if not bag_path.is_file():
        raise FileNotFoundError(f"bag not found: {bag_path}")
    run_out = Path(require_arg("run_out_dir"))
    clip_id = require_arg("clip_id")
    run_id = require_arg("run_id")
    ds = get_arg("ds") or datetime.now(timezone.utc).strftime("%Y%m%d")
    backend = resolve_backend()
    run_out.mkdir(parents=True, exist_ok=True)
    work_dir = run_out / "_sdk_work"

    client, _, mc_config = build_sdk_client(
        backend=backend,
        require_taxonomy=True,
        load_dotenv=True,
        work_dir=work_dir,
    )
    media_mode = resolve_media_mode("local")
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode=media_mode)
    try:
        result = client.process_bag(
            bag_path,
            clip_config=ClipConfig(
                min_sec=get_float_arg("clip_min_sec", 15.0),
                max_sec=get_float_arg("clip_max_sec", 20.0),
                sample_fps=get_float_arg("sample_fps", 1.0),
            ),
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
