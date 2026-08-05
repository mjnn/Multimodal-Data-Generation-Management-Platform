# OMS Multimodal SDK 文档索引

> 版本 **0.3.2** · 软件包名 `oms-multimodal-sdk`

| 文档 | 路径 | 适合谁 |
|------|------|--------|
| **使用说明（主文档）** | [SDK.md](SDK.md) | 所有新用户 |
| **可运行示例** | [../examples/](../examples/) | 想先动手跑通的人 |
| **DataWorks 批量运行** | [DATAWORKS_SDK.md](DATAWORKS_SDK.md) | 已有阿里云大数据环境的进阶用户 |
| 发布说明 | [../RELEASE.md](../RELEASE.md) | 打包发布 |
| 构建脚本 | [../scripts/build_release.ps1](../scripts/build_release.ps1) | 打包发布 |

安装后也可在 Python 中定位内置副本：

```python
from oms_multimodal import (
    __version__,
    bundled_taxonomy_path,
    bundled_sdk_doc_path,
    bundled_dataworks_doc_path,
)

print(__version__)
print(bundled_sdk_doc_path())
print(bundled_taxonomy_path())
```

## 建议阅读顺序

1. 打开 [examples/README.md](../examples/README.md)，按顺序跑 `01` → `02` → `03`
2. 阅读 [SDK.md](SDK.md) 第 1～6 节（概念 + 推荐用法）与文末术语表
3. 需要查函数签名时，再看 [SDK.md](SDK.md) 第 7 节起的 API 参考
4. 仅当要把任务提交到阿里云 DataWorks 批量计算时，再读 [DATAWORKS_SDK.md](DATAWORKS_SDK.md)
