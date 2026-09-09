# Design: 源湖数据单元（手动成组）

> 日期：2026-09-08  
> 状态：draft  
> 范围：HMI 源湖 + 开跑绑定。不改 DataWorks、不 publish `audio_nvh-v2`、不把 Sample 重新做成主路径。

## 1. 问题

问题音频判定等配方有 **两个必选数据源**（`.wav` + `.json`）。文件先各自入湖，开跑时按槽位独立勾选，可以把 A 段录音和 B 段标签凑成一对。

已有 `collection_id` 只表示 **同一次上传会话**（D9：同批不自动绑定）。用户要求：

1. 入湖之后 **手动** 把已有文件组成一个「数据单元」
2. 同一个文件可以同时属于多个单元
3. 多槽开跑时 **只能选同一单元** 里的文件；点选整个单元后仍可在单元内微调勾选

## 2. 已拍板

| ID | 决策 | 选择 |
|----|------|------|
| U1 | 模型 | 独立 `platform_source_unit` + 成员表（多对多）。不复用 Sample，不改写 `collection_id` |
| U2 | 成组时机 | 文件已入湖后，在「数据源」勾选组成；不是上传瞬间自动成组 |
| U3 | 开跑 UX | 多槽：先选单元（自动填槽）+ 单元内微调。单槽：维持现状，散文件可选 |
| U4 | Sample | 仍内部；每次开跑 `create_sample`。单元只约束选用集合 |
| U5 | 约束范围 | 配方 **槽位数 ≥ 2** 时开跑 UI 出现单元列表。`unit_id` **必须**当：(a) 必选槽 ≥ 2（如 `audio_defect`），或 (b) 本次 assignments **填了 ≥ 2 个槽**（如 `oms_cabin` 同时勾 bag+音频）。只填一个可选槽时仍可不开单元。本次 assignments 里出现的全部 `source_id` 都必须是该单元成员 |

## 3. 数据模型

```text
platform_source_unit
  unit_id TEXT PK
  title TEXT          -- 可空；展示时空则用成员文件名拼接
  created_at TEXT NOT NULL

platform_source_unit_member
  unit_id TEXT NOT NULL → platform_source_unit
  source_id TEXT NOT NULL → platform_source
  PRIMARY KEY (unit_id, source_id)
```

`ensure_platform_schema()` 建表。删单元只删这两张表的行，**不**删 `platform_source`。源文件物理删除时成员行一并清掉（或开跑时当缺失）。

成员下限：**创建/更新后至少 2 个不同 `source_id`**。不限制 kind 组合（同一单元可以两个 wav；开跑时由配方槽位再筛）。

## 4. API（`/api/platform`）

均仅 **local** 可写（与 `POST /sources` 相同）。读：与现有 sources 一致（需 overview/pipeline 权限）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/source-units` | 列表；每项含 `members: [{source_id, kind, filename}]` |
| POST | `/source-units` | `{ title?, source_ids }` → 建单元 |
| PATCH | `/source-units/{unit_id}` | `{ title?, source_ids? }`；`source_ids` 整表替换成员 |
| DELETE | `/source-units/{unit_id}` | 解散 |

`GET /sources` 每条可附 `unit_ids: string[]`（该文件所属单元），便于湖列表展示。

开跑：

- `PreflightIn` / `RunIn` 增加可选 `unit_id`
- 配方 **必选槽 ≥ 2**，或本次填了 **≥ 2 个槽** 时必须提供 `unit_id`；缺则 400，`code=SOURCE_UNIT_REQUIRED`
- 解析后 `assignments` 中出现的全部 `source_id`（含可选槽）必须是该单元成员；否则 400，`code=SOURCE_UNIT_MISMATCH`
- 单元候选：必选槽 ≥ 2 时成员 kinds 覆盖 **全部必选槽**；可选多槽（如 oms_cabin）时成员能覆盖 **≥ 2 个槽**
- 单槽配方（`ivi_ui_stub` / `audio_array_spec`）忽略 `unit_id`

`GET /source-units?eligible_for={data_type_id}` 按上面规则过滤候选。

## 5. 源湖 UI

「数据源」表：勾选行（已入库）→ **组成单元**。可选填标题。成功后按单元分组展示（折叠：单元标题 + 成员文件）。

- 解散、改成员、改标题
- 采集批 Tag 仍显示，文案保持「同批不自动绑定」
- 一个文件出现在多个单元里：成员行可重复出现在不同分组下，不复制湖文件

test id：`lake-compose-unit`、`lake-unit-row`、`lake-unit-title`。

## 6. 开跑 UI（`LakeRunBindPanel`）

当当前类型 **槽位数 ≥ 2**（`audio_defect` 双必选，`oms_cabin` 四路可选）：

1. 上方 **单元列表**（`lake-run-unit-list`）：`GET /source-units?eligible_for=` 过滤后的候选
2. 点选一个单元 → 各槽按 kind **自动勾选** 该单元内匹配文件（每槽若多份则先勾满 `cardinality_min`，其余保持未勾，用户微调）
3. 槽位表只展示该单元成员；勾选不能超出成员
4. `audio_defect`：未选单元时不展示散文件勾选表
5. `oms_cabin`：未选单元时仍可勾 **单个** 可选槽的散文件；填两个及以上槽必须先选单元

单槽类型：不出现单元列表，现有按槽勾散文件不变。

## 7. 错误

| 情况 | 行为 |
|------|------|
| 组成单元 < 2 个文件 | 前端拦 + API 400 |
| 成员引用已删 source | PATCH/开跑当缺失；列表不展示空 id |
| 多槽未选单元 | 预检/开跑 400 `SOURCE_UNIT_REQUIRED` |
| 勾了单元外文件 | 400 `SOURCE_UNIT_MISMATCH` |
| 单元缺某必选 kind | 不进开跑候选列表；若仍 POST 则走现有预检 missing |

## 8. 非目标

- 上传瞬间按文件主名自动配对
- 把 Sample 重新做成用户可编辑对象
- 云模式 POST 单元
- 改 DataWorks / 配方 graph 语义
- publish `audio_nvh-v2`

## 9. 验收

**A**

- 建单元：同一 wav 可加入两个单元（各配不同 json）
- 多槽 `preflight`/`create_run`：无 `unit_id` 或跨单元 → 失败；同单元微调子集 → 通过
- 单槽类型：无单元仍可开跑

**A-E2E**

- 源湖：入两个文件 → 组成单元 → 列表可见 `lake-unit-row`
- 管线管理选 `audio_defect`：出现单元列表；点选后 wav/json 槽自动填；无法勾另一单元文件

不写 H 主观项。
