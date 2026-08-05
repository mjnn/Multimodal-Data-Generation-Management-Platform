#!/usr/bin/env python3
"""本机验证 SDK MC 能力 + OSS 上传 + MC ingest（不含 DPE apply_chunk）。

默认复用已有 extract（``RUN_OUT_DIR`` 下已有 ``clips_index.jsonl`` + ``_sdk_work``），
只重跑 ``asr,preview,label,embed,upload``，再：
  1) 上传到真实 OSS（sdk_v1 run 树）
  2) 写入 ``aig_sdk__*``（本机 PyODPS ingest）
  3) 调用 ``verify_sdk_v1_run.py`` 做 OSS+MC 核对

用法::

    cd pipeline/local_sdk_mc_test
    py -3.11 run_mc_oss_verify.py
    py -3.11 run_mc_oss_verify.py --with-extract   # 强制重跑 extract（更慢）
    py -3.11 run_mc_oss_verify.py --skip-cloud     # 只跑 SDK，不上传/不 ingest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SDK_ROOT = REPO / "piplinesdk"
PIPELINE = REPO / "pipeline"
# 后 insert 的会排到最前：先放依赖目录，最后放本目录，保证优先用本目录 sdk_node_common
_PATHS = [
    REPO / "shared",
    REPO / "hmi" / "backend",
    PIPELINE / "dataworks",
    PIPELINE,
    SDK_ROOT,
    HERE,
]
for p in _PATHS:
    s = str(p)
    if s in sys.path:
        sys.path.remove(s)
    sys.path.insert(0, s)

# 必须先于 oms_multimodal：避免其它路径上的同名 sdk_node_common 抢先
from sdk_node_common import (  # noqa: E402
    build_sdk_client,
    get_arg,
    load_local_env,
    make_run_context,
    require_arg,
    require_run_paths,
    resolve_backend,
)

from oms_multimodal import (  # noqa: E402
    ClipConfig,
    __version__,
    parse_stages,
    run_stages,
)
from oms_multimodal.storage_backend import upload_run_dir_to_oss  # noqa: E402


def _bag_clip_id(bag: Path) -> str:
    digest = hashlib.sha256(bag.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _ds_today() -> str:
    # 与云上常见分区一致：UTC+8 日历日
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(hours=8)).strftime("%Y%m%d")


def _ensure_clip_id(bag: Path) -> str:
    configured = (get_arg("clip_id") or "").strip()
    real = _bag_clip_id(bag)
    if not configured or configured.endswith(":demo") or "demo" in configured.lower():
        os.environ["CLIP_ID"] = real
        print(f"CLIP_ID auto-set from bag hash → {real}")
        return real
    if configured != real:
        print(f"WARN: CLIP_ID={configured} != bag_sha256={real} (继续用配置值)")
    return configured


def run_sdk(*, with_extract: bool) -> Path:
    bag = Path(require_arg("bag_local_path"))
    if not bag.is_file():
        raise FileNotFoundError(bag)
    clip_id = _ensure_clip_id(bag)
    run_out, _, run_id = require_run_paths()
    # 若换了 run_id 但想复用 extract：把旧 _sdk_work / clips_index 拷过来
    legacy = HERE / "output" / "run_demo"
    if (
        not with_extract
        and not (run_out / "clips_index.jsonl").is_file()
        and (legacy / "clips_index.jsonl").is_file()
    ):
        print(f"seed extract artifacts from {legacy} → {run_out}")
        run_out.mkdir(parents=True, exist_ok=True)
        for name in ("clips_index.jsonl", "clip_videos.jsonl"):
            src = legacy / name
            if src.is_file():
                shutil.copy2(src, run_out / name)
        src_work = legacy / "_sdk_work"
        if src_work.is_dir():
            dst_work = run_out / "_sdk_work"
            if dst_work.exists():
                shutil.rmtree(dst_work)
            shutil.copytree(src_work, dst_work)

    stages_raw = (
        "extract,asr,preview,label,embed,upload"
        if with_extract
        else "asr,preview,label,embed,upload"
    )
    if not with_extract and not (run_out / "clips_index.jsonl").is_file():
        raise SystemExit("no clips_index.jsonl — pass --with-extract or seed RUN_OUT_DIR")

    backend = resolve_backend()
    print(
        json.dumps(
            {
                "sdk": __version__,
                "backend": backend,
                "stages": stages_raw,
                "bag": str(bag),
                "run_out": str(run_out),
                "clip_id": clip_id,
                "run_id": run_id,
            },
            ensure_ascii=False,
        )
    )

    client, _, _ = build_sdk_client(require_taxonomy=True, load_dotenv=True, work_dir=run_out / "_sdk_work")
    ctx = make_run_context(client, run_out, clip_id=clip_id, run_id=run_id, media_mode="local")
    try:
        result = run_stages(
            ctx,
            bag,
            client,
            stages=parse_stages(stages_raw),
            clip_config=ClipConfig(
                min_sec=float(get_arg("clip_min_sec", "15") or "15"),
                max_sec=float(get_arg("clip_max_sec", "20") or "20"),
                sample_fps=float(get_arg("sample_fps", "1.0") or "1.0"),
            ),
            bag_oss_key=get_arg("bag_oss_key", "rosbags/output/output.bag") or "",
            ds=_ds_today(),
            model_backend=backend,
        )
    finally:
        client.close()

    summary = {
        "stages_done": result.stages_done,
        "errors": result.errors,
        "preview_ok": result.preview_ok,
        "label_rows": result.label_rows,
        "embedding_rows": result.embedding_rows,
        "has_asr": (run_out / "asr.jsonl").is_file(),
        "has_labels": (run_out / "labels.jsonl").is_file(),
        "has_embed": (run_out / "fusion_embeddings.jsonl").is_file(),
        "has_videos": (run_out / "clip_videos.jsonl").is_file(),
        "has_run_json": (run_out / "run.json").is_file(),
        "has_preview_manifest": (run_out / "preview" / "manifest.json").is_file(),
    }
    print("SDK_RESULT=" + json.dumps(summary, ensure_ascii=False))
    if result.errors:
        raise SystemExit(f"SDK stages reported errors: {result.errors}")
    for key in ("has_asr", "has_labels", "has_embed", "has_videos", "has_run_json", "has_preview_manifest"):
        if not summary[key]:
            raise SystemExit(f"missing artifact after SDK run: {key}")
    return run_out


def upload_and_ingest(run_out: Path, *, skip_verify: bool) -> None:
    clip_id = require_arg("clip_id")
    run_id = require_arg("run_id")
    ds = get_arg("ds", _ds_today()) or _ds_today()
    bucket = get_arg("oss_bucket") or os.environ.get("OSS_BUCKET", "")
    if not bucket:
        raise SystemExit("OSS_BUCKET missing")

    print(f"Uploading run → oss://{bucket}/clips/{clip_id}/runs/{run_id}/")
    uri = upload_run_dir_to_oss(run_out, clip_id=clip_id, run_id=run_id, bucket=bucket)
    print(f"OSS_UPLOAD={uri}")

    # ingest 脚本默认读 HMI local artifacts；这里直接调 ingest_sdk_run(run_dir=本地产物)
    from odps import ODPS
    from cloud_config import load_cloud_env, require_odps_settings, resolve_cloud_settings
    from repo_paths import CONFIG_PATH
    import yaml
    from sdk_mc_ingest import ingest_sdk_run

    load_cloud_env()
    # 也合并本目录 .env（ODPS 可能只在 local_sdk_mc_test/.env）
    load_local_env(override=False)
    with CONFIG_PATH.open(encoding="utf-8") as f:
        config = yaml.safe_load(f)
    settings = require_odps_settings(resolve_cloud_settings(config))
    # 本目录 .env 可覆盖 config
    access_id = os.environ.get("ODPS_ACCESS_ID") or settings["odps_access_id"]
    access_key = os.environ.get("ODPS_ACCESS_KEY") or settings["odps_access_key"]
    project = os.environ.get("ODPS_PROJECT") or settings["odps_project"]
    endpoint = os.environ.get("ODPS_ENDPOINT") or settings["odps_endpoint"]
    odps = ODPS(access_id, access_key, project=project, endpoint=endpoint)
    prefix = settings.get("sdk_table_prefix") or settings.get("table_prefix") or "aig_sdk__"
    ingest_sdk_run(
        odps,
        clip_id=clip_id,
        run_id=run_id,
        ds=ds,
        run_dir=run_out,
        table_prefix=prefix,
    )
    print(f"MC_INGEST ok prefix={prefix} ds={ds}")

    if skip_verify:
        return
    cmd = [
        sys.executable,
        str(PIPELINE / "scripts" / "verify_sdk_v1_run.py"),
        "--clip-id",
        clip_id,
        "--run-id",
        run_id,
        "--ds",
        ds,
    ]
    print("VERIFY:", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(PIPELINE), check=False)
    if proc.returncode != 0:
        raise SystemExit(f"verify_sdk_v1_run failed exit={proc.returncode}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-extract", action="store_true")
    parser.add_argument("--skip-cloud", action="store_true", help="only SDK stages")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()

    load_local_env(override=True)
    os.environ.setdefault("MODEL_BACKEND", "mc")
    # 默认写到独立目录，避免踩旧 demo
    os.environ.setdefault("RUN_OUT_DIR", str(HERE / "output" / "run_mc_oss_verify_20260805"))

    run_out = run_sdk(with_extract=args.with_extract)
    if args.skip_cloud:
        print("skip-cloud: done (SDK only)")
        return
    upload_and_ingest(run_out, skip_verify=args.skip_verify)
    print("ALL_DONE")


if __name__ == "__main__":
    main()
