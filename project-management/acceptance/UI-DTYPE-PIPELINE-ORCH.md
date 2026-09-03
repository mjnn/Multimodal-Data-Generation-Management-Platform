# UI-DTYPE-PIPELINE-ORCH · DataType 管线编排（组件卡） · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | UI-DTYPE-PIPELINE-ORCH · 新建数据类型：SDK 组件卡编排 |
| 日期 | 2026-09-02 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` + Playwright preview |
| Agent 自动化摘要 | editor **12/12**；kernel **15/15**；lake **6/6**；`tsc -b` 通过；editor e2e **3/3**（解析器=连续帧）；lake e2e **4/4** |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 卡 ↔ 配方编译 / hydrate + 非法 preprocess

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_editor.py`

**期望结果**
- 自定义 draft upsert 仍可用
- `label` 写入 `preprocess` 被拒
- 未知 `params` key 被拒；合法 `sample_fps` 落库
- `oms_cabin` hydrate→compile 预处理 op 顺序不变，`bbox.enabled` 仍为 false
- 梅尔 + 打标卡编译出 `stages.label.model=nvh_sem_ast`
- STFT 对 video 槽无兼容绑定；catalog 含 `label`/`embed`（`role=stage`）
- `parse_bag` 仅勾选音频时 `produces=[".wav"]`，ASR 可绑 `port_id=.wav`，视频绑定为空
- 旧 `oms_cabin` `frames_audio_topics` hydrate 为 `frames/.wav/.json`（画面=连续帧，不是 `.mp4`）
- `encode_preview` 输入不含 `.mp4`；可绑解析器 `frames` 与抽帧/`image` 槽，不可绑视频槽
- 源 kind 为入湖后缀（`frame.png` + `kind=image` → `.png`）

**通过判断标准**
- 退出码 0；12 tests ok

**执行记录**
- 2026-09-02：`Ran 9 tests in 3.977s OK`
- 2026-09-02（产出 kind）：`Ran 11 tests in 4.802s OK`
- 2026-09-02（编码器去视频）：`Ran 12 tests in 4.606s OK`
- 2026-09-02（kind 后缀）：`Ran 12 tests in 4.434s OK`
- 2026-09-02（parse 连续帧）：`Ran 12 tests in 3.552s OK`

#### A-2 · 内核配方回归

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_kernel.py`

**期望结果**
- 种子配方仍通过 `validate_recipe`；未知 op / VL bbox 仍拒绝

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02：`Ran 15 tests in 4.085s OK`
- 2026-09-02（产出 kind）：`Ran 15 tests in 5.239s OK`
- 2026-09-02（kind 后缀）：`Ran 15 tests in 4.514s OK`
- 2026-09-02（parse 连续帧）：`Ran 15 tests in 4.434s OK`

#### A-4 · 源湖入库 kind 为文件后缀

**操作步骤**
1. `py -3 hmi/backend/scripts/test_platform_datatype_lake.py`
2. `py -3 hmi/backend/scripts/test_source_upload_modality.py`
3. `py -3 hmi/backend/scripts/test_platform_lake_run_bind.py`

**期望结果**
- `put_source(..., kind="image", filename="frame.png")` 落库 `.png`
- `classify_source_filename("a.mp4")` 为 `.mp4`
- 配方 eligible kinds 为后缀集合（音频 = `AUDIO_EXTS`）

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02：lake **6/6**；upload **2/2**；bind **5/5**

#### A-3 · 前端类型检查

**操作步骤**
1. `cd hmi/frontend && npx.cmd tsc -b`

**期望结果**
- 无错误

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-02：`tsc -b` 退出码 0
- 2026-09-02（产出 kind）：`tsc -b` 退出码 0
- 2026-09-02（kind 后缀）：`tsc -b` 退出码 0
- 2026-09-02（parse 连续帧）：`tsc -b` 退出码 0

---

### A-E2E · Playwright / Selenium

#### A-E2E-1 · 从目录添加梅尔频谱 + 打标器并回看

| 脚本/Spec | `hmi/frontend/e2e/platform-dtype-editor.spec.ts` |

**操作步骤**
1. 后端 `:8000` local
2. `cd hmi/frontend && npx.cmd playwright test e2e/platform-dtype-editor.spec.ts`

**期望结果**
- 新建页可见管线编排与默认打标器卡
- 添加 audio 槽 + 梅尔频谱，保存 draft 后编辑页仍见 `pipe-step-mel_spectrogram` 与 `pipe-step-label`
- STFT 对默认 video 槽显示「无兼容输入」
- 编辑 `oms_cabin`：解析器产出芯片为 **连续帧** / `.wav` / `.json`（无 `.mp4`）；ASR 绑定「ROSBAG 解析器 · .wav」；编码器绑定可见「ROSBAG 解析器 · 连续帧」与「视频抽帧 · 连续帧」

**通过判断标准**
- 3 passed

**执行记录**
- 2026-09-02：`3 passed (19.4s)`
- 2026-09-02（产出 kind）：`3 passed (12.5s)`
- 2026-09-02（编码器去视频）：`3 passed (41.7s)`
- 2026-09-02（kind 后缀）：`3 passed`（与 lake 同跑时 26.8s/1.9s/2.0s）
- 2026-09-02（parse 连续帧）：`3 passed (15.9s)`

#### A-E2E-2 · 源湖类型列为后缀

| 脚本/Spec | `hmi/frontend/e2e/platform-lake.spec.ts` |

**操作步骤**
1. 后端 `:8000` local
2. `cd hmi/frontend && npx.cmd playwright test e2e/platform-lake.spec.ts`

**期望结果**
- 入湖 `.wav` 后表格 kind Tag 为 `.wav`（不是「音频」）
- `audio_array_spec` 仍可预检通过；`ivi_ui_stub` 仍过滤文本源

**通过判断标准**
- 4 passed

**执行记录**
- 2026-09-02（kind 后缀）：`4 passed (18.2s)`

---

## 二、人工签字 / 主观（H · 可选）

本工单无 H。A + A-E2E 全绿即可 done。

---

## 三、不在本工单范围

- 不改 `local_sdk_worker` 执行顺序
- 不改 DataWorks
- 不 publish `audio_nvh-v2`
- ASR / 抽帧 `params` 仅落库，worker 本刀不读
- worker 不按 `emit_modalities` 裁剪解析产物（仅编辑器绑定）
- 无自由拖线画布

---

## 四、点测结论

- [x] A / A-E2E — 可标 done
