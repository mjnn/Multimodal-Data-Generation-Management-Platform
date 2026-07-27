# =============================================================================
# DataWorks PyODPS3 节点：SDK 推理（sdk_infer）
# 用 oms-multimodal-sdk 完成：rosbag 解析 → ASR → 预览 MP4 → Omni 打标 → 融合向量
#
# 粘贴前在镜像/节点依赖中安装：
#   pip install /path/to/piplinesdk/oms_multimodal_sdk-0.3.0-py3-none-any.whl
#   # 或源码：pip install -e /path/to/piplinesdk
#
# 工作流参数示例：
#   bag_local_path=/mnt/oss/rosbags/.../output.bag   # OSS 挂载后的 .bag
#   clip_id=sha256:...
#   run_id=...
#   run_out_dir=/mnt/oss/clips/{clip_id}/runs/{run_id}
#   taxonomy_path=                              # 空则用 bundled_taxonomy_path()
#   model_backend=api                           # 当前仅支持 api（MC Omni 未上架）
#
# 环境变量（Secrets）：DASHSCOPE_API_KEY, DASHSCOPE_WORKSPACE_ID
# =============================================================================

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from oms_multimodal import (
    ClipConfig,
    OmsMultimodalClient,
    OutputConfig,
    bundled_taxonomy_path,
)

try:
    from dw_args import get_arg, require_arg
except ImportError:

    def get_arg(name: str, default: str | None = None) -> str | None:
        import os

        return os.environ.get(name.upper(), default)

    def require_arg(name: str) -> str:
        value = get_arg(name)
        if not value:
            raise ValueError(f"missing {name}")
        return value


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _materialize_preview(run_out: Path, work_dir: Path, clip_id_from_sdk: str) -> None:
    """Copy SDK clip_preview_*.mp4 + audio.wav into preview/ for sdk_v1 OSS."""
    preview_dir = run_out / "preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    clips_root = work_dir / "clips"
    if not clips_root.is_dir():
        return
    for clip_dir in clips_root.iterdir():
        if not clip_dir.is_dir():
            continue
        for name in clip_dir.glob("clip_preview_*.mp4"):
            shutil.copy2(name, preview_dir / name.name)
        wav = clip_dir / "audio.wav"
        if wav.is_file():
            shutil.copy2(wav, preview_dir / "audio.wav")
        break


def main() -> None:
    bag_path = Path(require_arg("bag_local_path"))
    run_out = Path(require_arg("run_out_dir"))
    clip_id = require_arg("clip_id")
    run_id = require_arg("run_id")
    ds = get_arg("ds") or datetime.now(timezone.utc).strftime("%Y%m%d")
    backend = (get_arg("model_backend") or "api").strip().lower()

    taxonomy = get_arg("taxonomy_path")
    tax_path = Path(taxonomy) if taxonomy else bundled_taxonomy_path()

    run_out.mkdir(parents=True, exist_ok=True)
    work_dir = run_out / "_sdk_work"

    client = OmsMultimodalClient(
        taxonomy_path=tax_path,
        work_dir=work_dir,
        load_dotenv=True,
        model_backend="api" if backend != "mc" else "mc",
    )
    result = client.process_bag(
        bag_path,
        clip_config=ClipConfig(min_sec=15.0, max_sec=20.0, sample_fps=1.0),
        output=OutputConfig(
            labels_out=run_out / "labels.jsonl",
            embeddings_out=run_out / "fusion_embeddings.jsonl",
            videos_out=run_out / "clip_videos.jsonl",
        ),
    )

    _materialize_preview(run_out, work_dir, clip_id)

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
    (run_out / "run.json").write_text(json.dumps(run_json, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps({"ok": True, "result": result.to_dict() if hasattr(result, "to_dict") else result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
