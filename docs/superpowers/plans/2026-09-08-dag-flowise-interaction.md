# DAG Flowise 交互 Implementation Plan

> **For agentic workers:** Use executing-plans. Steps use checkbox syntax.

**Goal:** DataType 编排画板达到 Flowise/Dify 级交互（搜、拖、左入右出、条件边颜色、Elkjs 排布）。

**Architecture:** 校验进 `ioContract.canConnectGraph`；排布进 `dagLayout.layoutGraphElk`；画板只改 xyflow 投影与 CSS。`recipe.graph` 仍是 nodes/edges + position。

**Tech Stack:** React 19、`@xyflow/react`、`elkjs`、Playwright。Windows：`npm.cmd` / `npx.cmd`。

## Global Constraints

- 勿改 DataWorks；勿 publish `audio_nvh-v2`
- 点击组件栏添加必须保留
- 控制流 palette 仍不提供校核/导出

---

## Task 1: canConnectGraph + Elkjs 布局

- [ ] `ioContract.ts` 导出 `canConnectGraph`
- [ ] `dagLayout.ts` + `elkjs`
- [ ] `scripts/dagLayout.assert.mts`

## Task 2: Palette + Canvas

- [ ] 搜索、拖放 MIME、`onAdd(opId, position?)`
- [ ] MiniMap、自动排布、左入右出、then/else 边
- [ ] 画布高度；更新 e2e 高度上限

## Task 3: A-E2E + 浏览器

- [ ] Playwright 新断言
- [ ] 编辑器里拖放 + 自动排布走一遍
