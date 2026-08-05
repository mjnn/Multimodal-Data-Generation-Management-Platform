# OMS Multimodal SDK — 可运行示例

本目录提供**可以直接运行的脚本**，用来在你自己的电脑上验证 SDK 是否安装正确、能否解析 bag、能否调用云端模型。

阅读正式说明请看：[docs/SDK.md](../docs/SDK.md)。

---

## 你需要准备什么

1. **Python 3.11 或 3.12**（推荐）
2. 安装本 SDK：

```powershell
cd <本仓库里的 piplinesdk 目录>
py -3.11 -m pip install -e .
```

3. 一份 **ROS1 格式的 `.bag` 录制文件**
4. 若要跑语音识别 / 打标 / 向量：在 `piplinesdk` 目录准备 `.env`：

```powershell
copy .env.example .env
```

至少填写：

```env
DASHSCOPE_API_KEY=你的百炼密钥
DASHSCOPE_WORKSPACE_ID=你的业务空间ID
MODEL_BACKEND=api
```

密钥来自阿里云「百炼 / DashScope」控制台。  
**只跑「查看 bag」或「本地解析」时，可以不填密钥。**

---

## 指定你的 bag 与输出目录（可选）

脚本默认会尝试读取一份样例 bag。若找不到，或你想换自己的文件：

```powershell
$env:BAG_PATH = "D:\data\my_recording.bag"
$env:RUN_OUT  = "D:\tmp\sdk_demo_run"   # 可选：结果写到哪里
$env:MODEL_BACKEND = "api"              # 可选：api（默认）或 mc
```

---

## 脚本说明

| 脚本 | 会不会调用云端大模型 | 做什么 |
|------|----------------------|--------|
| `01_inspect_bag.py` | 否 | 列出 bag 里的话题与消息数量 |
| `02_extract_only.py` | 否 | 只做本地解析：切片段、导出媒体 |
| `03_run_stages.py` | 取决于你传入的步骤 | **推荐**：按步骤跑流水线 |
| `04_process_bag.py` | 是 | 旧的一键全流程接口 |
| `05_dpe_apply_chunk_concurrency.py` | 视节点配置 | **DataWorks 教学**：UDF、`apply` / `apply_chunk`、`batch_rows` / `dpe_parallel` |

### 建议按这个顺序试

```powershell
cd <piplinesdk 目录>

# 1）确认 bag 能打开
py -3.11 examples\01_inspect_bag.py

# 2）确认本地解析正常（不需要密钥）
py -3.11 examples\02_extract_only.py

# 3）解析 + 语音识别（需要密钥与网络）
py -3.11 examples\03_run_stages.py extract,asr

# 4）完整步骤：解析→语音识别→预览→打标→向量→写出 run.json
py -3.11 examples\03_run_stages.py

# （可选）旧一键接口
py -3.11 examples\04_process_bag.py
```

`03_run_stages.py` 的参数是**逗号分隔的步骤英文名**，常用：

| 步骤名 | 含义 |
|--------|------|
| `extract` | 解析 bag、切片段 |
| `asr` | 语音转文字 |
| `preview` | 整理预览目录 |
| `label` | 场景打标 |
| `embed` | 生成融合向量 |
| `upload` | 写出 `run.json`（表示本机结果已落盘可交付） |

不传参数时，默认跑：`extract,asr,preview,label,embed,upload`。

### DataWorks：UDF 与并发（示例 05）

`05_dpe_apply_chunk_concurrency.py` **不能**像上面那样在本机直接跑通（需要 DataWorks 注入的 `o` / `args`、MaxFrame、DPE 镜像）。用途是：

1. 阅读注释，搞清 Driver vs DPE Worker、什么是 UDF  
2. 对比 `DataFrame.apply`（一行一次）与 `mf.apply_chunk`（一次多行）  
3. 看清两个并发旋钮：`batch_rows`、`dpe_parallel`（配合 `mf.rebalance`）  
4. 按需把代码粘贴进 DataWorks PyODPS3 节点做探针  

节点参数建议先：`batch_rows=1`，`dpe_parallel=2`，`demo_mode=chunk`。  
生产完整实现见仓库 `pipeline/dataworks/sdk_pipeline_driver_node.py`；云上说明见 [docs/DATAWORKS_SDK.md](../docs/DATAWORKS_SDK.md)。

---

## 结果在哪里

默认写在：

`examples/_out/<脚本名>/`

若设置了环境变量 `RUN_OUT`，则写到该路径。

完整运行后，可在输出目录查看例如：`labels.jsonl`、`asr.jsonl`、`fusion_embeddings.jsonl`、`preview/`。

---

## 相关文档

| 文档 | 适合谁 |
|------|--------|
| [docs/SDK.md](../docs/SDK.md) | 所有人：安装、概念、API、术语表 |
| [docs/DATAWORKS_SDK.md](../docs/DATAWORKS_SDK.md) | 需要在阿里云 DataWorks 上批量跑的进阶读者 |
