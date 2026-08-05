#!/usr/bin/env python3
"""示例 01：只查看 bag 里有什么（不调用任何云端模型）。

做什么
    打开一份 ROS1 录制文件（.bag），列出里面的「话题」：
    名称、消息类型、模态（图像/音频/文本等）、消息条数。

怎么跑
    py -3.11 examples/01_inspect_bag.py

可选环境变量
    BAG_PATH  —— 指定你的 .bag 路径；不设则用脚本内默认样例路径
"""
from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 让「未 pip install、直接跑脚本」时也能 import 到本仓库里的 oms_multimodal
# ---------------------------------------------------------------------------
_EXAMPLES = Path(__file__).resolve().parent  # .../piplinesdk/examples
_SDK_ROOT = _EXAMPLES.parent                 # .../piplinesdk
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

from _common import default_bag  # noqa: E402
from oms_multimodal import __version__, inspect_bag  # noqa: E402


def main() -> None:
    # 1）确定要打开的 bag 文件
    bag = default_bag()
    if not bag.is_file():
        raise SystemExit(
            f"找不到 bag 文件: {bag}\n"
            f"请设置环境变量后重试，例如：\n"
            f'  $env:BAG_PATH = "D:\\data\\my_recording.bag"'
        )

    print(f"SDK 版本 = {__version__}")
    print(f"bag 路径 = {bag}")

    # 2）只做元数据检查：不解码全部帧，也不调用大模型
    topics = inspect_bag(bag)

    # 3）打印每个话题的摘要
    #    modality：image=图像, audio=音频, text=文本, other=其它
    print("--- 话题列表 ---")
    for t in topics:
        print(
            f"  模态={t.modality:6}  "
            f"消息数={t.message_count:6}  "
            f"名称={t.name}  "
            f"类型={t.msgtype}"
        )
    print(f"话题总数 = {len(topics)}")
    print("完成。下一步可跑：examples/02_extract_only.py（本地解析，仍不需要密钥）")


if __name__ == "__main__":
    main()
