# oms-multimodal-sdk 0.3.2 发布包

## 包文件

| 文件 | 用途 |
|------|------|
| `oms_multimodal_sdk-0.3.2-py3-none-any.whl` | **推荐**：wheel，Python 3.10+ |
| `oms_multimodal_sdk-0.3.2.tar.gz` | 源码包 |

## 安装

```bash
pip install oms_multimodal_sdk-0.3.2-py3-none-any.whl
```

## wheel 内附带资源

安装后位于 `site-packages/oms_multimodal/bundled/`：

| 文件 | Python 访问 |
|------|-------------|
| `oms_label_taxonomy.yaml` | `from oms_multimodal import bundled_taxonomy_path` |
| `SDK.md` | `from oms_multimodal import bundled_sdk_doc_path` |

示例：

```python
from oms_multimodal import OmsMultimodalClient, bundled_taxonomy_path, bundled_sdk_doc_path, __version__

print(__version__)
print(bundled_taxonomy_path())
print(bundled_sdk_doc_path())

client = OmsMultimodalClient(taxonomy_path=bundled_taxonomy_path())
```

## 本版本要点（0.3.2）

- 流水线默认 **ASR → Omni 打标 → fusion embedding**
- ASR 默认模型：**qwen3-asr-flash**
- 声学面板默认 **mel** 谱，供 VL-embedding 使用
- **Mel 矩阵导出**（`mel_matrix.csv`）并注入打标 / 向量化 text 特征（`mel_feature_text`）
- wheel 内置 **taxonomy YAML** 与 **SDK.md**

## 运行前配置

SDK **不包含** `.env` 与示例 rosbag。需配置：

- `DASHSCOPE_API_KEY`
- `DASHSCOPE_WORKSPACE_ID`（Omni 必需）
- 可选：`ASR_MODEL`、`ASR_LANGUAGE`、`EMBEDDING_*`、`OMNI_MODEL`

## 重新构建（维护者）

在 **`piplinesdk/`** 目录：

```bash
pip install build
Copy-Item docs/SDK.md oms_multimodal/bundled/SDK.md   # PowerShell；或 cp on Linux
# taxonomy：oms_multimodal/bundled/oms_label_taxonomy.yaml
python -m build
Copy-Item dist/oms_multimodal_sdk-0.3.2-py3-none-any.whl .
```

产物：`dist/` 与仓库根 `oms_multimodal_sdk-0.3.2-py3-none-any.whl`。
