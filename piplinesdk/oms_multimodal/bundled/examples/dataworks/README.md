# DataWorks 节点参考代码（只读副本）

本目录文件自 HMI 仓 `pipeline/dataworks/` 同步，供 wheel 安装后离线查阅。

**粘贴到 DataWorks 前**请在源码仓执行 bundle（内联 helper）：

```bash
python pipeline/scripts/bundle_pipeline_dispatch.py dataworks/sdk_extract_dpe_node.py
```

| 文件 | 说明 |
|------|------|
| `dpe_udf_minimal_example.py` | 最简 Driver + DPE UDF |
| `05_dpe_apply_chunk_concurrency.py` | 教学：UDF、`apply`/`apply_chunk`、`batch_rows`/`dpe_parallel`（与 `piplinesdk/examples/05_*.py` 同源） |
| `sdk_dpe_common.py` | 批量 apply 壳 |
| `pipeline_dispatch.py` / `upload_run.py` | dispatch / upload_run |
| `sdk_*_dpe_node.py` | 各 capability DPE 节点 |
| `sdk_dispatch_batch_node.py` | batch dispatch（Driver） |
| `sdk_infer_node.py` | 复合 infer（Driver） |

详细说明见同级 `../DATAWORKS_SDK.md`。
