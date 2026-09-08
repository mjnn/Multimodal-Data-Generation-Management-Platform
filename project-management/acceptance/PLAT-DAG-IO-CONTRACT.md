# PLAT-DAG-IO-CONTRACT · DAG 节点 I/O 契约 · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`  
> 规格：`docs/superpowers/specs/2026-09-07-dag-io-contract-design.md`

| 字段 | 内容 |
|------|------|
| 工单 | PLAT-DAG-IO-CONTRACT · 编排输入封闭、最小输入黄叹号、期望输出、节点试跑 |
| 日期 | 2026-09-07 |
| 环境前置 | A 单测不需双端；A-E2E 需 HMI 后端 `:8000` local + 前端 `:5174` |
| Agent 自动化摘要 | io_contract **14/14**；kernel **10/10**；graph_runtime **9/9**；catalog_ops **9/9**；recipe_graph **33/33**；Playwright editor **14/14 (50.5s)** |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · diagnose_graph 最小输入 / 未声明产物

**操作步骤**
1. `py -3 hmi/backend/scripts/test_io_contract.py -v`

**期望结果**
- label 零输入 → `min_input`
- 绑上游未声明的 `.wav` → `unbound_kind`
- frames 边 OK

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-07：`Ran 14 tests in 0.122s` OK（含 A-1～A-4 同文件）

#### A-2 · 消费绑定：未绑 wav 则 `include_audio=False`

**操作步骤**
1. 同上 `test_io_contract.py` 中 `TestConsumeFlags`

**期望结果**
- 仅 frames 边：`include_audio` False
- 另绑 `.wav`：True
- 旧 `out` 且 emit 含 wav：True；emit 仅 frames：False

**通过判断标准**
- 对应用例 pass

**执行记录**
- 2026-09-07：4 consume 用例 OK

#### A-3 · 生产者缺期望产物记在该节点

**操作步骤**
1. `test_execute_missing_wav_fails_parse_node`

**期望结果**
- parse 期望 `.wav` 但未写出 → `RuntimeError` 文案 `节点 parse 未按期望输出` 且含 `.wav`

**通过判断标准**
- 该用例 pass

**执行记录**
- 2026-09-07：OK

#### A-4 · `until_key` + `include_ai=False` 不跑打标、不报「AI打标器未执行」

**操作步骤**
1. `TestExecuteUntil`

**期望结果**
- `until_key=parse` 只跑 parse_bag
- `until_key=lab` + `include_ai=False` 打标为 `checked`，sdk_runner 不调 label

**通过判断标准**
- 该用例 pass

**执行记录**
- 2026-09-07：OK

#### A-5 · kernel / runtime / catalog / graph 回归

**操作步骤**
1. `py -3 hmi/backend/scripts/test_capability_kernel.py`
2. `py -3 hmi/backend/scripts/test_platform_graph_runtime.py`
3. `py -3 hmi/backend/scripts/test_platform_catalog_ops.py`
4. `py -3 hmi/backend/scripts/test_platform_recipe_graph.py`

**期望结果**
- 原有套件全绿

**通过判断标准**
- 退出码 0

**执行记录**
- 2026-09-07：kernel **10/10**；graph_runtime **9/9**；catalog_ops **9/9**；recipe_graph **33/33**

---

### A-E2E · Playwright

#### A-E2E-1 · 打标器未连源：黄叹号

| 脚本/Spec | `hmi/frontend/e2e/platform-dtype-editor.spec.ts`（`DAG I/O warn bang…`） |

**操作步骤**
1. 新建类型，删 `src-1→stage-label` 边
2. 断言 `dag-io-warn-stage-label`

**期望结果** · **通过判断标准** · **执行记录**
- 黄叹号可见
- 2026-09-07：该 spec 含此步骤；全文件 **14/14 (50.5s)**（`PLAYWRIGHT_SKIP_WEBSERVER=1` `PLAYWRIGHT_BASE_URL=http://127.0.0.1:5174` `npx.cmd playwright test e2e/platform-dtype-editor.spec.ts`）

#### A-E2E-2 · 连上 parse_bag 输出后叹号消失

**操作步骤**
1. 源槽加 `.bag`，加入未连接的 parse_bag → `dag-io-warn-.*parse_bag`
2. 检查器把 parse 绑到数据源、打标器绑到「ROSBAG 解析器 · 连续帧」
3. 两处叹号消失

**期望结果**
- parse / label 黄叹号 `toHaveCount(0)`

**执行记录**
- 2026-09-07：同上 14/14

#### A-E2E-3 · 检查器试跑无源提示需要数据源

**操作步骤**
1. 打开节点检查器，点「运行到此节点」，不选源湖文件

**期望结果**
- `dag-expected-outputs`、`dag-node-probe` 可见
- `dag-probe-result` 含 `需要数据源才能试跑`

**执行记录**
- 2026-09-07：同上 14/14

---

## 二、人工签字 / 主观（H · 可选）

> 本工单无 H。

---

## 三、不在本工单范围

- 改 DataWorks / DPE / 云端 Job 顺序
- publish `audio_nvh-v2`
- 宣称 IVI 业务打标完成
- 拦保存（黄叹号仅提示）
- 无 graph 的旧 `plan_and_run`

---

## 四、点测结论

- [x] A / A-E2E 全绿；无 H — 可标 done
