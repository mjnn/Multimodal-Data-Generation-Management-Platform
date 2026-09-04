### Task 5: 切片 A 验收（单测 + Playwright）

**Files:**
- Modify: `hmi/frontend/e2e/platform-dtype-editor.spec.ts`
- Modify: `hmi/backend/scripts/test_platform_datatype_editor.py`（若 Task 2 已覆盖 hydrate，本任务只补 e2e）

- [x] **Step 1:** 更新 e2e

  - 新建页：`getByTestId('pipeline-orchestrator')` 可见；**没有**「源槽位（绑定可入湖 kinds）」标题；`pipe-add-source` 追加 `pipe-source-row`（`pipe-source-card` 仍为 1）
  - STFT 用例：默认源 kinds=`.mp4` →「无兼容输入」
  - `oms_cabin`：`pipe-source-card` count=1、`pipe-source-row` count=4（含 `rosbag`）；解析器芯片「连续帧」；ASR「ROSBAG 解析器 · .wav」；编码器「ROSBAG 解析器 · 连续帧」

- [x] **Step 2:** 后端 `:8000` local 已起时：

```powershell
cd hmi/frontend
cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts"
```

Expected: 3 passed（若新增用例则全绿）

- [x] **Step 3:** `py -3 hmi/backend/scripts/test_platform_datatype_editor.py` 与 `test_platform_datatype_kernel.py`

- [x] **Step 4:** 写 `project-management/acceptance/UI-DTYPE-SOURCE-NODES.md` 的 **A / A-E2E**（切片 B 在 Task 8 补全）

- [ ] **Step 5: Commit**（仅当用户要求）

---

