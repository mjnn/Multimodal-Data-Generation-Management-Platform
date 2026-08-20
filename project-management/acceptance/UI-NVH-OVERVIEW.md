# UI-NVH-OVERVIEW · 纯音频 NVH 总览/探索/校核媒体展示验收

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | UI-NVH-OVERVIEW · `audio_nvh_timeline` 频谱时间轴 + typed clip 列表 |
| 日期 | 2026-08-20 |
| 环境前置 | A-E2E 需本机后端 `:8000` + Playwright preview `:4175` |
| Agent 自动化摘要 | 产品拍板：四通道 mel + SPL + 波形共用时间轴（非舱内四路、非 ASR）；A 4/4 + tsc；A-E2E **2/2**；**未 publish** `audio_nvh-v2`；NVH Explorer 详情标签右侧改为 `ClipLabelTreeView`（去除 raw `LabelRail`），并对齐舱内多模形态 |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · 视图模板 + bootstrap + typed 列表

**操作步骤**
1. `py -3 hmi/backend/scripts/test_audio_nvh_view.py -v`

**期望结果**
- `audio_nvh_timeline` 注册；`audio_array_spec.overview_view` 指向它
- bootstrap 返回 4 通道 mel/spl/waveform URL + labels
- `list_clips_light_for_data_type('audio_array_spec')` 按 `pipeline_execution.data_type_id` 过滤（非空）；IVI 隔离
- **hotfix ISOLATE-DTYPE-CLIPS（同日）**：`oms_cabin` 不再全量 `list_clips_light`；排除 audio/IVI typed active run（见 `acceptance/ISOLATE-DTYPE-CLIPS.md`）

**通过判断标准**
- unittest 全绿

**执行记录**
- 通过（2026-08-20）：`4/4`

#### A-2 · 配方回归仍为 NVH 时间轴

**操作步骤**
1. `py -3 hmi/backend/scripts/test_audio_array_spec.py -v` 中 `TestAudioArraySpecRecipe`

**期望结果**
- `overview_view == audio_nvh_timeline`

**执行记录**
- 通过（同日脚本 `3/3`，含样例解析）

#### A-3 · 前端 TypeScript

**操作步骤**
1. `cd hmi/frontend && node node_modules/typescript/bin/tsc -b --pretty false`

**期望结果**
- exit 0

**执行记录**
- 通过（2026-08-20）

---

### A-E2E · Playwright / Selenium

#### A-E2E-1 · DataType 首页含麦克风阵列并进入隔离工作区

| 脚本/Spec | `hmi/frontend/e2e/datatype-workspace.spec.ts` |

**操作步骤**
1. 本机 API `HMI_DATA_SOURCE=local` 在 `:8000`
2. `cd hmi/frontend && node node_modules/@playwright/test/cli.js test e2e/datatype-workspace.spec.ts`

**期望结果**
- 卡片 `data-type-card-audio_array_spec` 可见
- 进入 `/w/audio_array_spec`，banner 含「麦克风阵列」与 `audio_nvh_timeline`
- OMS / IVI 工作区仍隔离

**通过判断标准**
- Playwright 1 passed

**执行记录**
- 通过（2026-08-20）：`1/1`（约 30.8s）

#### A-E2E-2 · NVH Explorer 标签展示对齐舱内形态

| 脚本/Spec | `hmi/frontend/e2e/nvh-label-tree.spec.ts` |

**操作步骤**
1. `node node_modules/@playwright/test/cli.js test e2e/nvh-label-tree.spec.ts`

**期望结果**
- 进入 `clips/:clipId?run_id=...` 后，NVH 标签树容器 `data-testid=audio-nvh-label-tree` 可见
- 原右侧 `LabelRail` 容器 `data-testid=audio-nvh-label-rail` 不存在

**通过判断标准**
- 以上断言均通过

**执行记录**
- 通过（2026-08-20）：`1/1`（chromium）

---

## 二、人工签字 / 主观（H · 可选）

无。可脚本化 UI 已用 A-E2E；有真实 `.dat` run 时人工点进 Clip 看四通道谱图属探索，不阻塞 done。

---

## 三、不在本工单范围

- **publish** `audio_nvh-v2`
- 语义标签（L6）写回 API / 校核保存
- HMI 在线 H-2
- 舱内 `audio_spec_asr` 视图（保留模板名供未来 ASR 类型）

---

## 四、点测结论

- [x] A / A-E2E — 可标 done
