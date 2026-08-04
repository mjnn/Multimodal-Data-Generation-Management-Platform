# Local SDK 全量功能示例

本目录用于在本地（含 Windows）跑通 OMS Multimodal SDK 的完整能力演示。

## 文件

| 文件 | 说明 |
|------|------|
| `sdk_full_pipeline_demo.ipynb` | Jupyter 全量示例：中间产物 + 打标/向量最终产物 |
| `.env.example` | 环境变量模板（复制为同目录或 `piplinesdk/.env`） |

## 准备

1. Python **3.11 / 3.12**（不推荐 3.14）
2. 在 `piplinesdk/` 下：

```powershell
pip install -e ".[mc]"
# 若本机 pyproject 无 [mc] extra，改用：
# pip install -e .
pip install jupyter ipykernel matplotlib
```

3. 配置 `DASHSCOPE_API_KEY`、`DASHSCOPE_WORKSPACE_ID`（见 `.env.example`）
4. 准备一个 ROS1 `.bag`，在 notebook 里改 `BAG_PATH`

## 运行

```powershell
cd D:\cursor_project\rosbag_to_labels_pipline\pipeline\local_sdk_mc_test
jupyter notebook sdk_full_pipeline_demo.ipynb
```

产物默认写到本目录下的 `output/`。
