### Task 8: 检查器条件 UI + 上云黄警告（切片 E）

**Files:**
- Create: `hmi/frontend/src/components/datatype/DagNodeInspector.tsx`
- Modify: `hmi/frontend/src/pages/DataTypeEditorPage.tsx`

**Interfaces:**
- If node selected (`type==if`): Form.List of predicates; field Select from `source.kind | source.slot_id | asr.avg_confidence | asr.has_text | label.avg_confidence | labels.` custom input；op Select from the 10 ops
- Warning Alert `data-testid="dag-cloud-lossy"` text exactly: `本地按图执行；上云只跑公共前缀。` when `graphIsLossy(graph)`；always show the first sentence in a muted hint `data-testid="dag-cloud-hint"`

- [ ] **Step 1: Implement inspector + alerts** (no extra unit test runner; Playwright in Task 12 covers hint)

```tsx
<Alert type="info" data-testid="dag-cloud-hint" message="本地按图执行；上云只跑公共前缀。" />
{lossy ? (
  <Alert type="warning" data-testid="dag-cloud-lossy" message="图含 if 或打标后节点：上云不会执行这些分支。" />
) : null}
```

Do not block draft or published save.

- [ ] **Step 2: tsc PASS**

---

