# {Mx.y} · {标题} · 验收清单

> 格式：`project-management/acceptance/_FORMAT.md`

| 字段 | 内容 |
|------|------|
| 工单 | Mx.y · {标题} |
| 日期 | YYYY-MM-DD |
| 环境前置 | API / Web / E2E 需双端：是/否 |
| Agent 自动化摘要 | （收工时填） |

---

## 一、Agent / 自动化

### A · 单元 / API / 构建

#### A-1 · …

**操作步骤**
1. …

**期望结果**
- …

**通过判断标准**
- …

**执行记录**（Agent 收工填）

---

### A-E2E · Playwright / Selenium

> 无 UI 改动可整节写「本工单无 A-E2E」。

#### A-E2E-1 · …

| 脚本/Spec | `frontend/e2e/….spec.ts` |

**操作步骤**
1. `npx playwright test e2e/….spec.ts`

**期望结果** · **通过判断标准** · **执行记录**（Agent）

---

## 二、人工签字 / 主观（H · 可选）

> 仅签字/主观；可脚本化 UI 不得放此处。

#### H-1 · …

---

## 三、不在本工单范围

- …

---

## 四、点测结论

- [ ] A / A-E2E / H（或无 H）— 可标 done
