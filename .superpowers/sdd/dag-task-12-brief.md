### Task 12: Playwright 收口 + 验收文档

**Files:**
- Modify: `hmi/frontend/e2e/platform-dtype-editor.spec.ts`
- Create: `project-management/acceptance/UI-DTYPE-DAG-CANVAS.md`
- Modify: `project-management/CURRENT.md`, `tracking.csv`, `progress-board.md`, `changelog-progress.md`

**A-E2E 必须：**

1. 新建页 `dag-canvas` 可见；`palette-op-if` 可点出 if 节点
2. `dag-node-label` 存在且无删除按钮
3. `overview-locked-labels_tree` 存在；`overview-remove-labels_tree` 为 0
4. `dag-cloud-hint` 文案含 `本地按图执行；上云只跑公共前缀。`
5. 保存 draft 成功

**A 单测：** `test_platform_recipe_graph.py` + `test_platform_graph_runtime.py` + 既有 editor 套件。

- [ ] **Step 1: Run e2e**

working_directory: `hmi/frontend`  
`cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"`

- [ ] **Step 2: Write acceptance** with sections **A** (commands + pass counts), **A-E2E** (playwright), **H** only if someone visually signed the canvas.

- [ ] **Step 3: Progress 四件套** — 本工单 status 按切片：A–C 可先标部分完成；整单 done 仅当 D 的 runtime 单测也过。若 Task 11 只落地 guard + source-kind if，在 acceptance 写明「ASR/标签 if 本地仍 RuntimeError，符合计划 Task 11 护栏」。

---

## Spec coverage

| Spec | Task |
|------|------|
| D1–D2 本地真 DAG / 不上云图执行 | 10–11 |
| D3 / D8 表达式 | 2 |
| D4 / §7 橱窗 + 锁树 | 5, 9 |
| D5 打标后节点 | 1, 10 |
| D6 / §6 投影压扁 | 4, 5 |
| D7 互斥汇合 | 1, 10 |
| D9 graph 权威 | 5 |
| D10 黄警告仍可 publish | 8 |
| D11 xyflow | 7 |
| ivi 补打标器 | 3, 5 |
| 无 graph 旧路径 | 11 |
| 不改 DataWorks | Global Constraints |
| Playwright | 7, 9, 12 |

## Placeholder / 一致性

- `_require_any_kinds_from_slots` 若为 private：在 `recipe_graph.py` 复制或改为公开，不要留「类似 Task N」
- `_chain()` 的 `op_id` 必须改成 `OPERATORS` 里真实 id（实现时打开 `operators.py` 选一个 preprocess）
- `pin_label_last` 不再把 label 挪到最后，与 D5 一致
- 前端没有 vitest：内核行为以后端单测为准；UI 用 Playwright
