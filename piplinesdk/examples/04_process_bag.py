#!/usr/bin/env python3
"""示例 04：旧的一键接口 process_bag（解析 + 语音识别 + 打标 + 向量）。

做什么
    调用 client.process_bag，内部按固定顺序跑完整处理。
    步骤开关不如示例 03 的 run_stages 灵活；适合快速试一把。

怎么跑
    py -3.11 examples/04_process_bag.py

环境变量
    BAG_PATH / RUN_OUT / MODEL_BACKEND
    以及 .env 中的 DASHSCOPE_API_KEY、DASHSCOPE_WORKSPACE_ID

推荐
    新代码优先用 examples/03_run_stages.py。
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
    OutputConfig,
    __version__,
    bundled_taxonomy_path,
)


def main() -> None:
    # 1）读入密钥环境变量；选择模型后端 api 或 mc
    env_path = safe_load_dotenv()
    backend = model_backend()

    # 2）输入 bag、输出目录
    bag = default_bag()
    if not bag.is_file():
        raise SystemExit(
            f"找不到 bag 文件: {bag}\n"
            f'请设置: $env:BAG_PATH = "D:\\data\\my_recording.bag"'
        )

    out = default_run_out("04_process_bag")
    out.mkdir(parents=True, exist_ok=True)

    print(f"SDK 版本    = {__version__}")
    print(f"模型后端    = {backend}")
    print(f"已加载 .env = {env_path or '(未找到)'}")
    print(f"bag 路径    = {bag}")
    print(f"输出目录    = {out}")

    # 3）创建客户端
    client = OmsMultimodalClient(
        taxonomy_path=bundled_taxonomy_path(),
        work_dir=out / "_sdk_work",
        load_dotenv=False,  # 已由 safe_load_dotenv 处理
        model_backend=backend,  # type: ignore[arg-type]
    )

    try:
        # 4）一键处理整份 bag
        # OutputConfig：指定标签文件、向量文件写到哪里
        result = client.process_bag(
            bag,
            clip_config=ClipConfig(
                min_sec=15,
                max_sec=20,
                sample_fps=1.0,
                max_clips=2,  # 示例限制片段数
            ),
            output=OutputConfig(
                embeddings_out=out / "fusion_embeddings.jsonl",
                labels_out=out / "labels.jsonl",
            ),
        )
    finally:
        client.close()

    # 5）打印结果摘要
    # to_dict()：把结果对象转成普通字典，方便打印/落盘
    print("--- process_bag 结果 ---")
    print(result.to_dict())
    print(f"标签行数 label_rows         = {result.label_rows}")
    print(f"向量行数 embedding_rows     = {result.embedding_rows}")
    print(f"错误列表 errors             = {result.errors}")
    print("DONE")


if __name__ == "__main__":
    main()
