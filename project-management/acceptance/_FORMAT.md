# 验收清单 · 格式规范

> 权威来源：`web-agent-delivery` skill → `references/acceptance-checklist-format.md`  
> 模板：同目录 `_TEMPLATE.md`  
> **仓库路径**：验收命令默认在仓库根执行；后端 `hmi/backend/`、脚本 `hmi/scripts/`、`pipeline/scripts/`。见 [`docs/REPO_LAYOUT.md`](../../docs/REPO_LAYOUT.md)。

## 三类验收项

| 类型 | 编号 | 执行者 | 说明 |
|------|------|--------|------|
| 单元/API/构建 | `A-1`, … | Agent / CI | pytest、build、curl、脚本 |
| **E2E 浏览器** | `A-E2E-1`, … | Agent / CI | **Playwright / Selenium**（脚本入库） |
| 人工签字/主观 | `H-1`, …（尽量少） | 人 | 出口签字、主观体验、探索性 |

## 分工原则

- **可脚本化 UI → A-E2E，不写 H。**
- H 仅：签字、主观、探索、SSO/CAPTCHA、环境差异等。
- 工单无 H 项时：**A + A-E2E 全绿即可 done**。

## 单条用例四块

操作步骤 · 期望结果 · 通过判断标准 · 执行记录

## Agent 收工（聊天 + acceptance 文件）

```markdown
### A · 单元 / API / 构建（已执行）
| 编号 | 结果 | 证据 |

### A-E2E · Playwright / Selenium（已执行）
| 编号 | 结果 | 证据 |

### H · 人工签字（若有）
| 编号 | 摘要 |
```

## 反模式

- UI 回归写 H 不写 A-E2E
- Playwright/Selenium 写进 H 类
- 每工单堆很多 H 项
