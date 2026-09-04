### Task 7: 开跑 UI 分块勾选

**Files:**
- Modify: `hmi/frontend/src/components/pipeline/LakeRunBindPanel.tsx`
- Modify: `hmi/frontend/src/api/index.ts` + `types.ts`（`createPlatformRun` 增加 `assignments?`）

每个 `recipe.slots` 一块 `data-testid="lake-run-slot-{id}"`：标题 `slot.title || slot.id`，副文案 kinds 与基数。块内表格只列出 kind 合格源。勾选写入 `Record<slotId, sourceId[]>`。预检/开跑 POST `assignments`。

去掉「整表一个 checkbox 再自动分槽」作为主路径。

- [x] **Step 1:** 改面板

- [x] **Step 2:** `tsc -b`

- [ ] **Step 3: Commit**（仅当用户要求）

---

