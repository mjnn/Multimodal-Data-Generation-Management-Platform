### Task 9: 橱窗锁死 `labels_tree`（切片 C）

**Files:**
- Modify: `hmi/frontend/src/utils/overviewLayout.ts`（`ensureLabelsTree(detail)`）
- Modify: `hmi/frontend/src/components/datatype/OverviewComposer.tsx`（`widget_id==='labels_tree'` hide delete and widget switch; `data-testid="overview-locked-labels_tree"`）
- Modify: `hmi/frontend/src/pages/ClipExplorerPage.tsx` + `ReviewClipMediaPanel.tsx`（`labels_tree` 渲染 `labels_json` 树，testid `overview-runtime-labels_tree`）
- Mirror already in backend `hydrate_overview`

- [ ] **Step 1: Composer lock**

```tsx
const locked = card.widget_id === 'labels_tree'
// Delete button: {!locked && <Button ... data-testid={`overview-remove-${card.widget_id}`} />}
```

`ensureLabelsTree` on every `onChange` of detail and on preset fill.

- [ ] **Step 2: Runtime**

When `detailIds.includes('labels_tree')`, show the same `<pre>` currently used for `json_tree` but bind clip labels (`data-testid="overview-runtime-labels_tree"`). Keep `json_tree` path for structured JSON.

- [ ] **Step 3: Playwright**

On create page: `overview-locked-labels_tree` visible; `overview-remove-labels_tree` count 0.

- [ ] **Step 4: tsc + editor e2e PASS**

---

