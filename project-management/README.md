# 项目管理 — Rosbag Labels Platform 扩展

本目录为 **跨会话进度权威入口**，配合 `docs/prd-rosbag-labels.md` 与各 `docs/mN-implementation-notes.md` 使用。

## 先读哪个

1. **`CURRENT.md`** — 热指针：推荐下一个工单、判据、禁止抢跑
2. **`docs/m1-implementation-notes.md`** — 当前里程碑范围（M1 进行中）
3. **`docs/prd-rosbag-labels.md`** — 产品总规格

## 权威链

```text
PRD  >  docs/mN-implementation-notes.md  >  CURRENT.md 摘要
```

## 文件说明

| 文件 | 用途 |
|------|------|
| `CURRENT.md` | 跨会话开工/收工必读 |
| `tracking.csv` | 工单明细主数据（**UTF-8 BOM**，Excel 友好） |
| `progress-board.md` | Todo / Doing / Done / Blocked 看板 |
| `changelog-progress.md` | 进度变更倒序短记 |
| `milestones.md` | 各里程碑入口/出口标准 |
| `roadmap-gantt.md` | 总览甘特（Mermaid） |
| `acceptance/` | 每工单/里程碑手工验收清单 |

## 收工五件套

完成任一实施工单后必须更新：

1. `CURRENT.md`
2. `tracking.csv`
3. `progress-board.md`
4. `changelog-progress.md`
5. `acceptance/<工单ID>.md`

并在聊天中附 **手工验收清单**。

## 新会话口令

```text
按 project-management/CURRENT.md 做推荐下一个工单，结束时回写进度与 acceptance。
```
