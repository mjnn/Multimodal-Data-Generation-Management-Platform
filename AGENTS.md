# Agent 须知（跨会话）

本项目正在按 PRD 扩展 **账号 / Taxonomy / 校核 / Dataset** 能力。实施期请遵守以下入口。

## 开工前必读

1. **`project-management/CURRENT.md`** — 推荐下一个工单、判据、禁止抢跑
2. **`docs/m1-implementation-notes.md`**（或当前里程碑 Mn Notes）
3. **`docs/prd-rosbag-labels.md`** — 需求冲突时最高权威

## 收工必做

回写进度四件套 + **`project-management/acceptance/<工单ID>.md`**（**A / A-E2E / H** 分节，见 `acceptance/_FORMAT.md`），并在聊天附 **A+A-E2E 结果表** 与 **H 摘要（若有）**。

| 文件 | 说明 |
|------|------|
| `project-management/CURRENT.md` | 热指针 |
| `project-management/tracking.csv` | UTF-8 BOM |
| `project-management/progress-board.md` | 看板 |
| `project-management/changelog-progress.md` | 变更日志 |

## Cursor Rule

`.cursor/rules/project-progress-handoff.mdc`（**alwaysApply: true**）

## 新会话口令

```text
按 project-management/CURRENT.md 做推荐下一个工单，结束时回写进度与 acceptance。
```

## 权威链

```text
PRD  >  docs/mN-implementation-notes.md  >  CURRENT.md 摘要
```

## 现有系统文档

- **目录结构（必读）**：`docs/REPO_LAYOUT.md`
- 管线与 HMI 总览：`docs/WIKI.md`
- HMI 技术栈：`.cursor/rules/hmi-web-stack.mdc`
