from pathlib import Path

docs = Path(__file__).resolve().parent
head = (docs / "_sdk_head.md").read_text(encoding="utf-8")
tail = (docs / "_sdk_tail.md").read_text(encoding="utf-8")
tail = tail.replace(
    "### 示例 E：`run_stages` 缩阶（extract + asr）",
    "### 示例 E：只跑解析 + 语音识别",
)
tail = tail.replace('Path("output/p0_asr")', 'Path("output/asr_probe")')
glossary = """

---

## 15. 术语表

| 说法 | 完整含义 |
|------|----------|
| SDK | Software Development Kit，软件开发工具包；这里特指本 Python 包 |
| bag / rosbag | ROS 录制文件（`.bag`） |
| ROS / ROS1 | Robot Operating System（机器人操作系统）；本 SDK 读的是 ROS1 录制格式 |
| clip | 从 bag 切出的一小段时间窗口（默认约 15～20 秒） |
| topic / 话题 | bag 里一类消息通道，例如某路摄像头图像 |
| modality / 模态 | 消息类型归属：图像、音频、文本等 |
| ASR | Automatic Speech Recognition，自动语音识别（语音转文字） |
| Omni | 文中指用于场景打标的多模态大模型（默认 `qwen3.5-omni-plus`） |
| embedding / 向量 | 把一段多媒体内容映射成的数值向量，便于相似度搜索 |
| taxonomy / 标签体系 | 定义有哪些标签、如何解释的 YAML 文件 |
| Mel / Mel 谱 | 一种更符合人耳感知的音频频谱表示 |
| DashScope / 百炼 | 阿里云提供大模型 HTTP 调用的产品 |
| MaxCompute | 阿里云大数据计算服务；`MODEL_BACKEND=mc` 时走这条路径 |
| `MODEL_BACKEND=api` | 用百炼 HTTP 调用模型（本机试用默认） |
| `MODEL_BACKEND=mc` | 用 MaxCompute / MaxFrame AI 调用模型（进阶） |
| `run_stages` | 按步骤名组合执行流水线的推荐入口 |
| `jsonl` | JSON Lines：每行一个 JSON 对象的文本文件 |
| ffmpeg | 常用的音视频转码工具；生成预览 MP4 时可能用到 |

"""
out = head + tail.rstrip() + glossary
(docs / "SDK.md").write_text(out, encoding="utf-8")
(docs / "_sdk_head.md").unlink(missing_ok=True)
(docs / "_sdk_tail.md").unlink(missing_ok=True)
print("ok", len(out))
