# DataType DAG 交互（Flowise/Dify 手感）

> 日期：2026-09-08  
> 范围：HMI 数据类型编辑器 `PipelineDagCanvas` + `ComponentPalette`。不改 DataWorks、不 publish `audio_nvh-v2`、不改 `recipe.graph` 语义。

## 目标

编排图画成 Flowise/Dify 一类：组件栏可搜可拖、画布够大、左入右出、then/else 有颜色、连错会挡、一键 Elkjs 从左到右排布。

## 行为

| 项 | 约定 |
|----|------|
| 点击组件栏 | 仍添加节点（现有 Playwright 依赖） |
| 拖到画布 | 在落点 `screenToFlowPosition` 创建 |
| 搜索 | `palette-search`；有字时展开匹配组 |
| 画布 | 高度约 `min(560px, 62vh)`，MiniMap 左下，不挡检查器 |
| 端口 | 左 `in`、右输出；if 右侧 `then`/`else` |
| 边 | then 绿、else 红；其余中性 |
| 连线 | `canConnectGraph`（`ioContract`）；自环/源当目标/类型不兼容 → 拒绝 |
| 自动排布 | `dag-auto-layout`，Elkjs layered RIGHT，写回 `position` |

## 非目标

Flowise 运行时、节点商店、聊天调试；改 graph 的 nodes/edges 字段语义。

## 验收

- `platform-dtype-editor.spec.ts` 高度断言改为 ≥360 且 <720。
- 新断言：`palette-search`、`dag-auto-layout`、then/else 边 class。
- 浏览器：打开 `audio_defect` 或 `oms_cabin` 编辑器，拖一次、点一次自动排布。
