#!/usr/bin/env python3
"""示例 02：只做本地解析（切片段、导出媒体；不调用云端大模型）。

做什么
    把 .bag 切成约 15～20 秒的时间片段（clip），写出索引文件，
    并在工作目录里生成帧、音频、预览素材等。

不需要
    百炼 / DashScope 密钥（本脚本关闭了自动加载 .env）。

怎么跑
    py -3.11 examples/02_extract_only.py

可选环境变量
    BAG_PATH  —— 输入 bag
    RUN_OUT   —— 结果输出目录；默认 examples/_out/02_extract
"""
from __future__ import annotations

import sys
from pathlib import Path

_EXAMPLES = Path(__file__).resolve().parent
_SDK_ROOT = _EXAMPLES.parent
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from _common import default_bag, default_run_out  # noqa: E402
from oms_multimodal import (  # noqa: E402
    ClipConfig,
    OmsMultimodalClient,
    __version__,
    bundled_taxonomy_path,
    extract_clips,
)


def main() -> None:
    # ---------- 输入 / 输出路径 ----------
    bag = default_bag()
    if not bag.is_file():
        raise SystemExit(
            f"找不到 bag 文件: {bag}\n"
            f'请设置: $env:BAG_PATH = "D:\\data\\my_recording.bag"'
        )

    # run_dir：对外结果目录（索引 jsonl 写在这里）
    run_dir = default_run_out("02_extract")
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"SDK 版本 = {__version__}")
    print(f"bag 路径 = {bag}")
    print(f"输出目录 = {run_dir}")

    # ---------- 创建客户端 ----------
    # taxonomy：标签体系 YAML；本步虽不打标，仍建议传入安装包自带路径，保持写法一致。
    # work_dir：中间文件（解码帧、临时 clip 目录），默认放在 run_dir/_sdk_work。
    # load_dotenv=False：不读 .env，避免无关编码问题；本步也不需要密钥。
    client = OmsMultimodalClient(
        taxonomy_path=bundled_taxonomy_path(),
        work_dir=run_dir / "_sdk_work",
        load_dotenv=False,
        model_backend="api",  # 本步不调模型；写 api 仅表示默认后端取值
    )

    # ---------- 运行上下文 ----------
    # 告诉 SDK：结果写到哪个目录、媒体从本机读
    ctx = client.make_run_context(
        run_dir,
        media_mode="local",      # local = 读写本机磁盘路径
        clip_id="demo",          # 业务上的 clip 标识（示例随便起名）
        run_id="extract-only",   # 本次运行标识（示例随便起名）
    )

    try:
        # ---------- 执行「解析」步骤 ----------
        # ClipConfig：
        #   min_sec / max_sec —— 每个时间片段大约多长（秒）
        #   sample_fps        —— 为后续打标准备的采样帧率（本步也会按此抽帧）
        #   max_clips         —— 最多切几段；示例里限制为 2，跑得更快
        result = extract_clips(
            ctx,
            bag,
            client=client,
            clip_config=ClipConfig(
                min_sec=15,
                max_sec=20,
                sample_fps=1.0,
                max_clips=2,
            ),
        )
    finally:
        # 释放可能占用的资源（有模型会话时尤其重要）
        client.close()

    # ---------- 看结果 ----------
    print("--- 解析结果 ---")
    print(f"切出片段数 clip_rows = {result.clip_rows}")
    print(f"视频记录行数 video_rows = {result.video_rows}")
    print(f"片段索引文件 = {result.clips_index}")
    print(f"视频清单文件 = {result.videos_out}")
    print("OK。下一步可跑：examples/03_run_stages.py extract,asr（需要百炼密钥）")


if __name__ == "__main__":
    main()
