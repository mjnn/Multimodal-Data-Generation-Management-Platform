# DESIGN-M10 · Taxonomy 语义中枢

| 字段 | 内容 |
|------|------|
| 状态 | **已定稿** |
| 决议 | **R-UI-M10-1**：方案 **A−+B**（Hub 三 Tab + 全站 TaxonomyContextBar） |
| 确认日 | 2026-07-31 |

---

## 1. TaxonomyContextBar（方案 B）

- **位置**：业务页 `PageHeader` 下方；高度 36–40px；全宽浅底条  
- **内容**：`Published: {version_code}` · 可选 `本页契约: {code}` · 链接 `数据洞察 →`（`/taxonomy?tab=insights`）  
- **嵌入页**：总览、校核工作台、数据集列表/详情、管线设置  
- **状态色**：一致 = default；clip 契约 ≠ published = `warning`；dataset 混合 = `orange` Tag  

---

## 2. Taxonomy Hub（方案 A−）

**路由**：`/taxonomy`；query `tab=versions|insights|proposals`

| Tab | 内容 |
|-----|------|
| **版本** | 现有版本 Table + 横向 **lineage 时间线**（clone 链，非全屏 DAG） |
| **数据洞察** | 覆盖率 Table：`label_id`、名称、reviewed 数、enum 分布 Progress、缺口 Tag |
| **提案队列** | proposal Table + 状态筛选；Drawer 详情（证据 clip 列表、建议文案） |

**版本详情 Drawer**：diff（选对比版本）、impact 数字、进入 draft 编辑（现有编辑器）。

---

## 3. 数据集创建 · 契约区

- **Taxonomy 契约** Select：  
  - `默认（各 clip 校核版本）` — 不传 `taxonomy_version_id`（R10/R13）  
  - `锁定：{version_code}` — 写入 `filter_json.taxonomy_version_id`  
- **预览 panel**：版本分布 mini 表 + 既有 R10 warning  

---

## 4. 校核工作台

- ContextBar + Header 文案：`校核契约 {version_code}`  
- 若 ≠ published：Alert + 链接 Hub diff  

---

## 5. 组件与 Tokens

- 复用 Ant Design 6；不更换全站主题  
- 节点 ID：`Typography.Text code` 11px 次要  
- 洞察热力：Table + `Progress`（不用重图表库）  
- 提案：Table + Drawer（不用 Kanban）  

---

## 6. 反模式

- 不做全站 Taxonomy 抽屉（方案 C 推迟 M11）  
- 不在首屏阻塞式 DAG  
- 提案不得一键 auto-publish  

---

**实施工单**：M10.4（Hub）、M10.5（ContextBar）、M10.6（Dataset 契约）须引用本文件。
