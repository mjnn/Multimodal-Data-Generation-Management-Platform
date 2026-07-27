# 当前进度指针（跨会话权威入口）



> 最后更新：2026-07-23  

> 更新人：Agent（M6.4 + M6.5 路由完成）



---



## 一眼看懂



| 字段 | 当前值 |

|------|--------|

| 当前里程碑 | **M6** · 校核页 v2（逐标签 · 双模式） |

| 推荐下一个工单 | **M6.6** — E2E + acceptance |

> **仓库目录（2026-07 monorepo）**：代码在 `hmi/`、`pipeline/`、`shared/`、`piplinesdk/`；路径对照见 [`MONOREPO_PATHS.md`](./MONOREPO_PATHS.md) · [`docs/REPO_LAYOUT.md`](../docs/REPO_LAYOUT.md)。

| 禁止抢跑 | 全面 E2E 须本地/ECS 有 demo 校核数据 |



---



## 新会话开场白



```text

按 project-management/CURRENT.md 做 M6.6。

前端 ReviewWorkbenchPage 已接入 v2 API；/review 单页，/review/:clipId 重定向。

```



---



## 工单队列



| 顺序 | ID | 标题 | 状态 |

|------|-----|------|------|

| 1 | M6.1 | field review DB + merge | **done** |

| 2 | M6.2 | v2 task queue API | **done** |

| 3 | M6.3 | submit + audit | **done** |

| 4 | M6.4 | ReviewWorkbenchPage | **done** |

| 5 | M6.5 | 路由替换 + 移除旧页 | **partial**（路由已换；ReviewQueue/Detail 文件待删） |

| 6 | M6.6 | pytest + Playwright + acceptance | **todo** ← 推荐 |
