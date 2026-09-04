### Task 8: 切片 B Playwright + 收工文档

**Files:**
- Modify: `hmi/frontend/e2e/platform-lake.spec.ts`
- Modify: `project-management/CURRENT.md`、`changelog-progress.md`、`progress-board.md`、`tracking.csv`、`acceptance/UI-DTYPE-SOURCE-NODES.md`

- [x] **Step 1:** lake-run 用例：入湖 wav → `/pipeline?tab=run` → 选 `audio_array_spec` → 在 `lake-run-slot-audio_primary`（id 以种子为准）勾选该行 → 预检通过。`ivi_ui_stub` 文本源仍不出现在视频/图块里。

- [x] **Step 2:**

```powershell
cd hmi/frontend
cmd /c "npx.cmd playwright test e2e/platform-dtype-editor.spec.ts e2e/platform-lake.spec.ts"
```

Expected: 全绿

- [x] **Step 3:** 回写进度四件套 + acceptance（A 含 editor/kernel；A-E2E 含 editor + lake）。聊天附结果表。推荐下一工单恢复 **UI-NVH-REVIEW-SAVE**（除非产品继续插队）。

- [ ] **Step 4: Commit**（仅当用户要求）

---

## Spec coverage（自检）

| Spec 节 | 任务 |
|---------|------|
| S1 删除槽位表 | T4 |
| S2 数据源节点 + 一源多文件 | T2 T4（卡内多行仍多 slot） |
| S3 开跑分块勾选 | T6 T7 T8 |
| S4 显示名 | T1 T3 T4 |
| S5 编译 slots | T2 |
| S6 只绑上方 | T2 `assert_upward_bindings` |
| S7 切片 A/B | T5 / T8 |
| 单 slot 兼容 source_ids | T6 |
| 旧配方 hydrate | T2 |
| worker 不读 output_labels | T1 并列字段 |
| 不改 DataWorks | 全局约束 |

无 TBD。`audio_primary` 等 slot id 实现时以 `seed_recipes()` 为准，测试里不要写死猜错的 id。
