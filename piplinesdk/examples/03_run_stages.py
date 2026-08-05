#!/usr/bin/env python3
"""示例 03：按步骤跑流水线（推荐入口 run_stages）。

做什么
    用逗号分隔的步骤名，组合执行：
      extract  —— 解析 bag、切片段
      asr      —— 语音转文字（Automatic Speech Recognition）
      preview  —— 整理预览目录
      label    —— 场景打标
      embed    —— 生成融合向量
      upload   —— 写出 run.json（表示本机结果已落盘）

怎么跑
    # 默认：上面全部步骤
    py -3.11 examples/03_run_stages.py

    # 只跑解析 + 语音识别（适合先验证密钥和网络）
    py -3.11 examples/03_run_stages.py extract,asr

环境变量
    BAG_PATH       —— 输入 .bag
    RUN_OUT        —— 输出目录；默认 examples/_out/03_run_stages
    MODEL_BACKEND  —— api（默认，阿里云百炼 HTTP）或 mc（MaxCompute，进阶）

需要密钥时
    在 piplinesdk/.env 或仓库根 .env 填写：
      DASHSCOPE_API_KEY=...
      DASHSCOPE_WORKSPACE_ID=...   # 打标步骤需要
      MODEL_BACKEND=api
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

from _common import default_bag, default_run_out, model_backend, safe_load_dotenv  # noqa: E402
from oms_multimodal import (  # noqa: E402
    ClipConfig,
    OmsMultimodalClient,
    __version__,
    bundled_taxonomy_path,
    parse_stages,
    run_stages,
)


def main() -> None:
    # ---------- 1）解析命令行：要跑哪些步骤 ----------
    # 未传参数时，默认跑完整链路
    stages_raw = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "extract,asr,preview,label,embed,upload"
    )
    # parse_stages：把 "extract,asr" 转成集合；也支持别名 transcribe → asr
    stages = parse_stages(stages_raw)

    # ---------- 2）加载密钥与后端选择 ----------
    # safe_load_dotenv：尽量用 utf-8 / gbk 读 .env，避免编码错误导致脚本直接崩
    env_path = safe_load_dotenv()
    # api = 百炼 HTTP（本机试用）；mc = MaxCompute MaxFrame AI（需额外安装 .[mc]）
    backend = model_backend()

    # ---------- 3）输入 bag / 输出目录 ----------
    bag = default_bag()
    if not bag.is_file():
        raise SystemExit(
            f"找不到 bag 文件: {bag}\n"
            f'请设置: $env:BAG_PATH = "D:\\data\\my_recording.bag"'
        )

    run_dir = default_run_out("03_run_stages")
    run_dir.mkdir(parents=True, exist_ok=True)

    print(f"SDK 版本     = {__version__}")
    print(f"模型后端     = {backend}")
    print(f"要跑的步骤   = {sorted(stages)}")
    print(f"已加载 .env  = {env_path or '(未找到，仅使用已有环境变量)'}")
    print(f"bag 路径     = {bag}")
    print(f"输出目录     = {run_dir}")

    # ---------- 4）创建客户端 ----------
    # load_dotenv=False：密钥已由上面 safe_load_dotenv 读入环境，避免重复加载踩坑
    client = OmsMultimodalClient(
        taxonomy_path=bundled_taxonomy_path(),  # 安装包自带的标签体系 YAML
        work_dir=run_dir / "_sdk_work",         # 中间工作目录（帧、临时文件）
        load_dotenv=False,
        model_backend=backend,  # type: ignore[arg-type]
    )

    # ---------- 5）运行上下文：结果写哪里、媒体从哪读 ----------
    ctx = client.make_run_context(
        run_dir,
        media_mode="local",  # 本机磁盘路径
        clip_id="demo-clip",
        run_id="demo-run",
    )

    try:
        # ---------- 6）按步骤执行 ----------
        # bag_oss_key / ds：上云对象存储路径、分区日期；本机示例可留空
        # cleanup_work=False：保留 _sdk_work，方便你打开看中间文件
        result = run_stages(
            ctx,
            bag,
            client,
            stages=stages,
            clip_config=ClipConfig(
                min_sec=15,
                max_sec=20,
                sample_fps=1.0,
                max_clips=2,  # 示例限制片段数，加快试用
            ),
            bag_oss_key="",
            ds="",
            model_backend=backend,
            cleanup_work=False,
        )
    finally:
        client.close()

    # ---------- 7）打印摘要 ----------
    print("--- 运行摘要 StagesResult ---")
    print(f"已完成步骤 stages_done     = {result.stages_done}")
    print(f"解析片段数 extract_clip_rows = {result.extract_clip_rows}")
    print(f"标签行数   label_rows        = {result.label_rows}")
    print(f"向量行数   embedding_rows    = {result.embedding_rows}")
    print(f"预览是否有效 preview_ok      = {result.preview_ok}")
    if result.errors:
        print(f"错误列表 errors = {result.errors}")

    # 检查关键产物是否已写出（未跑对应步骤时显示 -- 是正常的）
    print("--- 输出文件是否存在 ---")
    for name in (
        "clips_index.jsonl",          # extract
        "asr.jsonl",                  # asr
        "labels.jsonl",               # label
        "fusion_embeddings.jsonl",    # embed
        "clip_videos.jsonl",          # extract
        "run.json",                   # upload
        "preview/manifest.json",      # preview
    ):
        path = run_dir / name
        mark = "有" if path.is_file() else "无"
        print(f"  [{mark}] {path.relative_to(run_dir)}")

    print("DONE")


if __name__ == "__main__":
    main()
