# HMI-SDK-MODALITY · 原始媒体上传 + Planner 模态编排 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | HMI-SDK-MODALITY · 管线管理上传 video/audio/text + CapabilityPlanner 按模态选阶段 |
| 日期 | 2026-08-12 |
| 环境前置 | 本地数据源；SDK 依赖含 opencv；打标需 DashScope（H 可选） |
| Agent 自动化摘要 | Planner 8/8；source_upload smoke 2/2 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · CapabilityPlanner 模态门控

**操作步骤**
1. `cd piplinesdk && py -3 -m unittest tests.test_planner -v`

**期望结果**
- 预编码视频：`ingest_sources`，无 `encode_preview` / `transcribe`
- 仅音频：有 `transcribe`，无 bbox/encode
- 仅文本：`ingest_sources` + label(+embed)，无 ASR/视频阶段

**通过判断标准**
- 全部 OK

**执行记录**
- 2026-08-12：`Ran 8 tests … OK`

#### A-2 · 源上传落盘 + ingest_sources（文本）

**操作步骤**
1. `cd hmi/backend && py -3 scripts/test_source_upload_modality.py -v`

**期望结果**
- `sources/{coll}__{hash12}/source_manifest.json` 写入
- `ingest_sources` 产出 `clips_index.jsonl`（文本种子 asr_text）

**通过判断标准**
- 2/2 OK

**执行记录**
- 2026-08-12：`Ran 2 tests … OK`

---

### A-E2E · Playwright / Selenium

本工单无独立 Playwright（UI 扩展 `RosbagUploadCard`；可脚本断言见 H 路径说明）。后续可补 `e2e/pipeline-source-upload.spec.ts`。

---

## 二、人工签字 / 主观（H · 可选）

#### H-1 · 本地管线管理上传原始媒体

**操作步骤**
1. HMI 数据源 = 本地；打开「管线管理」
2. 暂存区加入 mp4 和/或 wav 和/或 txt（可不带 .bag）
3. 确认执行；观察执行列表出现 clip，worker 日志含 `stages=` 且按模态跳过

**期望结果**
- 有视频无音频：无 ASR 阶段
- 有成片视频：跳过 encode_preview，仍有抽帧
- 仅文本：仍可入队（打标依赖模型密钥）

---

## 三、不在本工单范围

- 云端 DataWorks / OSS 原始媒体发现与触发
- 多视频分 clip、复杂媒体对齐
- Playwright E2E 入库

---

## 四、点测结论

- [x] A（A-1/A-2）— Agent 自动化通过
- [ ] H-1 — 待人工（可选）
