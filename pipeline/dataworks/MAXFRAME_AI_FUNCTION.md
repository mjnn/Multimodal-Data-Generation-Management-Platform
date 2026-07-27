# MaxFrame AI Function 集成（Job2/3/4）

> 与 `pipeline/dataworks/mf_ai_function.py` 配套。DataWorks 粘贴前运行：  
> `py -3 pipeline/scripts/bundle_dataworks_node.py dataworks/job2_asr_node.py`

## 原则

| 项 | 要求 |
|----|------|
| **禁止** | Driver `o.execute_sql(asr_sql_template)` 等手写 MC AI SQL |
| **必须** | MaxFrame AI Function：`ManagedTextLLM` / `read_odps_model` + `generate` / `extract` / `embed` |
| **引擎** | AI 阶段 `engine_order = ["DPE", "MCSQL"]`；OSS 切分仍用 DPE + `dpe_image` |
| **Quota** | 小模型 CU：`ai_cu_quota_name`；8B+ GU：`ai_gu_quota_name`；百炼 Token 模型留空 quota |

## 节点与接口映射

| Job | 能力 | AI Function 接口 | 推荐模型 |
|-----|------|------------------|----------|
| Job2 ASR | 音频转写 | `llm.generate` + `input_audio` | `qwen3-asr-flash`（百炼 ASR，非 qwen3.6-flash 文本模型） |
| Job3 打标 | 座舱图像结构化标签 | `llm.generate` + `ImageContentType.IMAGE_URL` 或 `llm.extract` | `qwen3.6-plus` / `Qwen3-8B` + extract |
| Job4 向量 | 文本段 embedding | `llm.embed(series, simple=True)` | `text-embedding-v4` |
| Job4 向量 | 图像 embedding | `llm.embed` 或 VL embedding 模型 | `qwen3-vl-embedding` |

## 工作流参数（AI 相关）

```properties
# Quota（三选一或组合）
ai_cu_quota_name=mf_cpu_quota
ai_gu_quota_name=mf_gu_quota
ai_modelset_project=bigdata_public_modelset

# Job2
asr_model=qwen3-asr-flash
asr_language=zh-CN
ai_parallel_partitions=4

# Job3
label_model=qwen3.6-plus
label_taxonomy_oss_key=config/oms_label_taxonomy.yaml

# Job4
text_embed_model=text-embedding-v4
image_embed_model=qwen3-vl-embedding
storage_mode=separate
```

`asr_sql_template` **已废弃**，勿再配置。

## 执行模式（Driver 编排 → MC 算力）

```
1. DPE UDF：OSS 读写（engine_order=["DPE"]）— 算力在 DPE Worker
2. configure_mf_ai_engine() → engine_order=["DPE","MCSQL"]
3. Driver 建 md.DataFrame → llm.generate|embed → .execute().fetch()
   ※ VL/ASR/embedding 推理在 DPE+MCSQL Worker，不在 Driver Pod
4. DPE UDF 写 OSS payload
```

**勿误解**：代码在 Driver 进程调用 `generate()`，不等于推理在 Driver 上跑。  
base64 模式只是图像 **输入格式**；多出来的是 encode 结果经 Driver 中转再 submit（见 `job3-maxframe-vl.mdc`）。  
概念总览：`maxframe-driver-dpe-mcsql.mdc`。

## Stub 模式

模型参数留空时行为不变：Job2 空 `asr_text`、Job3 OMS 空 `values`、Job4 零向量。

## SDK

Driver 镜像需 **maxframe >= 2.7.1**（含 `maxframe.learn.contrib.llm`）。

## 参考

- 阿里云文档：MaxFrame AI Function 快速上手（generate / task / Token Quota）
- 代码：`pipeline/dataworks/mf_ai_function.py`
- 官方：https://maxframe.readthedocs.io/en/latest/
